from ..commercial import offer_quote, require_complete
from ..money import decimal
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..admission import (SpecificationCheck, admission_audit_payload, require_company_admission)
from ..database import get_db
from ..deps import (
    CurrentUser,
    get_company,
    get_current_user,
    get_membership,
    notify,
    require_company_admin,
    require_company_buyer,
    require_company_seller,
    require_verified_company,
)
from ..models import CapacityEntry, CapabilityPassport, Deal, Need, Offer, OfferDraft, Product
from ..matching import ACTIVE_NEED_STATUSES, need_is_current, offer_unit_price, order_unit, run_market_rematch
from ..offer_draft import _matches_need, available_capacity_units, build_offer_draft, changed_fields
from ..schemas import DealOut, OfferDraftIn, OfferDraftOut, OfferIn, OfferOut, OfferPatch, OfferSelectIn
from ..resources import reserve, reservations, free_stock, occupies
from ..trust import append_audit_event, record_human_approval

from ..requirements import require_current_evidence

router = APIRouter(tags=["offers"])


@router.get("/needs/{need_id}/offers", response_model=list[OfferOut])
async def list_offers(
    need_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.scalar(select(Need).where(Need.id == need_id).with_for_update())
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")

    membership = await get_membership(db, need.company_id, user.id)
    if membership and membership["can_buy"]:
        query = select(Offer).where(Offer.need_id == need.id)
    else:
        seller_companies = (
            await db.execute(
                text(
                    "SELECT company_id FROM auth.company_members "
                    "WHERE user_id = :uid AND can_sell = true"
                ),
                {"uid": user.id},
            )
        ).scalars().all()
        if not seller_companies:
            return []
        result = await db.execute(
            select(Offer).where(
                Offer.need_id == need.id, Offer.company_id.in_(seller_companies)
            )
        )
        return result.scalars().all()

    result = await db.execute(query.order_by(Offer.created_at))
    return result.scalars().all()


@router.post("/needs/{need_id}/offer-draft", response_model=OfferDraftOut, status_code=status.HTTP_201_CREATED)
async def prepare_offer_draft(
    need_id: uuid.UUID,
    data: OfferDraftIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Черновик КП из подтверждённых данных. Обязательство создаёт только человек."""
    need = await db.scalar(select(Need).where(Need.id == need_id).with_for_update())
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_company_seller(data.company_id, user, db)
    await require_verified_company(data.company_id, user, db)
    if need.company_id == data.company_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Нельзя готовить предложение на потребность своей компании",
        )

    await require_current_evidence(db, need)
    if need.status not in ACTIVE_NEED_STATUSES or not need_is_current(need) or need.visibility != "open_anonymized":
        raise HTTPException(404, "Потребность недоступна")
    products = list(
        (await db.execute(select(Product).where(Product.company_id == data.company_id))).scalars().all()
    )
    passport = await db.get(CapabilityPassport, data.company_id)
    capacity = list(
        (await db.execute(select(CapacityEntry).where(CapacityEntry.company_id == data.company_id)))
        .scalars()
        .all()
    )
    held = await reservations(db, data.company_id)
    from ..resource_scopes import conversion_for, occupied_units
    free_capacity = 0
    for row in capacity:
        if not date.today() <= row.date <= need.deadline_date:continue
        conversion=conversion_for(row,need.category,need.subcategory,order_unit(need.characteristics))
        if conversion is None:continue
        free=max(0,row.available_units-sum(occupied_units(r) for r in held if r.capacity_entry_id==row.id and occupies(r)))
        free_capacity += free // conversion['resource_units_per_order_unit']
    stocks = {product.id: await free_stock(db, product, held) for product in products}
    result = await build_offer_draft(
        need=need,
        products=products,
        passport=passport,
        capacity_units=free_capacity,
        stock_by_product=stocks,
    )

    draft = OfferDraft(
        need_id=need.id,
        company_id=data.company_id,
        created_by_user_id=user.id,
        status="draft",
        payload=result.payload(),
        fields=[item.as_dict() for item in result.fields],
        missing=result.missing,
        warnings=result.warnings,
        explanation=result.explanation,
    )
    db.add(draft)
    await db.flush()
    await append_audit_event(
        db,
        event_type="offer_draft_generated",
        entity_type="offer_draft",
        entity_id=draft.id,
        actor_user_id=user.id,
        actor_company_id=data.company_id,
        source_refs=[{"type": "need", "id": str(need.id)}],
        explanation="Агент подготовил черновик предложения из подтверждённых данных продавца.",
        payload={
            "need_id": str(need.id),
            "fields": [item.as_dict() for item in result.fields],
            "missing": result.missing,
            "warnings": result.warnings,
        },
    )
    await db.commit()
    await db.refresh(draft)
    return draft


@router.post("/needs/{need_id}/offers", response_model=OfferOut, status_code=status.HTTP_201_CREATED)
async def create_offer(
    need_id: uuid.UUID,
    data: OfferIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    need = await db.scalar(select(Need).where(Need.id == need_id).with_for_update())
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")
    await require_current_evidence(db, need)
    if need.status not in ACTIVE_NEED_STATUSES or not need_is_current(need):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Потребность закрыта или срок её актуальности истёк")
    if need.visibility != "open_anonymized":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Потребность недоступна этой компании")
    if need.company_id == data.company_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Нельзя отправить предложение на потребность своей компании",
        )

    await require_company_seller(data.company_id, user, db)
    await require_verified_company(data.company_id, user, db)
    if data.moq_units > data.available_units:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="MOQ превышает доступный объём")
    if data.valid_until is not None and data.valid_until < date.today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Срок действия предложения не может быть в прошлом",
        )
    existing = await db.execute(
        select(Offer).where(Offer.need_id == need.id, Offer.company_id == data.company_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Компания уже отправила предложение по этой потребности",
        )

    draft: OfferDraft | None = None
    if data.draft_id is not None:
        draft = await db.get(OfferDraft, data.draft_id)
        if draft is None or draft.company_id != data.company_id or draft.need_id != need.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Черновик предложения не найден")
        if draft.status != "draft":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Черновик уже использован")
        if draft.payload.get("need_revision", 1) != need.revision:
            raise HTTPException(409, "Спецификация изменилась. Подготовьте новый черновик")
        source_id = draft.payload.get("product_id")
        if source_id:
            source = await db.get(Product, uuid.UUID(source_id))
            if not source or source.updated_at.isoformat() != draft.payload.get("source_updated_at"):
                raise HTTPException(409, "Товар или остаток изменился. Обновите черновик перед отправкой")

    resource_kind = data.resource_kind
    product_id = data.product_id
    if draft is not None:
        resource_kind = draft.payload.get("resource_kind", "capacity")
        product_id = uuid.UUID(draft.payload["product_id"]) if draft.payload.get("product_id") else None
    if resource_kind == "stock" and product_id is None:
        raise HTTPException(422, "Для складского предложения укажите товар")
    if product_id:
        product = await db.get(Product, product_id)
        if not product or product.company_id != data.company_id:
            raise HTTPException(422, "Товар не принадлежит компании продавца")
        compatible, reason = _matches_need(product, need)
        if not compatible:
            raise HTTPException(409, f"Товар не соответствует потребности: {reason}")
    offer = Offer(
        resource_kind=resource_kind,
        product_id=product_id,
        need_id=need.id,
        company_id=data.company_id,
        created_by_user_id=user.id,
        commercial_terms=data.commercial_terms.model_dump() if data.commercial_terms else None,
        price_rub=data.price_rub,
        available_units=data.available_units,
        lead_time_days=data.lead_time_days,
        delivery_cost_rub=data.delivery_cost_rub,
        moq_units=data.moq_units,
        price_tiers=[item.model_dump() for item in data.price_tiers],
        valid_until=data.valid_until,
    )
    if data.commercial_terms and data.commercial_terms.delivery_method in {"included","self_pickup"} and offer.delivery_cost_rub is None:
        offer.delivery_cost_rub = decimal(0)
    db.add(offer)
    await db.flush()
    offer.commercial_quote = await offer_quote(db,offer,need)
    if draft is not None:
        # Фиксируем, что человек исправил перед отправкой: это метрика работы агента.
        draft.status = "used"
        draft.used_offer_id = offer.id
        draft.used_at = datetime.now(timezone.utc)
        draft.changed_fields = changed_fields(
            draft.payload or {},
            {
                "price_rub": offer.price_rub,
                "available_units": offer.available_units,
                "lead_time_days": offer.lead_time_days,
                "delivery_cost_rub": offer.delivery_cost_rub,
                "moq_units": offer.moq_units,
            },
        )
        await append_audit_event(
            db,
            event_type="offer_draft_used",
            entity_type="offer_draft",
            entity_id=draft.id,
            actor_user_id=user.id,
            actor_company_id=data.company_id,
            source_refs=[
                {"type": "need", "id": str(need.id)},
                {"type": "offer", "id": str(offer.id)},
            ],
            explanation="Продавец подтвердил черновик агента и отправил предложение.",
            payload={"changed_fields": draft.changed_fields},
        )
    await record_human_approval(db,action='seller_quote_sent',entity_type='offer',entity_id=offer.id,
        actor_user_id=user.id,actor_company_id=data.company_id,permission='company_admin+seller+verified',decision='approved',
        payload={'revision':offer.revision,'commercial_quote':offer.commercial_quote},
        explanation='Уполномоченный продавец направил конкретную версию КП; предварительная неполная смета не разрешает согласование')
    await run_market_rematch(db, "offer_created", offer.id, {"need_id": str(need.id)})
    if need.created_by_user_id:
        await notify(db, need.created_by_user_id, "По вашей потребности поступило новое предложение", "offer_received")
    await db.commit()
    await db.refresh(offer)
    return offer


@router.patch("/offers/{offer_id}", response_model=OfferOut)
async def update_offer(
    offer_id: uuid.UUID,
    data: OfferPatch,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    offer = await db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Предложение не найдено")
    await require_company_seller(offer.company_id, user, db)
    await require_company_admin(offer.company_id, user, db)
    need = await db.scalar(select(Need).where(Need.id == offer.need_id).with_for_update())
    await db.refresh(offer, with_for_update=True)
    if offer.revision != data.expected_revision:
        raise HTTPException(409, "Предложение изменилось. Обновите условия перед подтверждением")
    if offer.status != "sent":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Можно изменить только действующее предложение")
    previous_quote = offer.commercial_quote
    patch = data.model_dump(exclude_unset=True, exclude={"expected_revision"})
    if any(value is None for key, value in patch.items() if key not in {"valid_until","delivery_cost_rub","commercial_terms"}):
        raise HTTPException(422, "Обязательное условие предложения не может быть пустым")
    try:
        merged = {key: getattr(offer, key) for key in ("company_id", "price_rub", "available_units", "lead_time_days", "delivery_cost_rub", "moq_units", "price_tiers", "valid_until", "resource_kind", "product_id", "commercial_terms")}
        OfferIn.model_validate({**merged, **patch})
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(error["msg"] for error in exc.errors())) from exc
    for field, value in patch.items():
        setattr(offer, field, value)
    if offer.resource_kind == "stock" and not offer.product_id:
        raise HTTPException(422, "Для складского предложения укажите товар")
    if offer.product_id:
        product = await db.get(Product, offer.product_id)
        if not product or product.company_id != offer.company_id:
            raise HTTPException(422, "Товар не принадлежит компании продавца")
        compatible, reason = _matches_need(product, need)
        if not compatible:
            raise HTTPException(409, f"Товар не соответствует потребности: {reason}")
    if offer.commercial_terms and offer.commercial_terms["delivery_method"] in {"included","self_pickup"} and offer.delivery_cost_rub is None:
        offer.delivery_cost_rub = decimal(0)
    offer.revision += 1
    if offer.moq_units > offer.available_units:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="MOQ превышает доступный объём")
    if offer.valid_until is not None and offer.valid_until < date.today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Срок действия предложения не может быть в прошлом",
        )
    offer.commercial_quote = await offer_quote(db,offer,need)
    await record_human_approval(db, action="seller_quote_changed", entity_type="offer", entity_id=offer.id,
        actor_user_id=user.id, actor_company_id=offer.company_id, permission="company_admin+seller", decision="approved",
        payload={'revision':offer.revision,'changed_fields':sorted(patch),
                 'previous_quote':previous_quote,'commercial_quote':offer.commercial_quote},
        source_refs=[{'type':'need','id':str(need.id),'revision':need.revision}],
        explanation="Продавец подтвердил новую версию условий КП; прежние согласованные сделки сохраняют свою смету.")
    await run_market_rematch(db, "offer_terms_changed", offer.id, {"need_id": str(offer.need_id)})
    await db.commit()
    await db.refresh(offer)
    return offer


@router.post("/offers/{offer_id}/select", response_model=DealOut, status_code=status.HTTP_201_CREATED)
async def select_offer(
    offer_id: uuid.UUID,
    data: OfferSelectIn | None = Body(default=None),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    offer = await db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Предложение не найдено")

    need = (
        await db.execute(select(Need).where(Need.id == offer.need_id).with_for_update())
    ).scalar_one_or_none()
    if need is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Потребность не найдена")

    await require_company_buyer(need.company_id, user, db)
    await require_company_admin(need.company_id, user, db)
    await require_verified_company(need.company_id, user, db)
    await db.refresh(offer, with_for_update=True)
    if data is None:
        raise HTTPException(428, "Обновите предложение и подтвердите показанную версию условий")
    if data.expected_revision != offer.revision:
        raise HTTPException(409, "Условия предложения изменились. Обновите их и подтвердите заново")
    existing_deal = await db.scalar(select(Deal).where(Deal.offer_id == offer.id))
    if existing_deal is not None:
        return existing_deal
    await require_current_evidence(db, need)
    if need.status not in ACTIVE_NEED_STATUSES or not need_is_current(need):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Потребность закрыта или срок её актуальности истёк")
    if offer.status != "sent":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Предложение уже обработано")
    seller_company = await get_company(db, offer.company_id)
    if seller_company is None or seller_company["verification_status"] != "verified":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Компания продавца больше не допущена к сделкам",
        )
    if offer.available_units < need.volume_units:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Предложение не покрывает требуемый объём",
        )
    if offer.moq_units > need.volume_units:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Объём потребности не достигает MOQ предложения",
        )
    product = None
    if offer.product_id:
        product = await db.get(Product, offer.product_id)
        if not product or product.company_id != offer.company_id:
            raise HTTPException(409, "Товар предложения больше не доступен продавцу")
        compatible, reason = _matches_need(product, need)
        if not compatible:
            raise HTTPException(409, f"Товар предложения изменился: {reason}. Запросите новое КП")
    if offer.valid_until is not None and offer.valid_until < date.today():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Срок действия предложения истёк")
    if offer.lead_time_days > max(0, (need.deadline_date - date.today()).days):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Предложение не соблюдает срок потребности")
    quote = offer.commercial_quote
    require_complete(quote.get('estimate') if quote else None)
    if quote['need']['revision'] != need.revision:
        raise HTTPException(409,'Спецификация изменилась после подтверждения КП. Запросите новую смету')
    total_price = decimal(quote['estimate']['total_rub'])
    if need.budget_rub is not None and total_price > need.budget_rub:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Стоимость предложения превышает бюджет потребности",
        )
    # Момент обязательства: документы продавца должны подтверждать спецификацию
    # потребности. Проверка выполняется заново, а не берётся из прошлого решения.
    admission = await require_company_admission(
        db,
        offer.company_id,
        SpecificationCheck(
            category=need.category,
            subcategory=need.subcategory,
            characteristics=product.characteristics if offer.product_id else need.characteristics,
            moq_units=offer.moq_units,
            label="спецификация потребности",
            product_id=offer.product_id,
            volume_units=need.volume_units,
            category_profile=need.category_profile,
        ),
        context="Сделка не создана",
    )

    deal = Deal(
        offer_id=offer.id,
        need_id=need.id,
        buyer_company_id=need.company_id,
        seller_company_id=offer.company_id,
        performed_by_user_id=user.id,
        commercial_snapshot=quote,
        units=need.volume_units,
        total_price_rub=total_price,
        unit_price_rub=offer_unit_price(offer, need.volume_units),
        delivery_price_rub=offer.delivery_cost_rub,
        status="created",
    )
    offer.status = "selected"
    others = await db.execute(select(Offer).where(Offer.need_id == need.id, Offer.id != offer.id))
    for other in others.scalars():
        other.status = "rejected"
    need.status = "matched"
    need.no_match_reason = None

    db.add(deal)
    await db.flush()
    await reserve(db, company_id=offer.company_id, anchor_type="deal", anchor_id=deal.id,
                  units=need.volume_units, deadline=need.deadline_date,
                  resource_kind=offer.resource_kind, product_id=offer.product_id,
                  category=need.category, subcategory=need.subcategory, unit=order_unit(need.characteristics))
    approval_payload = {
        "offer_id": str(offer.id),
        "offer_revision": offer.revision,
        "need_revision": need.revision,
        "need_id": str(need.id),
        "seller_company_id": str(offer.company_id),
        "product_category_profile": product.category_profile if product is not None else None,
        "units": need.volume_units,
        "total_price_rub": total_price,
        "admission": admission_audit_payload(
            admission,
            specification={
                "category": need.category, "subcategory": need.subcategory,
                "characteristics": need.characteristics,
                "category_profile": need.category_profile,
                "moq_units": offer.moq_units,
            },
        ),
    }
    await record_human_approval(
        db,
        action="select_offer_and_create_deal",
        entity_type="deal",
        entity_id=deal.id,
        actor_user_id=user.id,
        actor_company_id=need.company_id,
        permission="company_admin+buyer+verified",
        decision="approved",
        payload=approval_payload,
        source_refs=[{"type": "need", "id": str(need.id)}, {"type": "offer", "id": str(offer.id)}],
        explanation="Администратор проверенной компании-покупателя явно выбрал предложение после программной проверки цены, объёма, MOQ и срока.",
    )
    await append_audit_event(
        db,
        event_type="deal_created",
        entity_type="deal",
        entity_id=deal.id,
        actor_user_id=user.id,
        actor_company_id=need.company_id,
        source_refs=[{"type": "need", "id": str(need.id)}, {"type": "offer", "id": str(offer.id)}],
        explanation="Сделка создана из выбранного действующего предложения после Human Approval.",
        payload={**approval_payload, "gmv_rub": total_price},
    )
    await run_market_rematch(db, "offer_selected", offer.id, {"need_id": str(need.id)})
    if offer.created_by_user_id:
        await notify(db, offer.created_by_user_id, "Ваше предложение выбрано покупателем", "offer_selected")
    await db.commit()
    await db.refresh(deal)
    return deal

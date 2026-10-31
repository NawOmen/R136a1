import hashlib
import json
import re
from .money import decimal
from decimal import Decimal
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    CapabilityPassport,
    CapacityEntry,
    Coalition,
    CoalitionMember,
    CompatibilityProfile,
    GroupOffer,
    MarketOpportunity,
    MatchEvent,
    Need,
    Offer,
    Product,
)
from .resources import occupies, reservations
from .category_registry import resolve_category

COMMON_KEYS = {
    "volume_ml",
    "body_material",
    "material",
    "inner_coating",
    "coating",
    "top_diameter_mm",
    "bottom_diameter_mm",
}
INDIVIDUAL_KEYS = {"print", "logo", "packaging"}
HARD_KEYS = {"food_contact", "tr_ts_005_2011", "mandatory_requirements"}
FLEXIBLE_KEYS = {"allowed_analogues", "volume_tolerance", "deadline_tolerance_days"}
ACTIVE_NEED_STATUSES = {
    "open_for_offers",
    "waiting_for_match",
    "coalition_candidate",
    "awaiting_approvals",
}


def need_is_current(need: Need, today: date | None = None) -> bool:
    """Срок поставки и актуальности включают указанный день."""
    today = today or date.today()
    return need.deadline_date >= today and (need.valid_until is None or need.valid_until >= today)


def order_unit(characteristics: dict | None) -> str:
    from .category_units import order_unit as canonical_order_unit
    return canonical_order_unit(characteristics)


def offer_unit_price(offer: Offer, volume_units: int) -> float:
    price = decimal(offer.price_rub)
    tiers = sorted(
        (
            item
            for item in (offer.price_tiers or [])
            if isinstance(item, dict)
            and isinstance(item.get("min_units"), int)
            and isinstance(item.get("unit_price_rub"), (int, float, str, Decimal))
        ),
        key=lambda item: item["min_units"],
    )
    for tier in tiers:
        if volume_units >= tier["min_units"]:
            price = decimal(tier["unit_price_rub"])
    return price


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _need_parts(need: Need) -> tuple[dict, dict, dict, dict]:
    characteristics = need.characteristics or {}
    from .category_compatibility import canonical_characteristics
    normalized = canonical_characteristics(characteristics, (getattr(need,'category_profile',None) or {}).get('fields'))
    characteristics = {key: (format(values[0].normalize(),'f') if hasattr(values[0], 'as_tuple') else values[0]) for key, values in normalized.items()}
    common = {key: order_unit(characteristics) if key == "unit" else characteristics[key] for key in sorted(characteristics)
              if key not in INDIVIDUAL_KEYS | HARD_KEYS | FLEXIBLE_KEYS}
    common.setdefault("unit", "шт")
    hard = {key: characteristics[key] for key in sorted(HARD_KEYS) if key in characteristics}
    profile = getattr(need,"category_profile",None)
    if profile: hard["category_profile_version"] = {"category_id":profile["category_id"],"version":profile["profile_version"]}
    flexible = {key: characteristics[key] for key in sorted(FLEXIBLE_KEYS) if key in characteristics}
    individual = {
        key: characteristics[key]
        for key in sorted(characteristics)
        if key in INDIVIDUAL_KEYS
    }
    return common, hard, flexible, individual


def additional_matching_keys(need: Need) -> list[str]:
    """Explain custom constraints without silently weakening their matching."""
    from .category_characteristics import characteristic_profile
    fields = (getattr(need, "category_profile", None) or {}).get("fields")
    if fields is None:
        profile = characteristic_profile(need.category, need.subcategory)
        if profile is None:
            return []
        fields = profile["fields"]
    common, hard, _, _ = _need_parts(need)
    # Discovery checks common + hard; only INDIVIDUAL_KEYS are excluded there.
    # Flexible tolerances are evaluated separately and are not passport fields.
    return sorted((set(common) | set(hard)) - set(fields) - {"unit", "category_profile_version"})


def need_matching_warnings(need: Need) -> list[str]:
    if not additional_matching_keys(need):
        return []
    return ["Дополнительные характеристики вне профиля категории обязательны при подборе. "
            "Если паспорт производителя их не подтверждает, он не увидит запрос. "
            "Проверьте характеристики и удалите ненужные через изменение требований."]


def _tokens(value: str) -> set[str]:
    return {item for item in re.findall(r"[а-яёa-z0-9]+", value.lower()) if len(item) > 2}


def _passport_matches(passport: CapabilityPassport, category: str, common: dict, subcategory=None, volume_units=None, *, category_profile=None) -> bool:
    # Scoped declarations are authoritative for discovery; free text is only a legacy hint.
    from .category_compatibility import canonical_characteristics
    from .category_registry import registry_snapshot, normalize_label
    scopes = (getattr(passport, 'details', None) or {}).get('category_scopes', [])
    if scopes:
        registry = registry_snapshot()
        from .category_registry import resolve_category
        resolved=resolve_category(category,subcategory)
        from .category_profile_snapshot import profile_matches_leaf
        if not profile_matches_leaf(category_profile, resolved) or not profile_matches_leaf(
            common.get('category_profile_version'), resolved, version_key='version'
        ):
            return False
        leaves=[resolved] if resolved else []
        for scope in scopes:
            leaf = next((leaf for leaf in leaves if leaf['id'] == scope['category_id']), None)
            if leaf is None or scope.get('profile_version') != leaf['technical_profile']['version']: continue
            if order_unit(common) != scope['unit']: continue
            if volume_units is not None and (volume_units < scope.get('min_units',1) or (scope.get('max_units') is not None and volume_units > scope['max_units'])): continue
            requested = canonical_characteristics(common)
            allowed = scope.get('characteristics', {})
            from .category_compatibility import canonical_key, canonical_value
            from .category_compatibility import equal_value
            admitted = {canonical_key(key):[canonical_value(canonical_key(key),option) for option in options] for key,options in allowed.items()}
            requested = {key:values for key,values in requested.items() if key not in {'unit','category_profile_version'} | INDIVIDUAL_KEYS}
            if all(key in admitted and all(any(equal_value(value,option) for option in admitted[key]) for value in values) for key,values in requested.items()): return True
        return False
    return False  # Legacy text remains descriptive, never confirmed category capability.



def passport_scope_limits(passport,category,characteristics,subcategory=None):
    from types import SimpleNamespace
    scopes=(getattr(passport,'details',None) or {}).get('category_scopes',[])
    matching=[scope for scope in scopes if _passport_matches(SimpleNamespace(details={'category_scopes':[scope]}),category,characteristics,subcategory)]
    if not matching:return None,None
    minimum=min(scope.get('min_units',1) for scope in matching)
    maximum=None if any(scope.get('max_units') is None for scope in matching) else max(scope['max_units'] for scope in matching)
    return minimum,maximum


async def _active_needs(db: AsyncSession) -> list[Need]:
    today = date.today()
    needs = (
        await db.execute(
            select(Need)
            .where(Need.status.in_(ACTIVE_NEED_STATUSES), Need.visibility == "open_anonymized")
            .order_by(Need.created_at.desc())
        )
    ).scalars().all()
    result = []
    seen = set()
    for need in needs:
        if not need_is_current(need, today):
            need.status = "expired"
            need.no_match_reason = "Срок актуальности карточки истёк"
            continue
        signature = (
            need.company_id,
            need.category.strip().lower(), (need.subcategory or "").strip().lower(),
            _canonical_json(need.characteristics or {}),
            need.volume_units, need.deadline_date, need.valid_until, need.delivery_address_id,
            need.budget_rub, need.visibility,
        )
        if signature in seen:
            continue
        seen.add(signature)
        result.append(need)
    return result


def _reason_text(message: str) -> str:
    # Need.no_match_reason is VARCHAR(500); long document checklists must not
    # abort the rematch transaction or hide its useful leading explanation.
    return message if len(message) <= 500 else message[:499] + "…"


async def _has_direct_match(db: AsyncSession, need: Need) -> tuple[bool, str]:
    offers = (
        await db.execute(
            select(Offer).where(Offer.need_id == need.id, Offer.status.in_(["sent", "stale"]))
        )
    ).scalars().all()
    days_left = max(0, (need.deadline_date - date.today()).days)
    reasons: list[str] = []
    for offer in offers:
        if offer.status == "stale":
            reasons.append("Спецификация изменилась: продавец должен обновить условия КП")
            continue
        rejected: list[str] = []
        quote = offer.commercial_quote
        if not quote or not quote.get('estimate', {}).get('complete'):
            rejected.append("Не подтверждена полная смета, доставка или налоговая база КП")
        elif quote['need']['revision'] != need.revision:
            rejected.append("Спецификация изменилась: продавец должен обновить условия КП")
        from .admission import company_admission
        product = await db.get(Product, offer.product_id) if offer.product_id else None
        if offer.product_id and (product is None or product.company_id != offer.company_id):
            rejected.append("Товар предложения недоступен продавцу")
        company = (await db.execute(text("SELECT verification_status FROM auth.companies WHERE id=:id"),
                                    {"id": offer.company_id})).scalar_one_or_none()
        if company != "verified":
            rejected.append("Компания продавца не прошла проверку")
        admission = await company_admission(db, offer.company_id,
            product.category if product else need.category,
            product.subcategory if product else need.subcategory,
            characteristics=product.characteristics if product else need.characteristics,
            moq_units=offer.moq_units)
        if admission.blocking_open:
            rejected.append("Допуск продавца не подтверждён: " + admission.blocking_message)
        if offer.moq_units > need.volume_units:
            rejected.append("Объём потребности меньше минимальной партии продавца")
        if need.volume_units > offer.available_units:
            rejected.append("Доступный объём предложения меньше потребности")
        if offer.lead_time_days > days_left:
            rejected.append("Срок поставки не укладывается в срок потребности")
        if offer.valid_until is not None and offer.valid_until < date.today():
            rejected.append("Срок действия КП истёк")
        if quote and quote.get('estimate', {}).get('complete') and need.budget_rub is not None:
            if decimal(quote['estimate']['total_rub']) > need.budget_rub:
                rejected.append("Полная стоимость КП превышает бюджет потребности")
        if not rejected:
            return True, ""
        reasons.extend(rejected)
    if offers:
        return False, _reason_text("; ".join(dict.fromkeys(reasons)))
    passports = (
        await db.execute(select(CapabilityPassport))
    ).scalars().all()
    moqs=[]
    for item in passports:
        minimum,_=passport_scope_limits(item,need.category,{**_need_parts(need)[0],**_need_parts(need)[1]},need.subcategory)
        if minimum is not None:moqs.append(minimum)
    if moqs and min(moqs) > need.volume_units:
        return False, f"Не достигнут минимальный объём производителя (MOQ {min(moqs):,} {order_unit(need.characteristics)})".replace(",", " ")
    return False, "Пока нет выполнимого предложения от подходящего производителя"


async def _build_coalitions(db: AsyncSession, needs: list[Need]) -> None:
    groups: dict[tuple[str, str, str, str], list[Need]] = defaultdict(list)
    for need in needs:
        common, hard, _, _ = _need_parts(need)
        leaf = resolve_category(need.category, need.subcategory)
        if leaf is None:
            continue
        groups[(leaf['parent_id'], leaf['id'], _canonical_json(common), _canonical_json(hard))].append(need)

    passports = (await db.execute(select(CapabilityPassport))).scalars().all()
    for (_, subtype, common_json, hard_json), members in groups.items():
        distinct_companies = {item.company_id for item in members}
        if len(members) < 2 or len(distinct_companies) < 2:
            # S08.01: прямой путь с объяснением — коалиции нет, но подбор идёт.
            for item in members:
                if item.status == "waiting_for_match" and item.no_match_reason \
                        and "прямой подбор" not in item.no_match_reason:
                    item.no_match_reason = _reason_text(item.no_match_reason + (
                        "; совместимых запросов других компаний пока нет — доступен прямой подбор "
                        "предложения, коалиция соберётся при появлении спроса"
                    ))
            continue
        members = sorted(members, key=lambda item: str(item.id))
        # S08.01: у группы должно быть согласуемое окно сроков — производство
        # обязано завершиться до самого раннего дедлайна участника.
        latest_start = date.today()
        earliest_deadline = min(item.deadline_date for item in members)
        if earliest_deadline < latest_start:
            continue
        total_units = sum(item.volume_units for item in members)
        compatible_passports = [
            item
            for item in passports
            if _passport_matches(item, members[0].category, {**json.loads(common_json),**json.loads(hard_json)},members[0].subcategory,total_units)
            and item.company_id not in distinct_companies
        ]
        if not compatible_passports:
            continue
        compatible_passports.sort(key=lambda item: (passport_scope_limits(item,members[0].category,{**json.loads(common_json),**json.loads(hard_json)},members[0].subcategory)[0] or 0,str(item.company_id)))
        passport = compatible_passports[0]
        target_moq,_=passport_scope_limits(passport,members[0].category,{**json.loads(common_json),**json.loads(hard_json)},members[0].subcategory)
        identity = {
            "need_ids": [str(item.id) for item in members],
            "need_revisions": {str(item.id): item.revision for item in members},
            "producer_company_id": str(passport.company_id),
            "common": json.loads(common_json),
            "hard": json.loads(hard_json),
        }
        if subtype:
            identity["subcategory"] = subtype
        digest = hashlib.sha256(_canonical_json(identity).encode()).hexdigest()
        profile = (
            await db.execute(select(CompatibilityProfile).where(CompatibilityProfile.input_hash == digest))
        ).scalar_one_or_none()
        if profile is None:
            individual_parts = {
                str(item.id): _need_parts(item)[3]
                for item in members
            }
            flexible = {
                str(item.id): _need_parts(item)[2]
                for item in members
            }
            profile = CompatibilityProfile(
                category=members[0].category,
                common_base=json.loads(common_json),
                hard_constraints=json.loads(hard_json),
                flexible_parameters=flexible,
                individual_parts=individual_parts,
                input_hash=digest,
            )
            db.add(profile)
            await db.flush()
        existing = (
            await db.execute(
                select(Coalition).where(
                    Coalition.compatibility_profile_id == profile.id,
                    Coalition.status.not_in(("cancelled", "expired")),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            coalition = Coalition(
                compatibility_profile_id=profile.id,
                producer_company_id=passport.company_id,
                category=members[0].category,
                combined_volume_units=total_units,
                target_moq_units=target_moq,
                status="candidate",
                explanation=[
                    "Общая производственная основа и жёсткие ограничения совпадают",
                    f"Общий объём {total_units:,} {order_unit(members[0].characteristics)} достигает MOQ {target_moq or 0:,} {order_unit(members[0].characteristics)}".replace(",", " "),
                    f"Согласуемое окно: производство до {earliest_deadline.strftime("%d.%m.%y")} (ранний дедлайн участников)",
                    "Индивидуальная печать, упаковка и логистика будут рассчитаны отдельно",
                ],
            )
            db.add(coalition)
            await db.flush()
            for need in members:
                db.add(
                    CoalitionMember(
                        coalition_id=coalition.id,
                        need_id=need.id,
                        buyer_company_id=need.company_id,
                        units=need.volume_units,
                        individual_operations=_need_parts(need)[3],
                    )
                )
                need.status = "coalition_candidate"
                need.no_match_reason = None


async def _rebuild_opportunities(db: AsyncSession, needs: list[Need]) -> None:
    passports = (await db.execute(select(CapabilityPassport))).scalars().all()
    companies = (
        await db.execute(
            text("SELECT id FROM auth.companies WHERE country = 'RU' AND verification_status = 'verified'")
        )
    ).scalars().all()
    verified = set(companies)
    grouped: dict[tuple[str, str], list[Need]] = defaultdict(list)
    for need in needs:
        unit = order_unit(need.characteristics)
        grouped[((need.subcategory or need.category).strip().lower(), unit)].append(need)

    active_keys = set()
    for passport in passports:
        if passport.company_id not in verified:
            continue
        for (_, unit), category_needs in grouped.items():
            category = category_needs[0].subcategory or category_needs[0].category
            category_needs = [item for item in category_needs if _passport_matches(passport,item.category,{**_need_parts(item)[0],**_need_parts(item)[1]},item.subcategory)]
            if not category_needs:
                continue
            total_demand = sum(item.volume_units for item in category_needs)
            buyer_count = len({item.company_id for item in category_needs})
            offers = (
                await db.execute(
                    select(Offer).join(Need, Offer.need_id == Need.id).where(
                        Need.id.in_([item.id for item in category_needs]),
                        Offer.status == "sent",
                        (Offer.valid_until.is_(None) | (Offer.valid_until >= date.today())),
                    )
                )
            ).scalars().all()
            # Count only the actual members of a current, feasible group proposal.
            # A proposal's upper capacity is not delivered demand for unrelated buyers.
            covered_ids = set((await db.scalars(
                select(CoalitionMember.need_id)
                .join(Coalition, Coalition.id == CoalitionMember.coalition_id)
                .join(GroupOffer, GroupOffer.coalition_id == Coalition.id)
                .where(CoalitionMember.need_id.in_([item.id for item in category_needs]),
                       Coalition.status == "awaiting_approvals", GroupOffer.status == "preliminary",
                       GroupOffer.fill_deadline >= date.today(),
                       GroupOffer.min_total_units <= Coalition.combined_volume_units,
                       GroupOffer.max_total_units >= Coalition.combined_volume_units)
            )).all())
            supplied = sum(item.volume_units for item in category_needs if item.id in covered_ids)
            unmet = max(0, total_demand - supplied)
            active_keys.add((passport.company_id, category, unit))
            opportunity = (
                await db.execute(
                    select(MarketOpportunity).where(
                        MarketOpportunity.company_id == passport.company_id,
                        MarketOpportunity.category == category,
                        MarketOpportunity.unit == unit,
                    )
                )
            ).scalar_one_or_none()
            if opportunity is None:
                opportunity = MarketOpportunity(company_id=passport.company_id, category=category, unit=unit, score=0,
                    competition_level="нет", saturation_risk="низкий", unmet_volume_units=0,
                    buyers_count=0, need_ids=[], reasons=[], missing_data=[])
                db.add(opportunity)
            elif (opportunity.status == "dismissed"
                    and set(opportunity.need_ids or []) == {str(item.id) for item in category_needs}):
                # Отклонение действует, пока состав спроса не изменился.
                continue
            if unmet == 0:
                opportunity.status = "saturated"
                opportunity.score = 0
                opportunity.unmet_volume_units = 0
                opportunity.reasons = ["Действующее предложение уже покрывает подтверждённый спрос"]
                continue
            supply_ratio = min(1, supplied / total_demand) if total_demand else 1
            volume_factor = min(1, unmet / 50_000)
            share_factor = unmet / total_demand
            capacity_entries = (await db.scalars(select(CapacityEntry).where(
                CapacityEntry.company_id == passport.company_id,
                CapacityEntry.date >= date.today(),
                CapacityEntry.date <= max(item.deadline_date for item in category_needs),
            ))).all()
            held = await reservations(db, passport.company_id) if capacity_entries else []
            from .resource_scopes import conversion_for, occupied_units
            recorded_capacity = None
            for entry in capacity_entries:
                sample = category_needs[0]
                conversion = conversion_for(entry,sample.category,sample.subcategory,unit)
                if conversion is None: continue
                if recorded_capacity is None:recorded_capacity=0
                free = max(0,entry.available_units-sum(occupied_units(row) for row in held if row.capacity_entry_id==entry.id and occupies(row)))
                recorded_capacity += free // conversion['resource_units_per_order_unit']
            scope_min,scope_max=passport_scope_limits(passport,category_needs[0].category,{**_need_parts(category_needs[0])[0],**_need_parts(category_needs[0])[1]},category_needs[0].subcategory)
            capacity_limit = (
                recorded_capacity
                if recorded_capacity is not None
                else scope_max
            )
            capacity_ok = (
                (scope_min is None or total_demand >= scope_min)
                and (capacity_limit is None or total_demand <= capacity_limit)
            )
            logistics_factor = 1 if passport.delivery_regions else 0.5
            factors = {
                "confirmed_unmet_volume": volume_factor,
                "share_without_feasible_offer": share_factor,
                "passport_match": 1,
                "moq_and_capacity": 0.5 if recorded_capacity is None and capacity_ok else 1 if capacity_ok else 0.3,
                "logistics": logistics_factor,
                "competition_and_saturation": 1 - supply_ratio,
                "data_quality": 1,
            }
            weights = {
                "confirmed_unmet_volume": 0.25,
                "share_without_feasible_offer": 0.20,
                "passport_match": 0.20,
                "moq_and_capacity": 0.15,
                "logistics": 0.10,
                "competition_and_saturation": 0.05,
                "data_quality": 0.05,
            }
            opportunity.score = round(100 * sum(factors[key] * weights[key] for key in weights))
            opportunity.competition_level = "нет" if not offers else ("низкая" if len(offers) <= 2 else "высокая")
            opportunity.saturation_risk = "низкий" if supply_ratio < 0.5 else "средний"
            opportunity.unmet_volume_units = unmet
            opportunity.buyers_count = buyer_count
            opportunity.need_ids = [str(item.id) for item in category_needs]
            opportunity.reasons = [
                "Есть подтверждённый незакрытый спрос",
                "Паспорт возможностей соответствует категории и материалам",
                "Расчёт не является гарантией продаж или прибыли",
            ]
            opportunity.missing_data = ["Себестоимость и целевая маржа производителя"]
            if recorded_capacity is None:opportunity.missing_data.append("Нет подтверждённого календаря мощности этой категории и единицы")
            opportunity.status = "active"

    existing = (await db.execute(select(MarketOpportunity))).scalars().all()
    for opportunity in existing:
        if (opportunity.company_id, opportunity.category, opportunity.unit) not in active_keys:
            opportunity.status = "inactive"


async def run_market_rematch(
    db: AsyncSession,
    event_type: str,
    entity_id: uuid.UUID | None,
    payload: dict | None = None,
    *, event: MatchEvent | None = None,
) -> None:
    event = event or MatchEvent(
        event_type=event_type,
        entity_id=entity_id,
        payload=payload or {},
        status="processing",
    )
    db.add(event)
    await db.flush()
    needs = await _active_needs(db)
    unmatched_needs = []
    for need in needs:
        matched, reason = await _has_direct_match(db, need)
        if matched:
            need.status = "open_for_offers"
            need.no_match_reason = None
        elif need.status not in {"awaiting_approvals", "matched"}:
            need.status = "waiting_for_match"
            need.no_match_reason = reason
            unmatched_needs.append(need)
        elif need.status == "awaiting_approvals":
            unmatched_needs.append(need)
    await _build_coalitions(db, unmatched_needs)
    await _rebuild_opportunities(db, unmatched_needs)
    event.status = "processed"
    event.payload = {**event.payload, "processed_at": datetime.now(timezone.utc).isoformat()}

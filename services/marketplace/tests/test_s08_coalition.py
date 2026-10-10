"""S08: коалиции покупателей и изменение подтверждённой группы.

S08.01 — согласуемое окно сроков, прямой путь с объяснением, объёмы заявлено/подтверждено.
S08.02 — кратность партии на публикации.
S08.03 — единое обязательство в ledger; согласие по истёкшему запросу не завершает группу.
S08.04 — изменение состава после подтверждения через до-согласование: выход ниже MOQ
аннулирует старые условия, частичное изменение возвращается на публикацию, повтор
идемпотентен, заказы и история сохраняются.
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import (
    Coalition,
    CoalitionChangeRequest,
    CoalitionMember,
    Need,
    ParticipantOrder,
)
from app.money import amount, decimal, money_values
from app.resources import reservations
from conftest import (
    confirmed_quote_terms,
    grant_capacity,
    grant_packaging_documents,
    make_company,
    make_token,
    make_user,
)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def passport(client, token, company_id, *, moq=50_000):
    response = await client.put(
        f"/api/v1/companies/{company_id}/capability-passport",
        json={
            "details": {"category_scopes": [{"category_id": "packaging.paper-cups", "unit": "шт",
                                             "min_units": moq, "max_units": 60000,
                                             "characteristics": {"material": ["крафт-картон"], "coating": ["PE"],
                                                                 "volume_ml": [400], "food_contact": [True]}}]},
            "technologies": ["производство бумажных стаканов"],
            "equipment": ["линия формовки"],
            "materials": ["крафт-картон", "PE"],
            "size_ranges": {"volume_ml": [350, 450]},
            "certifications": ["ТР ТС 005/2011"],
            "min_order_units": moq,
            "max_order_units": 60_000,
            "delivery_regions": ["Москва", "Казань"],
            "completed_order_types": ["бумажные стаканы"],
        },
        headers=auth(token),
    )
    assert response.status_code == 200


async def create_published_need(client, db_session, volume, print_value):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=True, can_sell=False)
    token = make_token(user)
    created = await client.post(
        "/api/v1/needs",
        json={
            "company_id": str(company),
            "category": "бумажные стаканы",
            "characteristics": {
                "volume_ml": 400,
                "body_material": "крафт-картон",
                "inner_coating": "PE",
                "food_contact": True,
                "print": print_value,
            },
            "volume_units": volume,
            "budget_rub": 90_000 if volume == 5_000 else 620_000,
            "deadline_date": str(date.today() + timedelta(days=30)),
            "valid_until": str(date.today() + timedelta(days=20)),
            "visibility": "open_anonymized",
        },
        headers=auth(token),
    )
    published = await client.post(f"/api/v1/needs/{created.json()['id']}/publish", headers=auth(token))
    assert published.status_code == 200
    return user, company, token, published.json()


def fake_evaluate(total_units):
    async def evaluate(payload):
        payload = money_values(payload)
        members = []
        for item in payload["members"]:
            common = amount(item["volume_units"] * decimal("10.9"))
            total = round(common + item["individual_operations_cost_rub"] + item["delivery_cost_rub"], 2)
            members.append({
                "need_id": item["need_id"],
                "buyer_company_id": item["buyer_company_id"],
                "units": item["volume_units"],
                "common_production_cost_rub": common,
                "individual_operations_cost_rub": item["individual_operations_cost_rub"],
                "delivery_cost_rub": item["delivery_cost_rub"],
                "total_cost_rub": total,
                "baseline_cost_rub": item["individual_baseline_cost_rub"],
                "benefit_rub": None if item["individual_baseline_cost_rub"] is None else round(
                    decimal(item["individual_baseline_cost_rub"]) - total, 2),
                "within_budget": True,
                "deadline_met": True,
            })
        return {"compatible": True, "feasible": True, "combined_volume_units": total_units,
                "unit_price_rub": 10.9, "members": members,
                "reasons": ["Все обязательные ограничения соблюдены"], "input_hash": "synthetic-s08"}
    return evaluate


async def publish_group(client, seller_token, draft_id, need_one, need_two, *, production_start,
                        min_total_units=50_000, tier_min_units=50_000):
    published = await client.post(
        f"/api/v1/group-offers/{draft_id}/publish",
        json={
            "min_total_units": min_total_units,
            "max_total_units": 60_000,
            "available_capacity_units": 60_000,
            "price_tiers": [{"min_units": tier_min_units, "unit_price_rub": 10.9}],
            "production_start": str(production_start),
            "production_end": str(production_start + timedelta(days=5)),
            "fill_deadline": str(production_start - timedelta(days=1)),
            "non_fill_rule": "close_without_obligations",
            "participant_terms": [
                {"commercial_terms": confirmed_quote_terms(), "need_id": need_one["id"],
                 "individual_operations_cost_rub": 8_000, "delivery_cost_rub": 3_000,
                 "individual_baseline_cost_rub": 75_000, "delivery_days": 1},
                {"commercial_terms": confirmed_quote_terms(), "need_id": need_two["id"],
                 "individual_operations_cost_rub": 15_000, "delivery_cost_rub": 12_000,
                 "individual_baseline_cost_rub": 540_000, "delivery_days": 1},
            ],
        },
        headers=auth(seller_token),
    )
    assert published.status_code == 200, published.text
    return published.json()


async def confirmed_via_api(client, db_session, monkeypatch, *, min_total_units=50_000, passport_moq=50_000):
    seller_user = await make_user(db_session)
    seller_company = await make_company(db_session, seller_user, can_buy=False, can_sell=True)
    seller_token = make_token(seller_user)
    await passport(client, seller_token, seller_company, moq=passport_moq)
    await grant_packaging_documents(db_session, seller_company, decision_user_id=seller_user,
                                    confirms={"material": ["крафт-картон"], "coating": ["PE"]})
    _, buyer_one, token_one, need_one = await create_published_need(client, db_session, 5_000, "2+0")
    _, buyer_two, token_two, need_two = await create_published_need(client, db_session, 45_000, "4+0")
    assert need_two["status"] == "coalition_candidate"
    opportunities = await client.get(f"/api/v1/companies/{seller_company}/market-opportunities",
                                     headers=auth(seller_token))
    draft = await client.post(f"/api/v1/opportunities/{opportunities.json()[0]['id']}/prepare-offer",
                              headers=auth(seller_token))
    assert draft.status_code == 201
    monkeypatch.setattr("app.api.market.evaluate_coalition", fake_evaluate(50_000))
    production_start = date.today() + timedelta(days=10)
    await grant_capacity(db_session, seller_company, 60_000, production_start)
    published = await publish_group(client, seller_token, draft.json()["id"], need_one, need_two,
                                    production_start=production_start, min_total_units=min_total_units)
    coalition_id = published["id"]
    revision = published["version"]
    first = await client.post(f"/api/v1/coalitions/{coalition_id}/decision",
                              json={"company_id": str(buyer_one), "decision": "approved",
                                    "expected_revision": revision}, headers=auth(token_one))
    assert first.status_code == 200
    second = await client.post(f"/api/v1/coalitions/{coalition_id}/decision",
                               json={"company_id": str(buyer_two), "decision": "approved",
                                     "expected_revision": revision}, headers=auth(token_two))
    assert second.status_code == 200
    assert second.json()["status"] == "confirmed"
    return {
        "seller": seller_user, "seller_company": seller_company, "seller_token": seller_token,
        "buyer_one": buyer_one, "buyer_two": buyer_two, "token_one": token_one, "token_two": token_two,
        "need_one": need_one, "need_two": need_two, "coalition_id": coalition_id,
        "production_start": production_start,
    }


@pytest.mark.asyncio
async def test_exit_below_moq_annuls_old_terms_and_keeps_history(client, db_session, monkeypatch):
    """Контроль из ТЗ: выход ниже MOQ аннулирует старые условия, заказы сохранены."""
    ctx = await confirmed_via_api(client, db_session, monkeypatch)
    sc = ctx["seller_company"]
    from app.resources import reserve
    rows_before = [row for row in await reservations(db_session, sc)
                   if row.anchor_type == "coalition"]
    assert sum(row.units for row in rows_before if row.status in {"held", "committed"}) == 50_000
    key = uuid.uuid4()
    created = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/change-requests",
                                headers=auth(ctx["token_two"]),
                                json={"company_id": str(ctx["buyer_two"]), "reason": "Склад переполнен",
                                      "proposed_units": {ctx["need_two"]["id"]: 0},
                                      "resource_policy": "release_and_rereserve",
                                      "idempotency_key": str(key)})
    assert created.status_code == 201, created.text
    decided = await client.post(f"/api/v1/coalition-changes/{created.json()['id']}/decision",
                                headers=auth(ctx["seller_token"]),
                                json={"company_id": str(sc), "approved": True, "expected_revision": 2})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "applied_annulled"
    coalition = await db_session.get(Coalition, uuid.UUID(ctx["coalition_id"]))
    assert coalition.status == "recalculation_required"
    assert coalition.combined_volume_units == 5_000
    remaining_members = (await db_session.scalars(
        select(CoalitionMember).where(CoalitionMember.coalition_id == coalition.id))).all()
    assert len(remaining_members) == 1
    orders = (await db_session.scalars(select(ParticipantOrder))).all()
    assert len(orders) == 2
    assert all(order.status == "superseded" for order in orders)
    active = [row for row in await reservations(db_session, sc)
              if row.anchor_type == "coalition" and row.status in {"held", "committed"}]
    assert active == []
    needs = {str(need.id): need for need in
             (await db_session.scalars(select(Need))).all()}
    assert needs[ctx["need_one"]["id"]].status == "waiting_for_match"
    assert needs[ctx["need_two"]["id"]].status == "waiting_for_match"
    assert await db_session.get(Coalition, coalition.id) is not None


@pytest.mark.asyncio
async def test_partial_change_returns_to_reapproval_and_completes(client, db_session, monkeypatch):
    """Частичное изменение 5 000 → 4 000: до-согласование завершается новыми обязательствами."""
    ctx = await confirmed_via_api(client, db_session, monkeypatch, min_total_units=40_000,
                                    passport_moq=40_000)
    sc = ctx["seller_company"]
    key = uuid.uuid4()
    created = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/change-requests",
                                headers=auth(ctx["token_one"]),
                                json={"company_id": str(ctx["buyer_one"]), "reason": "Снижаем до 4 000",
                                      "proposed_units": {ctx["need_one"]["id"]: 4_000},
                                      "resource_policy": "release_and_rereserve",
                                      "idempotency_key": str(key)})
    assert created.status_code == 201, created.text
    decided = await client.post(f"/api/v1/coalition-changes/{created.json()['id']}/decision",
                                headers=auth(ctx["seller_token"]),
                                json={"company_id": str(sc), "approved": True, "expected_revision": 2})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "applied"
    coalition = await db_session.get(Coalition, uuid.UUID(ctx["coalition_id"]))
    assert coalition.status == "recalculation_required"
    assert coalition.combined_volume_units == 49_000
    # Старое удержание закреплено до нового согласия — двойной продажи нет.
    pinned = [row for row in await reservations(db_session, sc)
              if row.anchor_type == "coalition" and row.status in {"held", "committed"}]
    assert sum(row.units for row in pinned) == 50_000
    # Производитель перепубликует: экономика пересчитана штатным путём.
    from app.models import GroupOffer as GroupOfferModel
    draft = GroupOfferModel(coalition_id=uuid.UUID(ctx["coalition_id"]), company_id=sc, status="draft")
    db_session.add(draft)
    await db_session.commit()
    monkeypatch.setattr("app.api.market.evaluate_coalition", fake_evaluate(49_000))
    republished = await publish_group(client, ctx["seller_token"], str(draft.id),
                                      {**ctx["need_one"], "id": ctx["need_one"]["id"]},
                                      ctx["need_two"], production_start=ctx["production_start"],
                                      min_total_units=40_000, tier_min_units=40_000)
    assert republished["status"] == "awaiting_approvals"
    assert republished["combined_volume_units"] == 49_000
    assert republished["confirmed_volume_units"] == 0
    revision = republished["version"]
    for token, buyer in ((ctx["token_one"], ctx["buyer_one"]), (ctx["token_two"], ctx["buyer_two"])):
        answer = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                                   json={"company_id": str(buyer), "decision": "approved",
                                         "expected_revision": revision}, headers=auth(token))
        assert answer.status_code == 200, answer.text
    assert answer.json()["status"] == "confirmed"
    orders = (await db_session.scalars(select(ParticipantOrder).order_by(ParticipantOrder.created_at))).all()
    assert [order.coalition_version for order in orders] == [2, 2, 4, 4]
    assert [order.status for order in orders] == ["superseded", "superseded", "created", "created"]
    current = [row for row in await reservations(db_session, sc)
               if row.anchor_type == "coalition" and row.status in {"held", "committed"}]
    assert sum(row.units for row in current) == 49_000
    report = await client.get(f"/api/v1/companies/{ctx['buyer_one']}/commercial-analytics?role=buyer",
                              headers=auth(ctx["token_one"]))
    assert report.json()["group_orders_count"] == 1


@pytest.mark.asyncio
async def test_change_request_idempotent_and_guarded(client, db_session, monkeypatch):
    ctx = await confirmed_via_api(client, db_session, monkeypatch)
    key = uuid.uuid4()
    payload = {"company_id": str(ctx["buyer_one"]), "reason": "Снижаем до 4 000",
               "proposed_units": {ctx["need_one"]["id"]: 4_000},
               "resource_policy": "release_and_rereserve", "idempotency_key": str(key)}
    first = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/change-requests",
                              headers=auth(ctx["token_one"]), json=payload)
    assert first.status_code == 201, first.text
    repeat = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/change-requests",
                               headers=auth(ctx["token_one"]), json=payload)
    assert repeat.status_code == 201, repeat.text
    assert repeat.json()["id"] == first.json()["id"]
    assert len((await db_session.scalars(select(CoalitionChangeRequest))).all()) == 1
    conflict = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/change-requests",
                                 headers=auth(ctx["token_one"]),
                                 json={**payload, "reason": "Другая причина"})
    assert conflict.status_code == 409
    empty = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/change-requests",
                              headers=auth(ctx["token_one"]),
                              json={**payload, "proposed_units": {},
                                    "idempotency_key": str(uuid.uuid4())})
    assert empty.status_code == 422
    stranger = await make_user(db_session)
    stranger_company = await make_company(db_session, stranger, can_sell=False)
    await db_session.commit()
    forbidden = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/change-requests",
                                  headers=auth(make_token(stranger)),
                                  json={**payload, "company_id": str(stranger_company),
                                        "idempotency_key": str(uuid.uuid4())})
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_completed_decision_is_readable_only_by_party(client, db_session, monkeypatch):
    ctx = await confirmed_via_api(client, db_session, monkeypatch)
    sc = ctx["seller_company"]
    key = uuid.uuid4()
    created = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/change-requests",
                                headers=auth(ctx["token_one"]),
                                json={"company_id": str(ctx["buyer_one"]), "reason": "Снижаем до 4 000",
                                      "proposed_units": {ctx["need_one"]["id"]: 4_000},
                                      "resource_policy": "release_and_rereserve",
                                      "idempotency_key": str(key)})
    decided = await client.post(f"/api/v1/coalition-changes/{created.json()['id']}/decision",
                                headers=auth(ctx["seller_token"]),
                                json={"company_id": str(sc), "approved": False, "expected_revision": 2})
    assert decided.json()["status"] == "rejected"
    stranger = await make_user(db_session)
    stranger_company = await make_company(db_session, stranger, can_sell=False)
    await db_session.commit()
    leaked = await client.post(f"/api/v1/coalition-changes/{created.json()['id']}/decision",
                               headers=auth(make_token(stranger)),
                               json={"company_id": str(stranger_company), "approved": True,
                                     "expected_revision": 999})
    assert leaked.status_code == 403


@pytest.mark.asyncio
async def test_expired_fill_deadline_cannot_complete_group(client, db_session, monkeypatch):
    ctx = await confirmed_via_api(client, db_session, monkeypatch)
    from app.models import GroupOffer as GroupOfferModel
    offer = (await db_session.scalars(select(GroupOfferModel))).one()
    offer.fill_deadline = date.today() - timedelta(days=1)
    coalition = await db_session.get(Coalition, uuid.UUID(ctx["coalition_id"]))
    coalition.status = "awaiting_approvals"
    await db_session.commit()
    orders_before = len((await db_session.scalars(select(ParticipantOrder))).all())
    response = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                                 headers=auth(ctx["token_one"]),
                                 json={"company_id": str(ctx["buyer_one"]), "decision": "approved",
                                       "expected_revision": coalition.version})
    assert response.status_code == 409
    assert len((await db_session.scalars(select(ParticipantOrder))).all()) == orders_before


@pytest.mark.asyncio
async def test_confirmed_volumes_shown_separately(client, db_session, monkeypatch):
    ctx = await confirmed_via_api(client, db_session, monkeypatch)
    response = await client.get("/api/v1/coalitions/mine", headers=auth(ctx["token_one"]))
    assert response.status_code == 200, response.text
    view = next(item for item in response.json() if item["id"] == ctx["coalition_id"])
    assert view["combined_volume_units"] == 50_000
    assert view["confirmed_volume_units"] == 50_000


@pytest.mark.asyncio
async def test_single_need_gets_direct_path_explanation(db_session):
    from app.matching import run_market_rematch
    buyer = await make_user(db_session)
    bc = await make_company(db_session, buyer, can_sell=False)
    need = Need(company_id=bc, created_by_user_id=buyer, category="Упаковка и тара",
                subcategory="Бумажные стаканы", characteristics={"volume_ml": 400},
                volume_units=5_000, budget_rub=90_000, deadline_date=date.today() + timedelta(days=30),
                valid_until=date.today() + timedelta(days=20),
                visibility="open_anonymized", status="waiting_for_match",
                no_match_reason="Пока нет выполнимого предложения от подходящего производителя")
    db_session.add(need)
    await db_session.commit()
    await run_market_rematch(db_session, "test_direct_path", need.id)
    await db_session.commit()
    need = await db_session.get(Need, need.id)
    assert need.status == "waiting_for_match"
    assert "прямой подбор" in (need.no_match_reason or "")

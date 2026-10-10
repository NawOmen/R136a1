"""Этап S07: единая серверная граница, последствия и повторные решения.

Проверяем, что обязательство связано с неизменяемыми условиями, правом
и ресурсом: старое согласие, чужая роль, blocked-аккаунт, отозванное членство
и истёкшее предложение не создают нового обязательства; повтор возвращает
прежнее; участник не подтверждает за остальных.
"""
import asyncio
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text

from app.models import Deal, HumanApprovalRecord, ParticipantOrder
from conftest import (
    confirmed_quote_terms,
    grant_capacity,
    grant_packaging_documents,
    make_company,
    make_token,
    make_user,
)

from test_category_admission import _auth
from test_category_admission import _auth
from test_offer_draft_and_scorecard import _buyer_with_published_need
from test_stage5 import auth, create_published_need, passport


async def _seller_company(db_session, **kwargs):
    from conftest import grant_category_capability

    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False, can_sell=True, **kwargs)
    await grant_category_capability(db_session, company, "packaging.paper-cups",
                                    {"volume_ml": 400, "material": "крафт-картон"},
                                    unit="шт", min_units=1, max_units=60000)
    return user, company, make_token(user)


async def _direct_offer(client, token, company, need_id, **override):
    product = await client.post(
        f"/api/v1/companies/{company}/products",
        json={
            "name": "Стакан 400 мл PE",
            "category": "Упаковка и тара",
            "subcategory": "Бумажные стаканы",
            "characteristics": {"volume_ml": 400, "coating": "PE", "material": "крафт-картон", "unit": "шт"},
            "price_rub": 12,
            "moq_units": 1_000,
            "lead_time_days": 9,
            "stock_units": 20_000,
        },
        headers=_auth(token),
    )
    assert product.status_code == 201, product.text
    payload = {
        "commercial_terms": confirmed_quote_terms(),
        "company_id": str(company),
        "resource_kind": "stock",
        "product_id": product.json()["id"],
        "price_rub": 11.5,
        "available_units": 5_000,
        "moq_units": 1_000,
        "delivery_cost_rub": 3_000,
        "lead_time_days": 9,
    }
    payload.update(override)
    response = await client.post(f"/api/v1/needs/{need_id}/offers", json=payload, headers=_auth(token))
    assert response.status_code == 201, response.text
    return response.json()


async def _select(client, token, offer_id, revision=1, approved=True):
    return await client.post(
        f"/api/v1/offers/{offer_id}/select",
        json={"human_approved": approved, "expected_revision": revision},
        headers=_auth(token),
    )


async def test_select_consent_boundary(client, db_session):
    _, seller_company, seller_token = await _seller_company(db_session)
    await passport(client, seller_token, seller_company, moq=1)
    await grant_packaging_documents(db_session, seller_company, decision_user_id=None,
                                    confirms={"material": ["крафт-картон"], "coating": ["PE"]})
    buyer_user, _, buyer_token, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    offer = await _direct_offer(client, seller_token, seller_company, need_id)

    blocked = await client.post(f"/api/v1/offers/{offer['id']}/select",
                                json={"human_approved": True, "expected_revision": 1},
                                headers=_auth(make_token(uuid.uuid4())))
    assert blocked.status_code == 401

    stranger = await make_user(db_session)
    foreign = await client.post(f"/api/v1/offers/{offer['id']}/select",
                                json={"human_approved": True, "expected_revision": 1},
                                headers=_auth(make_token(stranger)))
    assert foreign.status_code == 404

    buyer_user2 = await make_user(db_session)
    _ = buyer_user2
    member_without_buy = await make_user(db_session)
    need_company = (await db_session.execute(
        text("SELECT company_id FROM marketplace.needs WHERE id = :id"), {"id": uuid.UUID(need_id)})).scalar_one()
    await db_session.execute(
        text("INSERT INTO auth.company_members (id, company_id, user_id, can_buy, can_sell, is_admin) "
             "VALUES (:id, :cid, :uid, false, false, false)"),
        {"id": uuid.uuid4(), "cid": need_company, "uid": member_without_buy},
    )
    await db_session.commit()
    norole = await client.post(f"/api/v1/offers/{offer['id']}/select",
                               json={"human_approved": True, "expected_revision": 1},
                               headers=_auth(make_token(member_without_buy)))
    assert norole.status_code == 403

    await db_session.execute(
        text("UPDATE auth.users SET account_status = 'blocked' WHERE id = :id"), {"id": buyer_user})
    await db_session.commit()
    after_block = await _select(client, buyer_token, offer["id"])
    assert after_block.status_code == 401
    await db_session.execute(
        text("UPDATE auth.users SET account_status = 'active' WHERE id = :id"), {"id": buyer_user})
    await db_session.commit()

    await db_session.execute(
        text("DELETE FROM auth.company_members WHERE company_id = :cid AND user_id = :uid"),
        {"cid": need_company, "uid": buyer_user})
    await db_session.commit()
    revoked = await _select(client, buyer_token, offer["id"])
    assert revoked.status_code == 404


async def test_expired_offer_and_stale_revision_create_nothing(client, db_session):
    _, seller_company, seller_token = await _seller_company(db_session)
    await passport(client, seller_token, seller_company, moq=1)
    await grant_packaging_documents(db_session, seller_company, decision_user_id=None,
                                    confirms={"material": ["крафт-картон"], "coating": ["PE"]})
    _, _, buyer_token, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    offer = await _direct_offer(client, seller_token, seller_company, need_id)
    await db_session.execute(
        text("UPDATE marketplace.offers SET valid_until = CURRENT_DATE - 1 WHERE id = :id"),
        {"id": uuid.UUID(offer["id"])})
    await db_session.commit()
    expired = await _select(client, buyer_token, offer["id"])
    assert expired.status_code == 409
    assert await db_session.scalar(select(Deal)) is None

    fresh = offer
    await db_session.execute(
        text("UPDATE marketplace.offers SET valid_until = NULL WHERE id = :id"),
        {"id": uuid.UUID(offer["id"])})
    await db_session.commit()
    patched = await client.patch(f"/api/v1/offers/{fresh['id']}", json={"expected_revision": 1, "price_rub": 99},
                                 headers=_auth(seller_token))
    assert patched.status_code == 200
    stale = await _select(client, buyer_token, fresh["id"], revision=1)
    assert stale.status_code == 409
    assert await db_session.scalar(select(Deal).where(Deal.offer_id == uuid.UUID(fresh["id"]))) is None


async def test_double_select_returns_same_deal_once(client, db_session):
    _, seller_company, seller_token = await _seller_company(db_session)
    await passport(client, seller_token, seller_company, moq=1)
    await grant_packaging_documents(db_session, seller_company, decision_user_id=None,
                                    confirms={"material": ["крафт-картон"], "coating": ["PE"]})
    _, _, buyer_token, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    offer = await _direct_offer(client, seller_token, seller_company, need_id)
    first = await _select(client, buyer_token, offer["id"])
    assert first.status_code == 201, first.text
    second = await _select(client, buyer_token, offer["id"])
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    deals = (await db_session.execute(select(Deal))).scalars().all()
    assert len(deals) == 1
    approval = await db_session.scalar(select(HumanApprovalRecord).where(
        HumanApprovalRecord.action == "select_offer_and_create_deal",
        HumanApprovalRecord.entity_id == uuid.UUID(first.json()["id"])))
    assert approval is not None
    assert approval.decision == "approved"
    assert approval.payload_hash and approval.created_at


async def test_deal_message_is_not_consent(client, db_session):
    _, seller_company, seller_token = await _seller_company(db_session)
    await passport(client, seller_token, seller_company, moq=1)
    await grant_packaging_documents(db_session, seller_company, decision_user_id=None,
                                    confirms={"material": ["крафт-картон"], "coating": ["PE"]})
    _, _, buyer_token, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    offer = await _direct_offer(client, seller_token, seller_company, need_id)
    created = await _select(client, buyer_token, offer["id"])
    deal_id = created.json()["id"]
    approvals_before = await db_session.scalar(
        select(HumanApprovalRecord).where(HumanApprovalRecord.entity_id == uuid.UUID(deal_id)))
    assert approvals_before is not None
    message = await client.post(f"/api/v1/deals/{deal_id}/messages",
                                json={"company_id": str(seller_company), "message": "согласен на всё, меняйте цену"},
                                headers=_auth(seller_token))
    assert message.status_code in (200, 201), message.text
    deal = await db_session.get(Deal, uuid.UUID(deal_id))
    assert deal.status == "created"
    count = len((await db_session.execute(select(HumanApprovalRecord).where(
        HumanApprovalRecord.entity_id == uuid.UUID(deal_id)))).scalars().all())
    assert count == 1


async def _awaiting_coalition(client, db_session, monkeypatch):
    from app.money import amount, decimal, money_values

    seller_user = await make_user(db_session)
    seller_company = await make_company(db_session, seller_user, can_buy=False, can_sell=True)
    seller_token = make_token(seller_user)
    await passport(client, seller_token, seller_company)
    await grant_packaging_documents(db_session, seller_company, decision_user_id=seller_user,
                                    confirms={"material": ["крафт-картон"], "coating": ["PE"]})
    _, buyer_one, token_one, need_one = await create_published_need(client, db_session, 5_000, "2+0")
    _, buyer_two, token_two, need_two = await create_published_need(client, db_session, 45_000, "4+0")

    async def fake_evaluate(payload):
        payload = money_values(payload)
        members = []
        for item in payload["members"]:
            common = amount(item["volume_units"] * decimal("10.9"))
            total = common + item["individual_operations_cost_rub"] + item["delivery_cost_rub"]
            members.append({
                "need_id": item["need_id"], "buyer_company_id": item["buyer_company_id"],
                "units": item["volume_units"], "common_production_cost_rub": common,
                "individual_operations_cost_rub": item["individual_operations_cost_rub"],
                "delivery_cost_rub": item["delivery_cost_rub"], "total_cost_rub": total,
                "baseline_cost_rub": item["individual_baseline_cost_rub"], "benefit_rub": None,
                "within_budget": True, "deadline_met": True})
        return {"compatible": True, "feasible": True, "combined_volume_units": 50_000,
                "unit_price_rub": 10.9, "members": members, "reasons": ["ok"], "input_hash": "s07"}

    monkeypatch.setattr("app.api.market.evaluate_coalition", fake_evaluate)
    production_start = date.today() + timedelta(days=10)
    await grant_capacity(db_session, seller_company, 60_000, production_start)
    opportunities = await client.get(f"/api/v1/companies/{seller_company}/market-opportunities",
                                     headers=auth(seller_token))
    opportunity = opportunities.json()[0]
    draft = await client.post(f"/api/v1/opportunities/{opportunity['id']}/prepare-offer",
                              headers=auth(seller_token))
    published = await client.post(
        f"/api/v1/group-offers/{draft.json()['id']}/publish",
        json={"min_total_units": 50_000, "max_total_units": 60_000, "available_capacity_units": 60_000,
              "price_tiers": [{"min_units": 50_000, "unit_price_rub": 10.9}],
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
                   "individual_baseline_cost_rub": 540_000, "delivery_days": 1}]},
        headers=auth(seller_token))
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "awaiting_approvals"
    return {
        "seller": (seller_user, seller_company, seller_token),
        "one": (buyer_one, token_one, need_one),
        "two": (buyer_two, token_two, need_two),
        "coalition_id": published.json()["id"],
        "revision": published.json()["version"],
    }


async def test_coalition_decision_records_consent(client, db_session, monkeypatch):
    ctx = await _awaiting_coalition(client, db_session, monkeypatch)
    buyer_one, token_one, _ = ctx["one"]
    decided = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                                json={"company_id": str(buyer_one), "decision": "approved",
                                      "expected_revision": ctx["revision"]},
                                headers=auth(token_one))
    assert decided.status_code == 200, decided.text
    approval = await db_session.scalar(select(HumanApprovalRecord).where(
        HumanApprovalRecord.action == "coalition_member_decision",
        HumanApprovalRecord.entity_id == uuid.UUID(ctx["coalition_id"]),
        HumanApprovalRecord.actor_company_id == buyer_one))
    assert approval is not None
    assert approval.decision == "approved"
    assert approval.actor_user_id is not None
    assert approval.payload_hash and approval.created_at


async def test_coalition_consent_boundary(client, db_session, monkeypatch):
    ctx = await _awaiting_coalition(client, db_session, monkeypatch)
    buyer_one, token_one, _ = ctx["one"]
    buyer_two, token_two, _ = ctx["two"]
    stranger = await make_user(db_session)
    foreign = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                                json={"company_id": str(buyer_two), "decision": "approved",
                                      "expected_revision": ctx["revision"]},
                                headers=_auth(make_token(stranger)))
    assert foreign.status_code in (403, 404)
    cross = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                              json={"company_id": str(buyer_two), "decision": "approved",
                                    "expected_revision": ctx["revision"]},
                              headers=auth(token_one))
    assert cross.status_code in (403, 404)
    stale = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                              json={"company_id": str(buyer_one), "decision": "approved",
                                    "expected_revision": ctx["revision"] + 99},
                              headers=auth(token_one))
    assert stale.status_code == 409
    none_consented = await db_session.scalar(select(HumanApprovalRecord).where(
        HumanApprovalRecord.action == "coalition_member_decision"))
    assert none_consented is None


async def test_parallel_member_approvals_single_obligation(client, db_session, monkeypatch):
    ctx = await _awaiting_coalition(client, db_session, monkeypatch)
    buyer_one, token_one, _ = ctx["one"]
    buyer_two, token_two, _ = ctx["two"]

    async def decide(company, token):
        return await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                                 json={"company_id": str(company), "decision": "approved",
                                       "expected_revision": ctx["revision"]},
                                 headers=auth(token))

    first, second = await asyncio.gather(decide(buyer_one, token_one), decide(buyer_two, token_two))
    assert {first.status_code, second.status_code} <= {200}
    orders = (await db_session.execute(select(ParticipantOrder))).scalars().all()
    assert len(orders) == 2
    approvals = (await db_session.execute(select(HumanApprovalRecord).where(
        HumanApprovalRecord.action == "coalition_member_decision"))).scalars().all()
    assert len(approvals) == 2
    coalition = (await client.get("/api/v1/coalitions/mine", headers=auth(token_one))).json()[0]
    assert coalition["status"] == "confirmed"


async def test_reserve_decision_consent_boundary(client, db_session):
    from app.models import Need, Offer, OptimizationVariantRecord, ReserveCommitment, ResiliencePlan

    buyer_user = await make_user(db_session)
    buyer = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    seller_user = await make_user(db_session)
    seller = await make_company(db_session, seller_user, can_buy=False, can_sell=True)
    need = Need(company_id=buyer, created_by_user_id=buyer_user, category="Упаковка и тара",
                subcategory="Бумажные стаканы", characteristics={"volume_ml": 400, "unit": "шт"},
                volume_units=5_000, deadline_date=date.today() + timedelta(days=30),
                status="open_for_offers", visibility="open_anonymized")
    db_session.add(need)
    await db_session.flush()
    variant = OptimizationVariantRecord(need_id=need.id, kind="reliable", input_hash="s07",
                                        result={"feasible": True})
    db_session.add(variant)
    await db_session.flush()
    plan = ResiliencePlan(need_id=need.id, buyer_company_id=buyer, baseline_variant_id=variant.id,
                          baseline_allocations=[], baseline_total_cost_rub=0, baseline_lead_time_days=1,
                          current_total_cost_rub=0, current_lead_time_days=1, status="ready_for_confirmation")
    db_session.add(plan)
    await db_session.flush()
    commitment = ReserveCommitment(plan_id=plan.id, company_id=seller, reserve_tier="warm",
                                   confirmation_status="pending")
    db_session.add(commitment)
    await db_session.commit()
    payload = {"company_id": str(seller), "decision": "rejected"}

    stranger = await make_user(db_session)
    assert (await client.post(f"/api/v1/reserve-commitments/{commitment.id}/decision", json=payload,
                              headers=_auth(make_token(stranger)))).status_code == 404
    await db_session.execute(
        text("DELETE FROM auth.company_members WHERE company_id = :cid AND user_id = :uid"),
        {"cid": seller, "uid": seller_user})
    await db_session.commit()
    revoked = await client.post(f"/api/v1/reserve-commitments/{commitment.id}/decision", json=payload,
                                headers=_auth(make_token(seller_user)))
    assert revoked.status_code == 404
    assert (await db_session.get(ReserveCommitment, commitment.id)).confirmation_status == "pending"
    assert await db_session.scalar(select(HumanApprovalRecord).where(
        HumanApprovalRecord.entity_id == commitment.id)) is None




async def test_plan_confirm_records_thresholds_and_version(client, db_session, monkeypatch):
    from app.models import Need, Offer, OptimizationVariantRecord
    from conftest import grant_capacity, grant_category_capability
    from test_stage6 import auth as stage6_auth, fake_resilience

    monkeypatch.setattr("app.api.resilience.calculate_resilience", fake_resilience)
    buyer_user = await make_user(db_session)
    buyer = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    buyer_token = make_token(buyer_user)
    primary_user = await make_user(db_session)
    primary = await make_company(db_session, primary_user, can_buy=False, can_sell=True)
    primary_token = make_token(primary_user)
    await grant_capacity(db_session, primary, 5_000)
    await grant_packaging_documents(db_session, primary, decision_user_id=primary_user,
                                    confirms={"material": ["крафт-картон"]})
    await grant_category_capability(db_session, primary, "packaging.paper-cups",
                                    {"volume_ml": 400, "material": "крафт-картон"})
    need = Need(company_id=buyer, created_by_user_id=buyer_user, category="бумажные стаканы",
                characteristics={"volume_ml": 400, "material": "крафт-картон"},
                volume_units=5_000, budget_rub=100_000,
                deadline_date=date.today() + timedelta(days=30), status="open_for_offers")
    db_session.add(need)
    await db_session.flush()
    db_session.add(Offer(need_id=need.id, company_id=primary, created_by_user_id=primary_user,
                         price_rub=10, available_units=5_000, lead_time_days=10,
                         delivery_cost_rub=2_000, moq_units=1_000, price_tiers=[], status="sent"))
    variant = OptimizationVariantRecord(
        need_id=need.id, kind="reliable", input_hash="baseline",
        result={"feasible": True, "total_cost_rub": 52_000, "max_lead_time_days": 10,
                "allocations": [{"company_id": str(primary), "units": 5_000, "unit_price_rub": 10,
                                 "delivery_cost_rub": 2_000, "total_cost_rub": 52_000,
                                 "lead_time_days": 10}]})
    db_session.add(variant)
    await db_session.commit()
    for quote in (await db_session.scalars(select(Offer).where(Offer.need_id == need.id))).all():
        updated = await client.patch(f"/api/v1/offers/{quote.id}", headers=stage6_auth(primary_token),
                                     json={"expected_revision": quote.revision,
                                           "commercial_terms": confirmed_quote_terms()})
        assert updated.status_code == 200, updated.text
    created = await client.post(f"/api/v1/needs/{need.id}/resilience-plans",
                                json={"variant_id": str(variant.id), "max_price_increase_pct": 25,
                                      "max_delay_days": 2, "auto_replace_within_thresholds": True},
                                headers=stage6_auth(buyer_token))
    assert created.status_code == 201, created.text
    plan = created.json()
    confirmed = await client.post(f"/api/v1/resilience-plans/{plan['id']}/confirm",
                                  json={"approved": True, "expected_revision": plan["version"]},
                                  headers=stage6_auth(buyer_token))
    assert confirmed.status_code == 200, confirmed.text
    approval = await db_session.scalar(select(HumanApprovalRecord).where(
        HumanApprovalRecord.action == "confirm_resilience_plan",
        HumanApprovalRecord.entity_id == uuid.UUID(plan["id"])))
    assert approval is not None
    assert approval.actor_company_id == buyer
    assert approval.decision == "approved"
    assert approval.payload_hash and approval.created_at
    from app.models import TrustAuditEvent

    event = await db_session.scalar(select(TrustAuditEvent).where(
        TrustAuditEvent.event_type == "human_approval_recorded",
        TrustAuditEvent.entity_id == uuid.UUID(plan["id"])))
    assert event is not None
    decided = event.payload["decision_payload"]
    assert decided["max_price_increase_pct"] == 25
    assert decided["max_delay_days"] == 2
    assert decided["auto_replace_within_thresholds"] is True
    assert decided["plan_version"] == plan["version"]




async def test_last_consent_rechecks_all_sides_verification(client, db_session, monkeypatch):
    ctx = await _awaiting_coalition(client, db_session, monkeypatch)
    buyer_one, token_one, _ = ctx["one"]
    buyer_two, token_two, _ = ctx["two"]
    from app.models import Coalition
    coalition = await db_session.get(Coalition, uuid.UUID(ctx["coalition_id"]))
    seller_company = coalition.producer_company_id
    first = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                              json={"company_id": str(buyer_one), "decision": "approved",
                                    "expected_revision": ctx["revision"]},
                              headers=auth(token_one))
    assert first.status_code == 200
    await db_session.execute(text("UPDATE auth.companies SET verification_status = 'rejected' WHERE id = :id"),
                             {"id": seller_company})
    await db_session.commit()
    last = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                             json={"company_id": str(buyer_two), "decision": "approved",
                                   "expected_revision": ctx["revision"]},
                             headers=auth(token_two))
    assert last.status_code == 409
    assert (await db_session.execute(select(ParticipantOrder))).scalars().all() == []
    await db_session.execute(text("UPDATE auth.companies SET verification_status = 'verified' WHERE id = :id"),
                             {"id": seller_company})
    await db_session.commit()
    await db_session.execute(text("UPDATE auth.companies SET verification_status = 'rejected' WHERE id = :id"),
                             {"id": buyer_one})
    await db_session.commit()
    last_again = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                                   json={"company_id": str(buyer_two), "decision": "approved",
                                         "expected_revision": ctx["revision"]},
                                   headers=auth(token_two))
    assert last_again.status_code == 409
    assert (await db_session.execute(select(ParticipantOrder))).scalars().all() == []


async def test_select_and_decision_request_keys(client, db_session):
    _, seller_company, seller_token = await _seller_company(db_session)
    await passport(client, seller_token, seller_company, moq=1)
    await grant_packaging_documents(db_session, seller_company, decision_user_id=None,
                                    confirms={"material": ["крафт-картон"], "coating": ["PE"]})
    _, _, buyer_token, need_id = await _buyer_with_published_need(client, db_session, volume=5_000)
    offer = await _direct_offer(client, seller_token, seller_company, need_id)
    key = str(uuid.uuid4())
    first = await client.post(f"/api/v1/offers/{offer['id']}/select",
                              json={"human_approved": True, "expected_revision": 1, "request_key": key},
                              headers=_auth(buyer_token))
    assert first.status_code == 201, first.text
    replay = await client.post(f"/api/v1/offers/{offer['id']}/select",
                               json={"human_approved": True, "expected_revision": 1, "request_key": key},
                               headers=_auth(buyer_token))
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    changed = await client.post(f"/api/v1/offers/{offer['id']}/select",
                                json={"human_approved": True, "expected_revision": 2, "request_key": key},
                                headers=_auth(buyer_token))
    assert changed.status_code == 409


async def test_decision_key_replay_and_conflict(client, db_session, monkeypatch):
    ctx = await _awaiting_coalition(client, db_session, monkeypatch)
    buyer_one, token_one, _ = ctx["one"]
    key = str(uuid.uuid4())
    first = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                              json={"company_id": str(buyer_one), "decision": "approved",
                                    "expected_revision": ctx["revision"], "request_key": key},
                              headers=auth(token_one))
    assert first.status_code == 200, first.text
    replay = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                               json={"company_id": str(buyer_one), "decision": "approved",
                                     "expected_revision": ctx["revision"], "request_key": key},
                               headers=auth(token_one))
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    conflict = await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                                 json={"company_id": str(buyer_one), "decision": "rejected",
                                       "expected_revision": ctx["revision"], "request_key": key},
                                 headers=auth(token_one))
    assert conflict.status_code == 409


async def test_final_consent_replay_after_commit_and_deadline(client, db_session, monkeypatch):
    from app.models import GroupOffer, ResourceReservation

    ctx = await _awaiting_coalition(client, db_session, monkeypatch)
    buyer_one, token_one, _ = ctx["one"]
    buyer_two, token_two, _ = ctx["two"]
    url = f"/api/v1/coalitions/{ctx['coalition_id']}/decision"
    first = await client.post(url, json={"company_id": str(buyer_one), "decision": "approved",
        "expected_revision": ctx["revision"], "request_key": str(uuid.uuid4())}, headers=auth(token_one))
    assert first.status_code == 200, first.text
    payload = {"company_id": str(buyer_two), "decision": "approved",
        "expected_revision": ctx["revision"], "request_key": str(uuid.uuid4())}
    final = await client.post(url, json=payload, headers=auth(token_two))
    assert final.status_code == 200 and final.json()["status"] == "confirmed", final.text
    coalition_id = uuid.UUID(ctx["coalition_id"])

    async def effects():
        orders = (await db_session.scalars(select(ParticipantOrder).where(
            ParticipantOrder.coalition_id == coalition_id))).all()
        resources = (await db_session.scalars(select(ResourceReservation).where(
            ResourceReservation.anchor_type == "coalition", ResourceReservation.anchor_id == coalition_id))).all()
        approvals = (await db_session.scalars(select(HumanApprovalRecord).where(
            HumanApprovalRecord.action == "coalition_member_decision",
            HumanApprovalRecord.entity_id == coalition_id))).all()
        return ({row.id for row in orders}, {(row.id, row.units, row.status) for row in resources},
                {row.id for row in approvals})

    before = await effects()
    assert len(before[0]) == 2 and before[1] and len(before[2]) == 2
    replay = await client.post(url, json=payload, headers=auth(token_two))
    assert replay.status_code == 200 and replay.json() == final.json(), replay.text
    group_offer = await db_session.scalar(select(GroupOffer).where(GroupOffer.coalition_id == coalition_id))
    group_offer.fill_deadline = date.today() - timedelta(days=1)
    await db_session.commit()
    after_deadline = await client.post(url, json=payload, headers=auth(token_two))
    assert after_deadline.status_code == 200 and after_deadline.json()["status"] == "confirmed", after_deadline.text
    assert (await client.post(url, json={**payload, "decision": "rejected"}, headers=auth(token_two))).status_code == 409
    assert (await client.post(url, json={**payload, "request_key": str(uuid.uuid4())}, headers=auth(token_two))).status_code == 409
    await db_session.execute(text("DELETE FROM auth.company_members WHERE company_id = :cid"), {"cid": buyer_two})
    await db_session.commit()
    assert (await client.post(url, json=payload, headers=auth(token_two))).status_code in (403, 404)
    assert await effects() == before


async def test_rejected_consent_replay_after_revision_change(client, db_session, monkeypatch):
    ctx = await _awaiting_coalition(client, db_session, monkeypatch)
    buyer_one, token_one, _ = ctx["one"]
    url = f"/api/v1/coalitions/{ctx['coalition_id']}/decision"
    payload = {"company_id": str(buyer_one), "decision": "rejected",
        "expected_revision": ctx["revision"], "request_key": str(uuid.uuid4())}
    first = await client.post(url, json=payload, headers=auth(token_one))
    assert first.status_code == 200 and first.json()["version"] > ctx["revision"], first.text
    replay = await client.post(url, json=payload, headers=auth(token_one))
    assert replay.status_code == 200 and replay.json() == first.json(), replay.text
    approvals = (await db_session.scalars(select(HumanApprovalRecord).where(
        HumanApprovalRecord.action == "coalition_member_decision",
        HumanApprovalRecord.entity_id == uuid.UUID(ctx["coalition_id"])))).all()
    assert len(approvals) == 1
    assert (await db_session.scalars(select(ParticipantOrder))).all() == []


async def test_publish_records_seller_approval(client, db_session, monkeypatch):
    ctx = await _awaiting_coalition(client, db_session, monkeypatch)
    from app.models import Coalition as CoalitionModel
    coalition = await db_session.get(CoalitionModel, uuid.UUID(ctx["coalition_id"]))
    from app.models import GroupOffer as GroupOfferModel
    offers = (await db_session.execute(select(GroupOfferModel).where(
        GroupOfferModel.coalition_id == coalition.id))).scalars().all()
    assert offers
    seller_approvals = (await db_session.execute(select(HumanApprovalRecord).where(
        HumanApprovalRecord.action == "seller_group_offer_published",
        HumanApprovalRecord.entity_id.in_([offer.id for offer in offers])))).scalars().all()
    assert len(seller_approvals) == 1
    assert seller_approvals[0].decision == "approved"
    assert seller_approvals[0].actor_company_id == coalition.producer_company_id
    assert seller_approvals[0].payload_hash


async def test_approve_recovery_checks_shown_version(client, db_session):
    from app.models import Need, OptimizationVariantRecord, ResiliencePlan, ResilienceScenario

    buyer_user = await make_user(db_session)
    buyer = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    buyer_token = make_token(buyer_user)
    need = Need(company_id=buyer, created_by_user_id=buyer_user, category="Упаковка и тара",
                subcategory="Бумажные стаканы", characteristics={"volume_ml": 400, "unit": "шт"},
                volume_units=5_000, deadline_date=date.today() + timedelta(days=30),
                status="open_for_offers", visibility="open_anonymized")
    db_session.add(need)
    await db_session.flush()
    variant = OptimizationVariantRecord(need_id=need.id, kind="reliable", input_hash="s07",
                                        result={"feasible": True})
    db_session.add(variant)
    await db_session.flush()
    plan = ResiliencePlan(need_id=need.id, buyer_company_id=buyer, baseline_variant_id=variant.id,
                          baseline_allocations=[], baseline_total_cost_rub=0, baseline_lead_time_days=1,
                          current_total_cost_rub=0, current_lead_time_days=1, status="active", version=3,
                          confirmed_at=datetime.now(timezone.utc))
    db_session.add(plan)
    await db_session.flush()
    scenario = ResilienceScenario(plan_id=plan.id, scenario_type="n1", failed_company_ids=[],
                                  result={"uncovered_units": 0, "unconfirmed_units": 0,
                                          "replacement_allocations": [], "new_total_cost_rub": 0,
                                          "new_lead_time_days": 1},
                                  input_hash="s07", status="proposed")
    db_session.add(scenario)
    await db_session.commit()
    missing = await client.post(f"/api/v1/resilience-scenarios/{scenario.id}/approve",
                                json={"approved": True}, headers=_auth(buyer_token))
    assert missing.status_code == 428
    wrong = await client.post(f"/api/v1/resilience-scenarios/{scenario.id}/approve",
                              json={"approved": True, "expected_revision": plan.version + 99},
                              headers=_auth(buyer_token))
    assert wrong.status_code == 409


async def test_same_member_concurrent_double_decide_single_record(client, db_session, monkeypatch):
    ctx = await _awaiting_coalition(client, db_session, monkeypatch)
    buyer_one, token_one, _ = ctx["one"]

    async def decide():
        return await client.post(f"/api/v1/coalitions/{ctx['coalition_id']}/decision",
                                 json={"company_id": str(buyer_one), "decision": "approved",
                                       "expected_revision": ctx["revision"]},
                                 headers=auth(token_one))

    first, second = await asyncio.gather(decide(), decide())
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    approvals = (await db_session.execute(select(HumanApprovalRecord).where(
        HumanApprovalRecord.action == "coalition_member_decision",
        HumanApprovalRecord.actor_company_id == buyer_one))).scalars().all()
    assert len(approvals) == 1

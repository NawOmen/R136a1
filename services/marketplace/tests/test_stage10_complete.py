"""Full S10 user journeys against PostgreSQL, including resource and race effects."""
from synthetic_files import PNG, PDF

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from app.models import Deal, DealExecutionEvent, DealFulfillment, HumanApprovalRecord, Product, ResourceReservation
from conftest import make_user, make_company, make_token
from test_s10_fulfillment import order

DAY = (date.today() + timedelta(days=3)).isoformat()
PROOF = {"note": "Подтверждено синтетическим актом", "attachments": []}
DISPATCH = {**PROOF, "expected_date": DAY, "address": "г. Москва, ул. Синтетическая, 10", "city": "Москва", "region": "Москва",
            "packaging": "Коробки", "places": 2, "weight_kg": 100, "volume_m3": 1, "hazard_class": None}
LOGISTICS = {**PROOF, "expected_date": DAY, "method": "self_pickup", "carrier": "", "cost_rub": "0.00"}


@pytest.fixture
async def full_order(order, db_session):
    product = Product(company_id=order["sc"], name="Синтетический стол", category="Мебель", characteristics={},
        price_rub=1000, price_tiers=[], moq_units=1, lead_time_days=2, stock_units=20)
    db_session.add(product)
    await db_session.flush()
    db_session.add(ResourceReservation(company_id=order["sc"], product_id=product.id,
        anchor_type="deal", anchor_id=order["deal"], units=10, resource_units=10, status="committed"))
    await db_session.commit()
    return {**order, "product": product.id}


async def state(client, order, buyer=True):
    response = await client.get(f"/api/v3/deals/{order['deal']}/fulfillment?company_id={order['bc' if buyer else 'sc']}",
                                headers=order["bh" if buyer else "sh"])
    assert response.status_code == 200, response.text
    return response.json()


async def act(client, order, action, payload, buyer=False, status=200, command=None):
    current = await state(client, order, buyer)
    command = command or {"company_id": str(order["bc" if buyer else "sc"]), "expected_revision": current["revision"],
        "terms_version": current["terms_version"], "human_approved": True, "idempotency_key": str(uuid.uuid4()),
        "action": action, "payload": payload}
    response = await client.post(f"/api/v3/deals/{order['deal']}/fulfillment", headers=order["bh" if buyer else "sh"], json=command)
    assert response.status_code == status, response.text
    return response.json(), command


async def ready(client, order, logistics=None):
    await act(client, order, "prepare", DISPATCH)
    await act(client, order, "production", {**PROOF, "expected_date": DAY})
    await act(client, order, "logistics", logistics or LOGISTICS, buyer=True)


async def shipped(client, order, units=10):
    result, _ = await act(client, order, "shipment", {**PROOF, "expected_date": DAY, "batch": "Синтетическая партия 1", "units": units})
    return result["batches"][-1]["id"]


async def received(client, order, batch, units, missing=0):
    current = await state(client, order)
    return await act(client, order, "receipt", {**PROOF, "expected_date": DAY, "batch_id": batch,
        "line_id": current["line_id"], "received": units, "missing": missing}, buyer=True)


async def inspected(client, order, batch, accepted, rejected=0, status=200):
    current = await state(client, order)
    return await act(client, order, "inspection", {**PROOF, "expected_date": DAY, "batch_id": batch,
        "line_id": current["line_id"], "accepted": accepted, "rejected": rejected}, buyer=True, status=status)


async def test_whole_cycle_partial_cancel_return_and_financials(client, full_order, db_session):
    o = full_order
    await act(client, o, "production", {**PROOF, "expected_date": DAY}, status=409)
    await ready(client, o)
    batch = await shipped(client, o, 6)
    await inspected(client, o, batch, 1, status=409)  # receipt cannot be skipped
    await received(client, o, batch, 6)
    partial, command = await inspected(client, o, batch, 6)
    assert partial["status"] == "partially_accepted" and partial["totals"]["open_units"] == 4
    replay, _ = await act(client, o, "inspection", {}, buyer=True, command=command)
    assert replay["revision"] == partial["revision"]
    await act(client, o, "complete", {**PROOF, "expected_date": DAY}, buyer=True, status=409)
    pending, _ = await act(client, o, "request", {**PROOF, "kind": "cancellation", "units": 4}, buyer=True)
    request = pending["requests"][-1]["id"]
    await act(client, o, "decision", {**PROOF, "event_id": request, "approved": True}, buyer=True, status=403)
    approved, _ = await act(client, o, "decision", {**PROOF, "event_id": request, "approved": True})
    assert approved["totals"]["open_units"] == 0
    await act(client, o, "complete", {**PROOF, "expected_date": DAY}, buyer=True)
    returning, _ = await act(client, o, "request", {**PROOF, "kind": "return", "units": 2}, buyer=True)
    rid = returning["requests"][-1]["id"]
    await act(client, o, "return_complete", {**PROOF, "event_id": rid}, status=409)
    agreed, _ = await act(client, o, "decision", {**PROOF, "event_id": rid, "approved": True})
    assert agreed["totals"]["returned_units"] == 0
    db_session.expire_all()
    product = await db_session.get(Product, o["product"])
    assert product.stock_units == 14  # approval does not restock or correct revenue
    final, c = await act(client, o, "return_complete", {**PROOF, "event_id": rid, "restock_accepted": True})
    again, _ = await act(client, o, "return_complete", {}, command=c)
    assert final["totals"]["returned_units"] == again["totals"]["returned_units"] == 2
    db_session.expire_all()
    assert (await db_session.get(Product, o["product"])).stock_units == 16
    report = await client.get(f"/api/v3/deals/{o['deal']}/execution?company_id={o['bc']}", headers=o["bh"])
    assert Decimal(report.json()["financials"]["net_goods_revenue_rub"]) == 4000
    assert await db_session.scalar(select(HumanApprovalRecord.id).where(HumanApprovalRecord.action == "stock_return"))
    assert len((await db_session.scalars(select(Deal))).all()) == 1


@pytest.mark.parametrize("resolution", ["credit", "accept"])
async def test_missing_rejected_bilateral_resolution(client, full_order, db_session, resolution):
    o = full_order
    await ready(client, o)
    batch = await shipped(client, o)
    await received(client, o, batch, 8, missing=2)
    result, _ = await inspected(client, o, batch, 5, rejected=3)
    assert result["totals"]["accepted_units"] == 5 and result["status"] == "disputed"
    await inspected(client, o, batch, 1, status=409)
    for dispute in result["disputes"]:
        await act(client, o, "dispute_decision", {**PROOF, "dispute_id": dispute["id"], "approved": True}, buyer=True, status=409)
        await act(client, o, "dispute_response", {**PROOF, "dispute_id": dispute["id"], "resolution": resolution})
        final, _ = await act(client, o, "dispute_decision", {**PROOF, "dispute_id": dispute["id"], "approved": True}, buyer=True)
    assert final["totals"]["open_units"] == 0 and final["totals"]["shipped_units"] == 10
    assert final["totals"]["accepted_units"] == (5 if resolution == "credit" else 10)
    await act(client, o, "complete", {**PROOF, "expected_date": DAY}, buyer=True)
    db_session.expire_all()
    assert (await db_session.get(Product, o["product"])).stock_units == 10  # no credit restock


async def test_unknown_tariff_manual_cargo_and_bilateral_version(client, full_order):
    o = full_order
    await act(client, o, "prepare", {**DISPATCH, "volume_m3": 13, "hazard_class": "3"})
    await act(client, o, "logistics", {**LOGISTICS, "cost_rub": None}, buyer=True, status=409)
    await act(client, o, "logistics", LOGISTICS, buyer=True, status=409)
    proposal, _ = await act(client, o, "logistics", {**LOGISTICS, "method": "seller_delivery", "cost_rub": "123.45", "manual_confirmation": True}, buyer=True)
    await act(client, o, "production", {**PROOF, "expected_date": DAY})
    await act(client, o, "shipment", {**PROOF, "expected_date": DAY, "batch": "Не согласовано", "units": 10}, status=409)
    pid = proposal["proposals"][-1]["id"]
    await act(client, o, "proposal_decision", {**PROOF, "proposal_id": pid, "approved": True}, buyer=True, status=403)
    final, _ = await act(client, o, "proposal_decision", {**PROOF, "proposal_id": pid, "approved": True})
    assert final["terms_version"] == 2 and final["logistics"]["confirmed"] is True
    assert Decimal(final["logistics"]["cost_rub"]) == Decimal("123.45")
    assert final["terms_history"][0]["version"] == 1
    await shipped(client, o)
    await act(client, o, "proposal", {**LOGISTICS, "manual_confirmation": True}, buyer=True, status=409)


async def test_revision_race_has_one_effect_and_legacy_cannot_bypass(client, full_order, db_session):
    o = full_order
    await ready(client, o)
    current = await state(client, o, False)
    base = {"company_id": str(o["sc"]), "expected_revision": current["revision"], "terms_version": 1, "human_approved": True,
            "action": "shipment", "payload": {**PROOF, "expected_date": DAY, "batch": "Конкурентная партия", "units": 6}}
    responses = await asyncio.gather(*(client.post(f"/api/v3/deals/{o['deal']}/fulfillment", headers=o["sh"],
        json={**base, "idempotency_key": str(uuid.uuid4())}) for _ in range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    db_session.expire_all()
    assert (await db_session.get(Product, o["product"])).stock_units == 14
    legacy = await client.patch(f"/api/v1/deals/{o['deal']}/timeline/delivery", headers=o["bh"],
        json={"company_id": str(o["bc"]), "completed": True, "human_approved": True})
    assert legacy.status_code == 409
    legacy = await client.post(f"/api/v1/deals/{o['deal']}/execution", headers=o["bh"],
        json={"company_id": str(o["bc"]), "kind": "acceptance", "units": 6, "note": "Обход новой проверки",
              "idempotency_key": str(uuid.uuid4()), "human_approved": True})
    assert legacy.status_code == 409


async def test_company_version_attachment_scopes_and_message_not_proposal(client, full_order, db_session):
    o = full_order
    upload = await client.post(f"/api/v3/deals/{o['deal']}/attachments", headers=o["bh"],
        data={"company_id": str(o["bc"]), "terms_version": "1"}, files={"file": ("Синтетический акт.pdf", PDF, "application/pdf")})
    assert upload.status_code == 201, upload.text
    aid = upload.json()["id"]
    message, _ = await act(client, o, "message", {**PROOF, "attachments": [aid]}, buyer=True)
    assert message["messages"][0]["terms_version"] == 1 and message["logistics"] is None
    await act(client, o, "message", {**PROOF, "attachments": [aid]}, status=404)
    own = await client.get(f"/api/v3/deals/{o['deal']}/attachments/{aid}?company_id={o['sc']}", headers=o["sh"])
    assert own.status_code == 200 and own.content.startswith(b"%PDF-")
    user = await make_user(db_session)
    foreign = await make_company(db_session, user)
    await db_session.commit()
    response = await client.get(f"/api/v3/deals/{o['deal']}/attachments/{aid}?company_id={foreign}",
        headers={"Authorization": f"Bearer {make_token(user)}"})
    assert response.status_code == 404
    malformed = await client.post(f"/api/v3/deals/{o['deal']}/attachments", headers=o["bh"],
        data={"company_id": str(o["bc"]), "terms_version": "1"}, files={"file": ("fake.pdf", b"<html>script</html>", "application/pdf")})
    assert malformed.status_code == 422
    invalid, _ = await act(client, o, "prepare", {**DISPATCH, "country": "US"}, status=422)
    assert invalid["detail"]


async def test_reviews_block_unperformed_pending_and_full_return(client, full_order):
    o = full_order
    url = f"/api/v3/deals/{o['deal']}/reviews"
    review = {"company_id": str(o["bc"]), "rating": 5, "comment": "Синтетический отзыв по поставке"}
    assert (await client.post(url, headers=o["bh"], json=review)).status_code == 409
    await ready(client, o)
    batch = await shipped(client, o)
    await received(client, o, batch, 10)
    await inspected(client, o, batch, 10)
    returning, _ = await act(client, o, "request", {**PROOF, "kind": "return", "units": 10}, buyer=True)
    assert (await client.post(url, headers=o["bh"], json=review)).status_code == 409
    rid = returning["requests"][-1]["id"]
    await act(client, o, "decision", {**PROOF, "event_id": rid, "approved": True})
    await act(client, o, "return_complete", {**PROOF, "event_id": rid})
    assert (await client.post(url, headers=o["bh"], json=review)).status_code == 409


async def test_credit_preserves_physical_shipment_for_s09_and_remaining_batch(client, full_order, db_session):
    from app.resilience_execution import execution_state
    from types import SimpleNamespace
    o = full_order
    await ready(client, o)
    batch = await shipped(client, o, 6)
    await received(client, o, batch, 4, missing=2)
    await inspected(client, o, batch, 4)
    dispute = (await state(client, o))["disputes"][0]
    await act(client, o, "dispute_response", {**PROOF, "dispute_id": dispute["id"], "resolution": "credit"})
    final, _ = await act(client, o, "dispute_decision", {**PROOF, "dispute_id": dispute["id"], "approved": True}, buyer=True)
    assert final["totals"]["unshipped_units"] == 4
    db_session.expire_all()
    deal = await db_session.get(Deal, o["deal"])
    protected = await execution_state(db_session, SimpleNamespace(need_id=deal.need_id))
    assert protected[str(deal.id)]["protected_units"] == 6
    assert protected[str(deal.id)]["cancelled_units"] == 0  # credit is not unshipped cancellation
    await db_session.rollback()
    new_batch = await shipped(client, o, 4)
    await received(client, o, new_batch, 4)
    result, _ = await inspected(client, o, new_batch, 4)
    assert result["totals"]["shipped_units"] == 10 and result["totals"]["accepted_units"] == 8
    report = await client.get(f"/api/v3/deals/{o['deal']}/execution?company_id={o['bc']}", headers=o["bh"])
    assert report.json()["shipped_units"] == 10 and report.json()["unshipped_units"] == 0
    await act(client, o, "shipment", {**PROOF, "expected_date": DAY, "batch": "Лишняя", "units": 1}, status=409)


async def test_seller_delivery_quote_changes_only_after_bilateral_approval(client, full_order, db_session):
    o = full_order
    await act(client, o, "prepare", DISPATCH)
    before = (await state(client, o))["commercial"]["seller_total_rub"]
    pending, _ = await act(client, o, "logistics", {**LOGISTICS, "method": "seller_delivery", "cost_rub": "123.45"}, buyer=True)
    assert pending["commercial"]["seller_total_rub"] == before
    agreed, _ = await act(client, o, "proposal_decision", {**PROOF, "proposal_id": pending["proposals"][0]["id"], "approved": True})
    assert Decimal(agreed["commercial"]["seller_total_rub"]) == Decimal("10123.45")
    report = await client.get(f"/api/v3/deals/{o['deal']}/execution?company_id={o['bc']}", headers=o["bh"])
    assert Decimal(report.json()["financials"]["delivery_price_rub"]) == Decimal("123.45")
    assert Decimal(agreed["terms_history"][0]["seller_total_rub"]) == 10000
    proposal, _ = await act(client, o, "proposal", LOGISTICS, buyer=True)
    changed, _ = await act(client, o, "proposal_decision", {**PROOF, "proposal_id": proposal["proposals"][-1]["id"], "approved": True})
    assert Decimal(changed["commercial"]["seller_total_rub"]) == 10000
    assert changed["terms_version"] == 3
    await act(client, o, "proposal", {**LOGISTICS, "cost_rub": "30000"}, buyer=True, status=409)
    await act(client, o, "proposal", {**LOGISTICS, "expected_date": (date.today()+timedelta(days=50)).isoformat()}, buyer=True, status=409)


async def test_stale_attachment_and_command_cannot_apply_to_new_terms(client, full_order):
    o = full_order
    await act(client, o, "prepare", DISPATCH)
    upload = await client.post(f"/api/v3/deals/{o['deal']}/attachments", headers=o["bh"],
        data={"company_id": str(o["bc"]), "terms_version": "1"}, files={"file": ("акт.pdf", PDF, "application/pdf")})
    assert upload.status_code == 201
    pending, _ = await act(client, o, "logistics", {**LOGISTICS, "method": "seller_delivery", "cost_rub": "10.00"}, buyer=True)
    await act(client, o, "proposal_decision", {**PROOF, "proposal_id": pending["proposals"][0]["id"], "approved": True})
    await act(client, o, "message", {**PROOF, "attachments": [upload.json()["id"]]}, buyer=True, status=404)
    current = await state(client, o)
    stale = {"company_id": str(o["bc"]), "expected_revision": current["revision"], "terms_version": 1,
        "human_approved": True, "idempotency_key": str(uuid.uuid4()), "action": "message", "payload": PROOF}
    await act(client, o, "message", {}, buyer=True, status=409, command=stale)


async def test_legacy_hazard_concurrent_edits_are_serialized(client, order, monkeypatch):
    from app.api import stage9
    paused, resume = asyncio.Event(), asyncio.Event()
    original = stage9.record_human_approval
    async def guarded(*args, **kwargs):
        result = await original(*args, **kwargs)
        if kwargs.get("payload", {}).get("hazard_class") == "3":
            paused.set()
            await resume.wait()
        return result
    monkeypatch.setattr(stage9, "record_human_approval", guarded)
    url = f"/api/v3/deals/{order['deal']}/delivery"
    base = {"company_id": str(order["bc"]), "weight_kg": 10, "volume_m3": 0.1, "method": "self_pickup", "human_approved": True}
    one = asyncio.create_task(client.put(url, headers=order["bh"], json={**base, "hazard_class": "3"}))
    await asyncio.wait_for(paused.wait(), timeout=5)
    two = asyncio.create_task(client.put(url, headers=order["bh"], json={**base, "weight_kg": 2000}))
    try:
        await asyncio.sleep(0.1)
        assert not two.done()
    finally:
        # The second edit also preserves class 3; do not pause it again.
        monkeypatch.setattr(stage9, "record_human_approval", original)
        resume.set()
    first, second = await asyncio.wait_for(asyncio.gather(one, two), timeout=10)
    assert first.status_code == second.status_code == 200
    assert second.json()["hazard_class"] == "3" and second.json()["cargo_class"] == "manual_review"


async def test_new_contract_blocks_legacy_even_before_first_command_and_keeps_history(client, full_order, db_session):
    from app.models import DealMessage
    o = full_order
    deal = await db_session.get(Deal, o["deal"])
    deal.execution_contract = "fulfillment_v3"
    user_id = await db_session.scalar(text("SELECT user_id FROM auth.company_members WHERE company_id=:company LIMIT 1"), {"company": o["bc"]})
    db_session.add(DealMessage(deal_id=deal.id, author_user_id=user_id, author_company_id=o["bc"], message="Сохранённая историческая переписка"))
    await db_session.commit()
    checkpoint = await client.patch(f"/api/v3/deals/{o['deal']}/timeline/production", headers=o["sh"],
        json={"company_id": str(o["sc"]), "completed": True, "human_approved": True})
    assert checkpoint.status_code == 409
    old_message = await client.post(f"/api/v3/deals/{o['deal']}/messages", headers=o["bh"],
        json={"company_id": str(o["bc"]), "message": "Нельзя обойти привязку к версии"})
    assert old_message.status_code == 409
    original = await state(client, o)
    assert original["messages"][0]["note"] == "Сохранённая историческая переписка"
    await act(client, o, "message", PROOF, buyer=True)
    adopted = await state(client, o)
    assert len(adopted["messages"]) == 2 and adopted["messages"][0] == original["messages"][0]


async def test_return_and_review_share_lock_and_recheck_performance(client, order, monkeypatch):
    from test_s10_fulfillment import complete_checkpoint
    from app.api import commerce
    o = order
    assert (await complete_checkpoint(client, o, "production", o["sh"], o["sc"])).status_code == 200
    assert (await complete_checkpoint(client, o, "shipment", o["sh"], o["sc"])).status_code == 200
    assert (await client.put(f"/api/v3/deals/{o['deal']}/delivery", headers=o["bh"], json={
        "company_id": str(o["bc"]), "weight_kg": 100, "volume_m3": 1, "method": "self_pickup", "human_approved": True})).status_code == 200
    accepted = await client.post(f"/api/v3/deals/{o['deal']}/execution", headers=o["bh"], json={
        "company_id": str(o["bc"]), "kind": "acceptance", "units": 10, "note": "Приёмка по синтетическому акту", "human_approved": True, "idempotency_key": str(uuid.uuid4())})
    assert accepted.status_code == 201
    pending = await client.post(f"/api/v3/deals/{o['deal']}/execution", headers=o["bh"], json={
        "company_id": str(o["bc"]), "kind": "return", "units": 10, "note": "Полный возврат по акту", "human_approved": True, "idempotency_key": str(uuid.uuid4())})
    assert pending.status_code == 201
    paused, resume = asyncio.Event(), asyncio.Event()
    original = commerce.audit
    async def guarded(*args, **kwargs):
        result = await original(*args, **kwargs)
        paused.set()
        await resume.wait()
        return result
    monkeypatch.setattr(commerce, "audit", guarded)
    returning = asyncio.create_task(client.post(f"/api/v3/deals/{o['deal']}/execution/{pending.json()['id']}/decision", headers=o["sh"],
        json={"company_id": str(o["sc"]), "approved": True, "human_approved": True}))
    await asyncio.wait_for(paused.wait(), 5)
    review = asyncio.create_task(client.post(f"/api/v3/deals/{o['deal']}/reviews", headers=o["bh"],
        json={"company_id": str(o["bc"]), "rating": 5, "comment": "Синтетический отзыв во время возврата"}))
    try:
        await asyncio.sleep(0.1)
        assert not review.done()
    finally:
        resume.set()
    returned, denied = await asyncio.wait_for(asyncio.gather(returning, review), 10)
    assert returned.status_code == 200 and denied.status_code == 409


@pytest.mark.parametrize("weight,volume,hazard", [(2000, 1, None), (2000, 13, None), (10, .1, "3")])
async def test_strict_cargo_requires_manual_confirmation(client, full_order, weight, volume, hazard):
    o = full_order
    prepared, _ = await act(client, o, "prepare", {**DISPATCH, "weight_kg": weight, "volume_m3": volume, "hazard_class": hazard})
    assert prepared["dispatch"]["cargo_class"] in {"large", "manual_review"}
    await act(client, o, "logistics", LOGISTICS, buyer=True, status=409)
    agreed, _ = await act(client, o, "logistics", {**LOGISTICS, "manual_confirmation": True}, buyer=True)
    assert agreed["logistics"]["confirmed"]


async def test_historical_receipt_dates_and_messages_survive_adoption(client, order):
    from test_s10_fulfillment import complete_checkpoint
    o = order
    assert (await complete_checkpoint(client, o, "production", o["sh"], o["sc"])).status_code == 200
    assert (await complete_checkpoint(client, o, "shipment", o["sh"], o["sc"])).status_code == 200
    assert (await client.put(f"/api/v3/deals/{o['deal']}/delivery", headers=o["bh"], json={
        "company_id": str(o["bc"]), "weight_kg": 100, "volume_m3": 1, "method": "self_pickup", "human_approved": True})).status_code == 200
    assert (await complete_checkpoint(client, o, "delivery", o["bh"], o["bc"])).status_code == 200
    adopted, _ = await act(client, o, "message", PROOF, buyer=True)
    assert adopted["batches"][0]["received"] == 10
    assert adopted["batches"][0]["accepted"] == 0
    receipt = next(h for h in adopted["history"] if h["action"] == "receipt")
    assert receipt["actual_date"] is not None and receipt["company_id"] == str(o["bc"])

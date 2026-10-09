"""S08: коалиции покупателей и изменение подтверждённой группы.

S08.01 — согласуемое окно сроков, прямой путь с объяснением, объёмы заявлено/подтверждено.
S08.02 — кратность партии на публикации.
S08.03 — единое обязательство в ledger; согласие по истёкшему запросу не завершает группу.
S08.04 — изменение состава после подтверждения: выход ниже MOQ аннулирует старые
условия, частичное изменение применяется единой записью, повтор идемпотентен.
"""
import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import (
    Coalition,
    CoalitionChangeRequest,
    CoalitionMember,
    CompatibilityProfile,
    GroupOffer,
    Need,
    ParticipantOrder,
    ResourceReservation,
)
from app.resources import reservations
from conftest import grant_capacity, make_company, make_token, make_user


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def setup_confirmed_coalition(db_session, *, volumes=(5_000, 45_000), moq=50_000):
    """Подтверждённая группа из двух потребностей без длинного API-пути."""
    seller = await make_user(db_session)
    sc = await make_company(db_session, seller, can_buy=False)
    buyers, companies, needs = [], [], []
    for volume in volumes:
        buyer = await make_user(db_session)
        bc = await make_company(db_session, buyer, can_sell=False)
        need = Need(company_id=bc, created_by_user_id=buyer, category="Упаковка и тара",
                    subcategory="Бумажные стаканы", characteristics={}, volume_units=volume,
                    budget_rub=10_000_000, deadline_date=date.today() + timedelta(days=30),
                    valid_until=date.today() + timedelta(days=20),
                    visibility="open_anonymized", status="matched")
        db_session.add(need)
        buyers.append(buyer)
        companies.append(bc)
        needs.append(need)
    await db_session.flush()
    profile = CompatibilityProfile(category="Упаковка и тара", common_base={"unit": "шт"},
                                   hard_constraints={}, flexible_parameters={}, individual_parts={},
                                   input_hash=f"s08-{uuid.uuid4().hex}")
    db_session.add(profile)
    await db_session.flush()
    coalition = Coalition(compatibility_profile_id=profile.id, producer_company_id=sc,
                          category="Упаковка и тара", combined_volume_units=sum(volumes),
                          target_moq_units=moq, status="confirmed", version=2)
    db_session.add(coalition)
    await db_session.flush()
    for need, bc, volume in zip(needs, companies, volumes):
        db_session.add(CoalitionMember(coalition_id=coalition.id, need_id=need.id,
                                       buyer_company_id=bc, units=volume, approval_status="approved"))
    start = date.today() + timedelta(days=10)
    offer = GroupOffer(coalition_id=coalition.id, company_id=sc, min_total_units=moq,
                       max_total_units=60_000, lot_multiple=1, price_tiers=[],
                       production_start=start, production_end=start + timedelta(days=5),
                       fill_deadline=start - timedelta(days=1),
                       non_fill_rule="close_without_obligations",
                       status="confirmed", seller_approval_status="approved")
    db_session.add(offer)
    await db_session.flush()
    for need, bc, volume in zip(needs, companies, volumes):
        db_session.add(ParticipantOrder(coalition_id=coalition.id, group_offer_id=offer.id,
                                        need_id=need.id, buyer_company_id=bc, seller_company_id=sc,
                                        units=volume, total_price_rub=1000, status="created"))
    day = date.today() + timedelta(days=11)
    await grant_capacity(db_session, sc, sum(volumes), day)
    await db_session.commit()
    return seller, sc, buyers, companies, needs, coalition, offer


@pytest.mark.asyncio
async def test_exit_below_moq_annuls_old_terms(db_session, client):
    """Контроль из ТЗ: 5 000 + 10 000 + 35 000 → 50 000; выход оставляет меньше MOQ."""
    seller, sc, buyers, companies, needs, coalition, offer = await setup_confirmed_coalition(
        db_session, volumes=(5_000, 10_000, 35_000), moq=50_000)
    from app.resources import reserve
    await reserve(db_session, company_id=sc, anchor_type="coalition", anchor_id=coalition.id,
                  units=50_000, deadline=date.today() + timedelta(days=16),
                  category="Упаковка и тара", subcategory="Бумажные стаканы")
    await db_session.commit()
    key = uuid.uuid4()
    created = await client.post(f"/api/v1/coalitions/{coalition.id}/change-requests",
                                headers=auth(make_token(buyers[2])),
                                json={"company_id": str(companies[2]), "reason": "Склад переполнен, забираем 35 000",
                                      "proposed_units": {str(needs[2].id): 0},
                                      "resource_policy": "release_and_rereserve",
                                      "idempotency_key": str(key)})
    assert created.status_code == 201, created.text
    decided = await client.post(f"/api/v1/coalition-changes/{created.json()['id']}/decision",
                                headers=auth(make_token(seller)),
                                json={"company_id": str(sc), "approved": True, "expected_revision": 2})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "applied_annulled"
    for need in needs:
        await db_session.refresh(need)
        assert need.status == "waiting_for_match"
    await db_session.refresh(coalition)
    assert coalition.status == "recalculation_required"
    assert coalition.version == 3
    active = [row for row in await reservations(db_session, sc)
              if row.anchor_type == "coalition" and row.anchor_id == coalition.id
              and row.status in {"held", "committed"}]
    assert active == []
    assert (await db_session.scalars(select(ParticipantOrder))).all() == []
    for need in needs:
        need = await db_session.get(Need, need.id)
        assert need.status == "waiting_for_match"
    # Старая группа не удалена, история сохранена.
    assert await db_session.get(Coalition, coalition.id) is not None


@pytest.mark.asyncio
async def test_partial_change_applies_single_obligation(db_session, client):
    seller, sc, buyers, companies, needs, coalition, offer = await setup_confirmed_coalition(
        db_session, moq=40_000)
    from app.resources import reserve
    await reserve(db_session, company_id=sc, anchor_type="coalition", anchor_id=coalition.id,
                  units=50_000, deadline=date.today() + timedelta(days=16),
                  category="Упаковка и тара", subcategory="Бумажные стаканы")
    await db_session.commit()
    key = uuid.uuid4()
    created = await client.post(f"/api/v1/coalitions/{coalition.id}/change-requests",
                                headers=auth(make_token(buyers[0])),
                                json={"company_id": str(companies[0]), "reason": "Снижаем до 4 000",
                                      "proposed_units": {str(needs[0].id): 4_000},
                                      "resource_policy": "release_and_rereserve",
                                      "idempotency_key": str(key)})
    assert created.status_code == 201, created.text
    decided = await client.post(f"/api/v1/coalition-changes/{created.json()['id']}/decision",
                                headers=auth(make_token(seller)),
                                json={"company_id": str(sc), "approved": True, "expected_revision": 2})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "applied"
    rows = [row for row in await reservations(db_session, sc)
            if row.anchor_type == "coalition" and row.anchor_id == coalition.id
            and row.status in {"held", "committed"}]
    assert sum(row.units for row in rows) == 49_000
    assert not any(row.product_id is not None and "member" in (row.anchor_type or "") for row in rows)
    await db_session.refresh(coalition)
    assert coalition.status == "confirmed"
    assert coalition.version == 3
    members = (await db_session.scalars(
        select(CoalitionMember).where(CoalitionMember.coalition_id == coalition.id))).all()
    assert all(item.approval_status == "pending" for item in members)
    assert (await db_session.scalars(select(ParticipantOrder))).all() == []
    remaining = {str(need.id) for need in needs}
    for need_id in remaining:
        need = await db_session.get(Need, uuid.UUID(need_id))
        await db_session.refresh(need)
        assert need.status == "awaiting_approvals"


@pytest.mark.asyncio
async def test_change_request_idempotent_and_guarded(db_session, client):
    seller, sc, buyers, companies, needs, coalition, offer = await setup_confirmed_coalition(db_session)
    key = uuid.uuid4()
    payload = {"company_id": str(companies[0]), "reason": "Снижаем до 4 000",
               "proposed_units": {str(needs[0].id): 4_000},
               "resource_policy": "release_and_rereserve", "idempotency_key": str(key)}
    first = await client.post(f"/api/v1/coalitions/{coalition.id}/change-requests",
                              headers=auth(make_token(buyers[0])), json=payload)
    assert first.status_code == 201, first.text
    repeat = await client.post(f"/api/v1/coalitions/{coalition.id}/change-requests",
                               headers=auth(make_token(buyers[0])), json=payload)
    assert repeat.status_code == 201, repeat.text
    assert repeat.json()["id"] == first.json()["id"]
    assert len((await db_session.scalars(select(CoalitionChangeRequest))).all()) == 1
    conflict = await client.post(f"/api/v1/coalitions/{coalition.id}/change-requests",
                                 headers=auth(make_token(buyers[0])),
                                 json={**payload, "reason": "Другая причина"})
    assert conflict.status_code == 409
    stranger = await make_user(db_session)
    stranger_company = await make_company(db_session, stranger, can_sell=False)
    await db_session.commit()
    forbidden = await client.post(f"/api/v1/coalitions/{coalition.id}/change-requests",
                                  headers=auth(make_token(stranger)),
                                  json={**payload, "company_id": str(stranger_company),
                                        "idempotency_key": str(uuid.uuid4())})
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_expired_fill_deadline_cannot_complete_group(db_session, client):
    seller, sc, buyers, companies, needs, coalition, offer = await setup_confirmed_coalition(db_session)
    coalition.status = "awaiting_approvals"
    coalition.version = 2
    offer.status = "preliminary"
    offer.fill_deadline = date.today() - timedelta(days=1)
    for need in needs:
        need.status = "awaiting_approvals"
    await db_session.commit()
    response = await client.post(f"/api/v1/coalitions/{coalition.id}/decision",
                                 headers=auth(make_token(buyers[0])),
                                 json={"company_id": str(companies[0]), "decision": "approved",
                                       "expected_revision": 2})
    assert response.status_code == 409
    assert len((await db_session.scalars(select(ParticipantOrder))).all()) == 2


@pytest.mark.asyncio
async def test_confirmed_volumes_shown_separately(db_session, client):
    seller, sc, buyers, companies, needs, coalition, offer = await setup_confirmed_coalition(db_session)
    members = (await db_session.scalars(
        select(CoalitionMember).where(CoalitionMember.coalition_id == coalition.id))).all()
    members[0].approval_status = "pending"
    await db_session.commit()
    response = await client.get("/api/v1/coalitions/mine", headers=auth(make_token(buyers[0])))
    assert response.status_code == 200, response.text
    view = next(item for item in response.json() if item["id"] == str(coalition.id))
    assert view["combined_volume_units"] == 50_000
    assert view["confirmed_volume_units"] in (5_000, 45_000)
    assert view["combined_volume_units"] - view["confirmed_volume_units"] in (5_000, 45_000)


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

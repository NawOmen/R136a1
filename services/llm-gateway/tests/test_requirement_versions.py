import uuid

import pytest

from sqlalchemy import text
from app.schemas import RawExtraction, RawFact


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def start(client, token, **extra):
    result = await client.post("/api/v2/buyer-agent/runs", headers=auth(token),
        data={"request_text": "нужно 5000 стаканов, за десять дней, доставка в Москву", **extra})
    assert result.status_code == 201, result.text
    return result.json()


async def test_durable_sources_revision_and_invalidation(client, token):
    run = await start(client, token)
    base = f"/api/v2/agent-runs/{run['id']}"
    source = await client.get(base + "/sources/request_text", headers=auth(token))
    assert source.status_code == 200
    assert len(source.json()["content_hash"]) == 64
    assert "5000" in source.json()["extracted_text"]
    downloaded = await client.get(base + "/sources/request_text?original=true", headers=auth(token))
    assert downloaded.status_code == 200
    assert "attachment" in downloaded.headers["content-disposition"]
    missing = await client.post(base + "/confirm", headers=auth(token))
    assert missing.status_code == 422
    confirmed = await client.post(base + "/confirm", json={"expected_revision": run["revision"]}, headers=auth(token))
    assert confirmed.status_code == 200, confirmed.text
    value = confirmed.json()
    assert all(p["confirmed_by_user_id"] for p in value["result"]["properties"])
    stale = await client.post(base + "/sources/request_text/invalidate", json={"expected_revision": run["revision"]}, headers=auth(token))
    assert stale.status_code == 409
    removed = await client.post(base + "/sources/request_text/invalidate", json={"expected_revision": value["revision"]}, headers=auth(token))
    assert removed.status_code == 200
    assert removed.json()["state"] == "needs_clarification"
    assert removed.json()["result"]["can_confirm"] is False
    assert (await client.get(base + "/sources/request_text?original=true", headers=auth(token))).status_code == 410
    assert (await client.post(base + "/confirm", json={"expected_revision": removed.json()["revision"]}, headers=auth(token))).status_code == 409


async def test_clarification_keeps_competing_sources_and_rejects_old_revision(client, token, fake_provider):
    fake_provider.extraction = RawExtraction(category="бумажные стаканы", facts=[
        RawFact(key="quantity_units", value=5000, source_id="request_text", confidence=.95, evidence="5000"),
        RawFact(key="lead_time_days", value=10, source_id="request_text", confidence=.95, evidence="десять дней"),
        RawFact(key="delivery_city", value="Москва", source_id="request_text", confidence=.95, evidence="Москву"),
        RawFact(key="material", value="бумага", source_id="request_text", confidence=.99, evidence="бумага"),
        RawFact(key="material", value="пластик", source_id="file_1", confidence=.99, evidence="пластик"),
    ])
    response = await client.post("/api/v2/buyer-agent/runs", headers=auth(token),
        data={"request_text": "бумага 5000 за десять дней доставка в Москву"},
        files={"files": ("старый-заказ.txt", "пластик".encode(), "text/plain")})
    assert response.status_code == 201, response.text
    run = response.json(); base = f"/api/v2/agent-runs/{run['id']}"
    assert (await client.post(base + "/confirm", headers=auth(token), json={"expected_revision": 1})).status_code == 409
    clarified = await client.post(base + "/clarify", headers=auth(token), json={"expected_revision": 1, "answers": {"material": "бумага"}})
    assert clarified.status_code == 200, clarified.text
    updated = clarified.json()
    history = updated["result"]["resolved_conflicts"]
    assert history[0]["competing_sources"][1]["value"] == "пластик"
    assert history[0]["resolved_by_user_id"]
    assert (await client.post(base + "/clarify", headers=auth(token), json={"expected_revision": 1, "answers": {"material": "пластик"}})).status_code == 409
    original = await client.get(base + "/sources/file_1?original=true", headers=auth(token))
    assert original.content.decode() == "пластик"


async def test_sources_require_current_membership(client, token, user_id, db_session):
    company = uuid.uuid4()
    await db_session.execute(text("INSERT INTO auth.companies "
        "(id,full_name,display_name,legal_form,inn,legal_address,country,verification_status) "
        "VALUES (:id,'ООО Синтетический покупатель','Синтетический покупатель','ООО','0000000000','г. Москва, ул. Синтетическая, д. 1','RU','verified')"), {"id":company})
    await db_session.execute(text("INSERT INTO auth.company_members(id,company_id,user_id,can_buy) VALUES (:id,:cid,:uid,true)"),
        {"id": uuid.uuid4(), "cid": company, "uid": user_id})
    await db_session.commit()
    run = await start(client, token, company_id=str(company))
    await db_session.execute(text("DELETE FROM auth.company_members WHERE company_id=:cid"), {"cid": company})
    await db_session.commit()
    result = await client.get(f"/api/v2/agent-runs/{run['id']}/sources/request_text", headers=auth(token))
    assert result.status_code == 403


async def test_empty_placeholder_and_unknown_answers_are_rejected(client, token):
    run = await start(client, token)
    base = f"/api/v2/agent-runs/{run['id']}/clarify"
    for answers in ({"quantity_units": "неизвестно"}, {"quantity_units": -1}, {"material_not_requested": "PLA"}, {"quantity_units": True}):
        response = await client.post(base, headers=auth(token), json={"expected_revision": 1, "answers": answers})
        assert response.status_code == 422, response.text


async def test_mismatched_numeric_evidence_blocks_confirmation_until_user_correction(client, token, fake_provider):
    fake_provider.extraction = RawExtraction(category="бумажные стаканы", facts=[
        RawFact(key="quantity_units", value=9000, source_id="request_text", confidence=.99, evidence="5000 стаканов"),
        RawFact(key="lead_time_days", value=10, source_id="request_text", confidence=.99, evidence="10 дней"),
        RawFact(key="delivery_city", value="Москва", source_id="request_text", confidence=.99, evidence="Москва"),
    ])
    created = await client.post("/api/v2/buyer-agent/runs", headers=auth(token),
        data={"request_text": "Нужно 5000 стаканов, 10 дней, Москва"})
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["state"] == "needs_clarification"
    assert run["result"]["can_confirm"] is False
    quantity = next(prop for prop in run["result"]["properties"] if prop["key"] == "quantity_units")
    assert quantity["status"] == "needs_clarification" and quantity["value"] is None
    assert quantity["sources"][0]["value"] == 9000
    assert quantity["sources"][0]["excerpt"] == "5000 стаканов"
    base = f"/api/v2/agent-runs/{run['id']}"
    blocked = await client.post(base + "/confirm", headers=auth(token),
        json={"expected_revision": run["revision"]})
    assert blocked.status_code == 409
    clarified = await client.post(base + "/clarify", headers=auth(token),
        json={"expected_revision": run["revision"], "answers": {"quantity_units": 5000}})
    assert clarified.status_code == 200, clarified.text
    corrected = clarified.json()
    quantity = next(prop for prop in corrected["result"]["properties"] if prop["key"] == "quantity_units")
    assert quantity["value"] == 5000 and quantity["confirmed_by_user_id"]
    assert quantity["sources"][0]["value"] == 9000
    assert corrected["result"]["resolved_conflicts"][-1]["value"] == 5000
    confirmed = await client.post(base + "/confirm", headers=auth(token),
        json={"expected_revision": corrected["revision"]})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["state"] == "confirmed_by_user"


@pytest.mark.parametrize('key,first,second', [('material','дерево','сталь'),('purpose','офис','улица'),('quantity_units',5000,6000),('lead_time_days',10,20)])
async def test_every_critical_conflict_blocks_confirmation(client, token, fake_provider, key, first, second):
    base = [RawFact(key='quantity_units',value=5000,source_id='request_text',confidence=.99,evidence='5000'),
            RawFact(key='lead_time_days',value=10,source_id='request_text',confidence=.99,evidence='10'),
            RawFact(key='delivery_city',value='Москва',source_id='request_text',confidence=.99,evidence='Москва')]
    base = [fact for fact in base if fact.key != key]
    base += [RawFact(key=key,value=first,source_id='request_text',confidence=.99,evidence=str(first)),
             RawFact(key=key,value=second,source_id='file_1',confidence=.99,evidence=str(second))]
    fake_provider.extraction=RawExtraction(category='Мебель',facts=base)
    response=await client.post('/api/v2/buyer-agent/runs',headers=auth(token),
        data={'request_text':f'5000 10 Москва {first}'},files={'files':('старый-заказ.txt',str(second).encode(),'text/plain')})
    assert response.status_code==201,response.text
    run=response.json()
    assert any(item['key']==key for item in run['result']['conflicts'])
    assert not run['result']['can_confirm']
    assert (await client.post(f"/api/v2/agent-runs/{run['id']}/confirm",headers=auth(token),json={'expected_revision':1})).status_code==409

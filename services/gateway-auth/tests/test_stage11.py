from sqlalchemy import select
from app.models import CompanyVerificationEvent
from test_verification import _make_admin, _register, _create_company, _submit, _auth


async def test_v2_decision_requires_reason_and_replay_is_one_event(client, db_session):
    admin = await _make_admin(client, db_session)
    token = await _register(client, "synthetic-stage11@test.ru")
    company = await _create_company(client, token)
    await _submit(client, token, company["id"])
    url = f"/api/v2/admin/companies/{company['id']}/verification"
    for body in ({"decision": "approve"}, {"decision": "approve", "reason": "   "}):
        assert (await client.post(url, json=body, headers=_auth(admin))).status_code == 422
    body = {"decision": "approve", "reason": "Проверены синтетические реквизиты"}
    for _ in range(2):
        response = await client.post(url, json=body, headers=_auth(admin))
        assert response.status_code == 200, response.text
    events = (await db_session.scalars(select(CompanyVerificationEvent))).all()
    assert len(events) == 1 and events[0].reason == body["reason"]
    assert (await client.post(url, json={**body, "reason": "Другая причина"}, headers=_auth(admin))).status_code == 409

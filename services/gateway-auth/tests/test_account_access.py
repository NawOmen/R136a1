"""Account access is recoverable, bounded and revokes previously issued sessions."""
from datetime import datetime, timedelta, timezone
import hashlib

import pytest
from sqlalchemy import select
from app.api import account
from app.models import AccountRecovery, SecurityEvent, User
from app.security import create_access_token, hash_password


async def account_fixture(db_session):
    user = User(email="access@demo.ru", first_name="Тестовый", last_name="Пользователь", password_hash=hash_password("old-password-123"))
    db_session.add(user)
    await db_session.commit()
    return user, {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def test_password_change_checks_current_password_and_revokes_old_tokens(client, db_session):
    user, headers = await account_fixture(db_session)
    assert (await client.post("/api/v2/auth/password/change", headers=headers, json={"current_password": "incorrect", "password": "new-password-123"})).status_code == 400
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
    changed = await client.post("/api/v2/auth/password/change", headers=headers, json={"current_password": "old-password-123", "password": "new-password-123"})
    assert changed.status_code == 200, changed.text
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {changed.json()['access_token']}"})).status_code == 200
    assert (await client.post("/api/v1/auth/login", json={"email": user.email, "password": "old-password-123"})).status_code == 401
    assert (await client.post("/api/v1/auth/login", json={"email": user.email, "password": "new-password-123"})).status_code == 200


async def test_end_other_sessions_returns_only_replacement_for_requesting_device(client, db_session):
    _, headers = await account_fixture(db_session)
    response = await client.post("/api/v2/auth/sessions/end", headers=headers)
    assert response.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"})).status_code == 200


@pytest.mark.parametrize("password", ["short", "я" * 40])
async def test_new_password_validation(client, db_session, password):
    _, headers = await account_fixture(db_session)
    response = await client.post("/api/v2/auth/password/change", headers=headers, json={"current_password": "old-password-123", "password": password})
    assert response.status_code == 422


async def test_recovery_generic_delivery_hashed_storage_single_use_and_expiry(client, db_session, session_factory, monkeypatch):
    user, headers = await account_fixture(db_session)
    monkeypatch.setattr(account.settings, "smtp_host", "synthetic-mail")
    monkeypatch.setattr(account.settings, "smtp_from", "support@demo.ru")
    monkeypatch.setattr(account, "SessionLocal", session_factory)
    sent = []
    monkeypatch.setattr(account, "send_recovery_email", lambda recipient, code: sent.append((recipient, code)))
    known = await client.post("/api/v2/auth/password/recovery", json={"email": user.email})
    unknown = await client.post("/api/v2/auth/password/recovery", json={"email": "unknown@demo.ru"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == {"message": account.NOTICE}
    assert len(sent) == 1 and sent[0][0] == user.email
    code = sent[0][1]
    challenge = await db_session.get(AccountRecovery, hashlib.sha256(code.encode()).hexdigest())
    assert challenge and challenge.token_hash != code
    assert code not in known.text
    assert (await client.post("/api/v2/auth/password/reset", json={"code": code, "password": "new-password-123"})).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    assert (await client.post("/api/v2/auth/password/reset", json={"code": code, "password": "other-password-123"})).status_code == 400
    await client.post("/api/v2/auth/password/recovery", json={"email": user.email})
    digest = hashlib.sha256(sent[-1][1].encode()).hexdigest()
    expired = await db_session.get(AccountRecovery, digest)
    expired.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()
    assert (await client.post("/api/v2/auth/password/reset", json={"code": sent[-1][1], "password": "other-password-123"})).status_code == 400
    events = (await db_session.scalars(select(SecurityEvent))).all()
    assert not any(code in str(event.reason) for event in events)


async def test_mail_failure_is_observable_without_disclosing_account(client, db_session, session_factory, monkeypatch):
    user, _ = await account_fixture(db_session)
    monkeypatch.setattr(account.settings, "smtp_host", "synthetic-mail")
    monkeypatch.setattr(account.settings, "smtp_from", "support@demo.ru")
    monkeypatch.setattr(account, "SessionLocal", session_factory)
    def fail(*args): raise OSError("synthetic failure")
    monkeypatch.setattr(account, "send_recovery_email", fail)
    response = await client.post("/api/v2/auth/password/recovery", json={"email": user.email})
    assert response.status_code == 202
    assert await db_session.scalar(select(SecurityEvent).where(SecurityEvent.event == "auth.recovery_delivery_failed"))


async def test_unconfigured_mail_is_not_reported_as_sent(client, monkeypatch):
    monkeypatch.setattr(account.settings, "smtp_host", "")
    assert (await client.get("/api/v2/auth/capabilities")).json()["password_recovery"] is False
    assert (await client.post("/api/v2/auth/password/recovery", json={"email": "access@demo.ru"})).status_code == 503


async def test_admin_cannot_lock_out_self_and_blocking_invalidates_sessions_after_unblock(client, db_session):
    user, headers = await account_fixture(db_session)
    admin = User(email="access-admin@demo.ru", first_name="Тестовый", last_name="Администратор", password_hash="synthetic-hash", is_marketplace_admin=True)
    db_session.add(admin)
    await db_session.commit()
    auth = {"Authorization": f"Bearer {create_access_token(admin.id)}"}
    assert (await client.post(f"/api/v1/admin/users/{admin.id}/block", headers=auth, json={"blocked": True})).status_code == 409
    for blocked in (True, False):
        assert (await client.post(f"/api/v1/admin/users/{user.id}/block", headers=auth, json={"blocked": blocked})).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_public_registration_records_both_acknowledgements_and_has_no_legacy_bypass(client, db_session, monkeypatch):
    from app.models import AccountAgreement
    from app.config import settings
    monkeypatch.setattr(settings, 'legacy_registration_enabled', False)
    data = {'rules_version':'rules-2','privacy_version':'privacy-2','first_name':'Проверка','last_name':'Регистрации','email':'new-access@demo.ru','password':'new-access-password'}
    assert (await client.post('/api/v1/auth/register', json=data)).status_code == 410
    assert (await client.post('/api/v2/auth/register', json=data)).status_code == 422
    for key in ('rules_accepted','privacy_acknowledged'):
        invalid = {**data, 'rules_accepted':True, 'privacy_acknowledged':True, key:False}
        assert (await client.post('/api/v2/auth/register', json=invalid)).status_code == 422
    assert (await client.post('/api/v2/auth/register', json={**data,'rules_accepted':True,'privacy_acknowledged':True,'rules_version':'outdated'})).status_code == 422
    registered = await client.post('/api/v2/auth/register', json={**data,'rules_accepted':True,'privacy_acknowledged':True})
    assert registered.status_code == 201, registered.text
    records = (await db_session.scalars(select(AccountAgreement))).all()
    assert {(r.document,r.version) for r in records} == {('rules','rules-2'),('privacy','privacy-2')}
    headers = {'Authorization': f"Bearer {registered.json()['access_token']}"}
    assert (await client.post('/api/v2/auth/logout', headers=headers)).status_code == 204
    assert (await client.get('/api/v1/auth/me', headers=headers)).status_code == 401


async def test_recovery_retries_after_initial_delivery_failure_from_persisted_state(client, db_session, session_factory, monkeypatch):
    from fastapi import Request
    user, _ = await account_fixture(db_session)
    monkeypatch.setattr(account.settings, 'smtp_host', 'synthetic-mail')
    monkeypatch.setattr(account.settings, 'smtp_from', 'support@demo.ru')
    monkeypatch.setattr(account, 'SessionLocal', session_factory)
    def fail(*args): raise OSError('synthetic failure')
    monkeypatch.setattr(account, 'send_recovery_email', fail)
    assert (await client.post('/api/v2/auth/password/recovery', json={'email':user.email})).status_code == 202
    row = await db_session.scalar(select(AccountRecovery))
    assert row.delivery_status == 'pending' and row.delivery_attempts == 1
    sent = []
    monkeypatch.setattr(account, 'send_recovery_email', lambda recipient,code:sent.append(code))
    await account.deliver(row.token_hash, Request({'type':'http','headers':[]}))
    await db_session.refresh(row)
    assert row.delivery_status == 'sent' and row.delivery_attempts == 2
    assert hashlib.sha256(sent[0].encode()).hexdigest() == row.token_hash
    assert (await client.post('/api/v2/auth/password/reset', json={'code':sent[0],'password':'retry-new-password'})).status_code == 200


async def test_first_admin_bootstrap_is_local_idempotent_and_cannot_appoint_second(client, db_session, session_factory, monkeypatch):
    import bootstrap_admin
    monkeypatch.setattr(bootstrap_admin, 'SessionLocal', session_factory)
    from app.models import AccountAgreement
    user, _ = await account_fixture(db_session)
    with pytest.raises(ValueError):
        await bootstrap_admin.bootstrap(user.email)
    db_session.add_all([AccountAgreement(user_id=user.id, document='rules',version='rules-1'),AccountAgreement(user_id=user.id,document='privacy',version='privacy-1')])
    await db_session.commit()
    await bootstrap_admin.bootstrap(user.email)
    await bootstrap_admin.bootstrap(user.email)
    await db_session.refresh(user)
    assert user.is_marketplace_admin
    assert len((await db_session.scalars(select(SecurityEvent).where(SecurityEvent.event=='admin.first_operator'))).all()) == 1
    other = User(email='other-operator@demo.ru',first_name='Проверка',last_name='Оператора',password_hash='synthetic-hash')
    db_session.add(other)
    await db_session.commit()
    with pytest.raises(ValueError):
        await bootstrap_admin.bootstrap(other.email)


async def test_secret_rotation_cancels_unsent_mail_instead_of_delivering_an_invalid_code(client, db_session, session_factory, monkeypatch):
    from fastapi import Request
    user, _ = await account_fixture(db_session)
    monkeypatch.setattr(account.settings,'smtp_host','synthetic-mail')
    monkeypatch.setattr(account.settings,'smtp_from','support@demo.ru')
    monkeypatch.setattr(account,'SessionLocal',session_factory)
    def fail(*args): raise OSError('synthetic failure')
    monkeypatch.setattr(account,'send_recovery_email',fail)
    await client.post('/api/v2/auth/password/recovery',json={'email':user.email})
    row = await db_session.scalar(select(AccountRecovery))
    monkeypatch.setattr(account.settings,'jwt_secret','rotated-synthetic-key-with-enough-entropy-1234567890')
    sent=[]
    monkeypatch.setattr(account,'send_recovery_email',lambda *args:sent.append(args))
    await account.deliver(row.token_hash,Request({'type':'http','headers':[]}))
    await db_session.refresh(row)
    assert row.delivery_status == 'cancelled' and not sent

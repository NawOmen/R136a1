REGISTER = {"last_name": "Петров", "first_name": "Пётр", "email": "petr@demo.ru", "password": "secret123"}

COMPANY = {
    "full_name": "Общество с ограниченной ответственностью «Тест»",
    "display_name": "ООО «Тест»",
    "legal_form": "ООО",
    "inn": "1234567890",
    "ogrn": "1234567890123",
    "kpp": "123456789",
    "legal_address": "г. Москва, ул. Тестовая, д. 1",
    "can_buy": True,
    "can_sell": True,
}


async def _token(client) -> str:
    r = await client.post("/api/v1/auth/register", json=REGISTER)
    assert r.status_code == 201
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_create_company(client):
    token = await _token(client)
    r = await client.post("/api/v1/companies", json=COMPANY, headers=_auth(token))
    assert r.status_code == 201
    c = r.json()
    assert c["verification_status"] == "draft"
    assert c["country"] == "RU"
    assert c["membership"]["is_admin"] is True
    assert c["membership"]["can_buy"] is True
    assert c["membership"]["can_sell"] is True


async def test_company_appears_in_me(client):
    token = await _token(client)
    await client.post("/api/v1/companies", json=COMPANY, headers=_auth(token))
    me = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert me.status_code == 200
    assert len(me.json()["companies"]) == 1
    assert me.json()["companies"][0]["verification_status"] == "draft"


async def test_patch_company(client):
    token = await _token(client)
    c = (await client.post("/api/v1/companies", json=COMPANY, headers=_auth(token))).json()
    r = await client.patch(f"/api/v1/companies/{c['id']}", json={"display_name": "ООО «Тест-2»"}, headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["display_name"] == "ООО «Тест-2»"


async def test_submit_review(client):
    token = await _token(client)
    c = (await client.post("/api/v1/companies", json=COMPANY, headers=_auth(token))).json()
    r = await client.post(f"/api/v1/companies/{c['id']}/submit-review", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["verification_status"] == "pending_review"


async def test_cannot_edit_after_submit(client):
    token = await _token(client)
    c = (await client.post("/api/v1/companies", json=COMPANY, headers=_auth(token))).json()
    await client.post(f"/api/v1/companies/{c['id']}/submit-review", headers=_auth(token))
    r = await client.patch(f"/api/v1/companies/{c['id']}", json={"display_name": "ООО «Изменено»"}, headers=_auth(token))
    assert r.status_code == 400


async def test_non_member_cannot_patch(client):
    token_a = await _token(client)
    c = (await client.post("/api/v1/companies", json=COMPANY, headers=_auth(token_a))).json()

    other = await client.post(
        "/api/v1/auth/register",
        json={"last_name": "Сидоров", "first_name": "Сидор", "email": "sidr@demo.ru", "password": "secret123"},
    )
    token_b = other.json()["access_token"]

    r = await client.patch(f"/api/v1/companies/{c['id']}", json={"display_name": "ООО «Изменено»"}, headers=_auth(token_b))
    assert r.status_code == 404


async def test_enable_second_permission(client):
    token = await _token(client)
    c = (await client.post("/api/v1/companies", json={**COMPANY, "can_sell": False}, headers=_auth(token))).json()
    assert c["membership"]["can_sell"] is False

    r = await client.patch(
        f"/api/v1/companies/{c['id']}/membership",
        json={"can_buy": True, "can_sell": True},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["can_buy"] is True
    assert r.json()["can_sell"] is True

    me = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert me.json()["companies"][0]["membership"]["can_buy"] is True
    assert me.json()["companies"][0]["membership"]["can_sell"] is True


async def test_cannot_disable_both_permissions(client):
    token = await _token(client)
    c = (await client.post("/api/v1/companies", json=COMPANY, headers=_auth(token))).json()

    r = await client.patch(
        f"/api/v1/companies/{c['id']}/membership",
        json={"can_buy": False, "can_sell": False},
        headers=_auth(token),
    )
    assert r.status_code == 400


async def test_non_admin_cannot_change_membership(client):
    token_a = await _token(client)
    c = (await client.post("/api/v1/companies", json=COMPANY, headers=_auth(token_a))).json()

    other = await client.post(
        "/api/v1/auth/register",
        json={"last_name": "Сидоров", "first_name": "Сидор", "email": "other@demo.ru", "password": "secret123"},
    )
    token_b = other.json()["access_token"]

    r = await client.patch(
        f"/api/v1/companies/{c['id']}/membership",
        json={"can_buy": True, "can_sell": False},
        headers=_auth(token_b),
    )
    assert r.status_code == 404


async def test_create_company_without_modes_fails(client):
    token = await _token(client)
    r = await client.post(
        "/api/v1/companies",
        json={**COMPANY, "can_buy": False, "can_sell": False},
        headers=_auth(token),
    )
    assert r.status_code == 422


async def test_create_company_only_buyer(client):
    token = await _token(client)
    r = await client.post(
        "/api/v1/companies",
        json={**COMPANY, "can_buy": True, "can_sell": False},
        headers=_auth(token),
    )
    assert r.status_code == 201
    assert r.json()["membership"]["can_buy"] is True
    assert r.json()["membership"]["can_sell"] is False


async def test_create_company_only_seller(client):
    token = await _token(client)
    r = await client.post(
        "/api/v1/companies",
        json={**COMPANY, "can_buy": False, "can_sell": True},
        headers=_auth(token),
    )
    assert r.status_code == 201
    assert r.json()["membership"]["can_buy"] is False
    assert r.json()["membership"]["can_sell"] is True

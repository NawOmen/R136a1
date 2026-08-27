from sqlalchemy import select

from app.models import User

REGISTER = {
    "last_name": "Иванов",
    "first_name": "Иван",
    "middle_name": "Иванович",
    "email": "ivan@demo.ru",
    "password": "secret123",
    "phone": "+7 900 000-00-00",
}


async def test_register_and_me(client):
    r = await client.post("/api/v1/auth/register", json=REGISTER)
    assert r.status_code == 201
    data = r.json()
    assert data["user"]["last_name"] == "Иванов"
    assert data["user"]["first_name"] == "Иван"
    assert data["user"]["middle_name"] == "Иванович"
    assert "full_name" not in data["user"]  # ФИО хранится в отдельных колонках

    token = data["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "ivan@demo.ru"
    assert me.json()["companies"] == []


async def test_register_without_middle_name(client):
    payload = {**REGISTER, "middle_name": None, "email": "nopatro@demo.ru"}
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201
    assert r.json()["user"]["middle_name"] is None


async def test_register_duplicate_email(client):
    await client.post("/api/v1/auth/register", json=REGISTER)
    r = await client.post("/api/v1/auth/register", json=REGISTER)
    assert r.status_code == 409


async def test_login_success(client):
    await client.post("/api/v1/auth/register", json=REGISTER)
    r = await client.post("/api/v1/auth/login", json={"email": "ivan@demo.ru", "password": "secret123"})
    assert r.status_code == 200
    assert "access_token" in r.json()


async def test_login_wrong_password(client):
    await client.post("/api/v1/auth/register", json=REGISTER)
    r = await client.post("/api/v1/auth/login", json={"email": "ivan@demo.ru", "password": "wrong"})
    assert r.status_code == 401


async def test_me_without_token(client):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


async def test_password_is_hashed(client, db_session):
    await client.post("/api/v1/auth/register", json=REGISTER)
    result = await db_session.execute(select(User).where(User.email == "ivan@demo.ru"))
    user = result.scalar_one()
    assert user.password_hash != "secret123"
    assert user.password_hash.startswith("$2")


async def test_api_does_not_return_password_hash(client):
    r = await client.post("/api/v1/auth/register", json=REGISTER)
    data = r.json()
    assert "password_hash" not in data["user"]
    assert "password" not in data["user"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert "password_hash" not in me.json()["user"]

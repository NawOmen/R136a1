from conftest import make_company, make_token, make_user


async def test_passport_round_trip_public_profile_and_legacy_client(client, db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=True, can_sell=True)
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    url = f"/api/v1/companies/{company}/capability-passport"
    payload = {"materials": ["сталь"], "size_ranges": {"diameter_mm": [10, 120], "length_mm": [5, 600]},
               "details": {"business_kind": "both", "product_types": "Металлические детали",
                           "limitations": "Без термообработки", "trial_batch": "10 шт. по согласованию"}}
    response = await client.put(url, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["details"]["limitations"] == "Без термообработки"
    assert (await client.get(url, headers=headers)).json()["size_ranges"] == payload["size_ranges"]
    public = await client.get(f"/api/v1/producers/{company}")
    assert public.status_code == 200, public.text
    assert public.json()["capability_details"]["product_types"] == "Металлические детали"
    legacy = await client.put(url, headers=headers, json={"materials": ["алюминий"]})
    assert legacy.status_code == 200
    assert legacy.json()["details"]["trial_batch"] == "10 шт. по согласованию"
    other = await make_user(db_session)
    denied = await client.put(url, headers={"Authorization": f"Bearer {make_token(other)}"}, json=payload)
    assert denied.status_code in {403, 404}


async def test_passport_rejects_invalid_details_and_limits(client, db_session):
    user = await make_user(db_session)
    company = await make_company(db_session, user, can_buy=False, can_sell=True)
    headers = {"Authorization": f"Bearer {make_token(user)}"}
    for payload in ({"details": {"packaging": "x" * 801}}, {"min_order_units": 1000, "max_order_units": 10}):
        response = await client.put(f"/api/v1/companies/{company}/capability-passport", headers=headers, json=payload)
        assert response.status_code == 422

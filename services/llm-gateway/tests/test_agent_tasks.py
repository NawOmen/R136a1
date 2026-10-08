import uuid

import pytest
from sqlalchemy import text

TASKS = "/api/v2/agent-tasks"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_company(db_session, user_id, can_buy=True):
    company_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO auth.companies "
            "(id, full_name, display_name, legal_form, inn, legal_address, country, verification_status) "
            "VALUES (:id, 'ООО «Тест»', 'ООО «Тест»', 'ООО', '7700000001', "
            "'г. Москва, ул. Синтетическая, д. 1', 'RU', 'verified')"
        ),
        {"id": company_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO auth.company_members (id, company_id, user_id, can_buy) "
            "VALUES (:id, :company_id, :user_id, :can_buy)"
        ),
        {"id": uuid.uuid4(), "company_id": company_id, "user_id": user_id, "can_buy": can_buy},
    )
    await db_session.commit()
    return company_id


async def create_task(client, token, company_id, key="key-1", scenario="buyer_investigation"):
    response = await client.post(
        TASKS,
        json={
            "company_id": str(company_id),
            "scenario_type": scenario,
            "input": {"need": "5000 стаканов"},
            "source_refs": [{"type": "text", "id": "request_text", "version": 1}],
            "idempotency_key": key,
        },
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def make_buyer_run(client, token, company_id, text_value="Нужно 5000 бумажных стаканов в Москву за десять дней"):
    response = await client.post(
        "/api/v1/buyer-agent/runs",
        data={"request_text": text_value, "route": "local", "company_id": str(company_id)},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_task_lifecycle_reopen_shows_step_response_and_result(client, token, db_session, user_id):
    company_id = await make_company(db_session, user_id)
    created = await create_task(client, token, company_id)
    assert created["state"] == "queued"
    assert created["created"] is True
    assert "ожидает запуска" in created["current_step"]

    body = (await client.get(TASKS + f"/{created['task_id']}", params={"company_id": str(company_id)}, headers=auth(token))).json()
    assert body["required_response"]["input_hash"]
    assert body["result_artifact"] is None

    started = await client.post(TASKS + f"/{created['task_id']}/start", params={"company_id": str(company_id)},
                                json={"expected_revision": 1}, headers=auth(token))
    assert started.json()["state"] == "running"

    run = await make_buyer_run(client, token, company_id)
    assert run["state"] == "ready_for_review"
    attached = await client.post(TASKS + f"/{created['task_id']}/attach-run", params={"company_id": str(company_id)},
                                 json={"run_id": run["id"]}, headers=auth(token))
    assert attached.status_code == 200, attached.text
    assert attached.json()["state"] == "awaiting_approval"
    assert attached.json()["linked_run_id"] == run["id"]
    assert attached.json()["required_response"]["run_revision"] == run["revision"]

    artifact = {"type": "agent_run_result", "id": run["id"], "revision": run["revision"]}
    approved = await client.post(
        TASKS + f"/{created['task_id']}/approve", params={"company_id": str(company_id)},
        json={"expected_revision": 1, "approval": {"decision": "approved"}, "result_artifact": artifact},
        headers=auth(token),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "completed"
    assert approved.json()["result_artifact"] == artifact

    reopened = (await client.get(TASKS + f"/{created['task_id']}", params={"company_id": str(company_id)},
                                 headers=auth(token))).json()
    assert reopened["state"] == "completed"
    assert reopened["result_artifact"]["id"] == run["id"]
    assert reopened["current_step"]


@pytest.mark.asyncio
async def test_idempotent_create_returns_same_task_without_new_effect(client, token, db_session, user_id):
    company_id = await make_company(db_session, user_id)
    first = await create_task(client, token, company_id, key="repeat-me")
    second = await create_task(client, token, company_id, key="repeat-me")
    assert second["created"] is False
    assert second["task_id"] == first["task_id"]


@pytest.mark.asyncio
async def test_company_switch_does_not_carry_foreign_task(client, token, db_session, user_id):
    first = await make_company(db_session, user_id)
    second = await make_company(db_session, user_id)
    created = await create_task(client, token, first, key="shared-key")
    missing = await client.get(TASKS + f"/{created['task_id']}", params={"company_id": str(second)}, headers=auth(token))
    assert missing.status_code == 404
    other = await create_task(client, token, second, key="shared-key")
    assert other["created"] is True
    assert other["task_id"] != created["task_id"]


@pytest.mark.asyncio
async def test_stale_revision_cannot_resume_or_approve(client, token, db_session, user_id):
    company_id = await make_company(db_session, user_id)
    created = await create_task(client, token, company_id)
    await client.post(TASKS + f"/{created['task_id']}/start", params={"company_id": str(company_id)},
                      json={"expected_revision": 1}, headers=auth(token))
    failed = await client.post(TASKS + f"/{created['task_id']}/fail", params={"company_id": str(company_id)},
                               json={"expected_revision": 1, "error": "сбой извлечения"}, headers=auth(token))
    assert failed.json()["state"] == "failed"
    assert failed.json()["result_artifact"] is None

    stale_resume = await client.post(TASKS + f"/{created['task_id']}/resume", params={"company_id": str(company_id)},
                                     json={"expected_revision": 99}, headers=auth(token))
    assert stale_resume.status_code == 409

    run = await make_buyer_run(client, token, company_id)
    await client.post(TASKS + f"/{created['task_id']}/attach-run", params={"company_id": str(company_id)},
                      json={"run_id": run["id"]}, headers=auth(token))
    stale_approve = await client.post(
        TASKS + f"/{created['task_id']}/approve", params={"company_id": str(company_id)},
        json={"expected_revision": 99, "approval": {"decision": "approved"},
              "result_artifact": {"type": "agent_run_result", "id": run["id"], "revision": run["revision"]}},
        headers=auth(token),
    )
    assert stale_approve.status_code == 409


@pytest.mark.asyncio
async def test_double_approve_has_single_effect(client, token, db_session, user_id):
    company_id = await make_company(db_session, user_id)
    created = await create_task(client, token, company_id)
    await client.post(TASKS + f"/{created['task_id']}/start", params={"company_id": str(company_id)},
                      json={"expected_revision": 1}, headers=auth(token))
    run = await make_buyer_run(client, token, company_id)
    await client.post(TASKS + f"/{created['task_id']}/attach-run", params={"company_id": str(company_id)},
                      json={"run_id": run["id"]}, headers=auth(token))
    payload = {"expected_revision": 1, "approval": {"decision": "approved"},
               "result_artifact": {"type": "agent_run_result", "id": run["id"], "revision": run["revision"]}}
    first = await client.post(TASKS + f"/{created['task_id']}/approve", params={"company_id": str(company_id)},
                              json=payload, headers=auth(token))
    assert first.json()["state"] == "completed"
    second = await client.post(TASKS + f"/{created['task_id']}/approve", params={"company_id": str(company_id)},
                               json=payload, headers=auth(token))
    assert second.status_code == 200
    assert second.json()["result_artifact"] == first.json()["result_artifact"]
    other = await client.post(
        TASKS + f"/{created['task_id']}/approve", params={"company_id": str(company_id)},
        json={**payload, "result_artifact": {"type": "offer", "id": str(uuid.uuid4())}},
        headers=auth(token),
    )
    assert other.status_code == 409


@pytest.mark.asyncio
async def test_completed_requires_saved_artifact_not_model_text(client, token, db_session, user_id):
    company_id = await make_company(db_session, user_id)
    created = await create_task(client, token, company_id)
    await client.post(TASKS + f"/{created['task_id']}/start", params={"company_id": str(company_id)},
                      json={"expected_revision": 1}, headers=auth(token))
    run = await make_buyer_run(client, token, company_id)
    await client.post(TASKS + f"/{created['task_id']}/attach-run", params={"company_id": str(company_id)},
                      json={"run_id": run["id"]}, headers=auth(token))
    for bad_artifact in ({"type": "text", "id": "model words"}, {"type": "offer"}, {"type": "agent_run_result", "id": run["id"]}):
        response = await client.post(
            TASKS + f"/{created['task_id']}/approve", params={"company_id": str(company_id)},
            json={"expected_revision": 1, "approval": {"decision": "approved"}, "result_artifact": bad_artifact},
            headers=auth(token),
        )
        assert response.status_code == 422, bad_artifact
    denied = await client.post(
        TASKS + f"/{created['task_id']}/approve", params={"company_id": str(company_id)},
        json={"expected_revision": 1, "approval": {"decision": "rejected"},
              "result_artifact": {"type": "offer", "id": str(uuid.uuid4())}},
        headers=auth(token),
    )
    assert denied.status_code == 422


@pytest.mark.asyncio
async def test_cancel_is_terminal(client, token, db_session, user_id):
    company_id = await make_company(db_session, user_id)
    created = await create_task(client, token, company_id)
    cancelled = await client.post(TASKS + f"/{created['task_id']}/cancel", params={"company_id": str(company_id)},
                                  json={"expected_revision": 1, "reason": "передумал"}, headers=auth(token))
    assert cancelled.json()["state"] == "cancelled"
    for action, payload in (("start", {"expected_revision": 1}), ("resume", {"expected_revision": 1}),
                            ("heartbeat", None)):
        response = await client.post(TASKS + f"/{created['task_id']}/{action}",
                                     params={"company_id": str(company_id)},
                                     json=payload, headers=auth(token))
        assert response.status_code == 409, action


@pytest.mark.asyncio
async def test_backoff_and_attempts_limit(client, token, db_session, user_id):
    company_id = await make_company(db_session, user_id)
    created = await create_task(client, token, company_id)
    task_id = created["task_id"]
    params = {"company_id": str(company_id)}

    async def fail():
        await client.post(TASKS + f"/{task_id}/start", params=params, json={"expected_revision": 1}, headers=auth(token))
        response = await client.post(TASKS + f"/{task_id}/fail", params=params,
                                     json={"expected_revision": 1, "error": "сбой"}, headers=auth(token))
        assert response.json()["state"] == "failed"

    await fail()
    first = await client.post(TASKS + f"/{task_id}/resume", params=params,
                              json={"expected_revision": 1}, headers=auth(token))
    assert first.status_code == 200
    assert first.json()["attempts"] == 1

    failed_again = await client.post(TASKS + f"/{task_id}/fail", params=params,
                                     json={"expected_revision": 1, "error": "сбой"}, headers=auth(token))
    assert failed_again.json()["state"] == "failed"
    too_soon = await client.post(TASKS + f"/{task_id}/resume", params=params,
                                 json={"expected_revision": 1}, headers=auth(token))
    assert too_soon.status_code == 429

    await db_session.execute(
        text("UPDATE agents.agent_tasks SET updated_at = now() - interval '2 hours' WHERE task_id = :id"),
        {"id": uuid.UUID(task_id)},
    )
    await db_session.commit()
    second = await client.post(TASKS + f"/{task_id}/resume", params=params,
                               json={"expected_revision": 1}, headers=auth(token))
    assert second.status_code == 200
    assert second.json()["attempts"] == 2

    failed_third = await client.post(TASKS + f"/{task_id}/fail", params=params,
                                     json={"expected_revision": 1, "error": "сбой"}, headers=auth(token))
    assert failed_third.json()["state"] == "failed"
    await db_session.execute(
        text("UPDATE agents.agent_tasks SET attempts = 3 WHERE task_id = :id"),
        {"id": uuid.UUID(task_id)},
    )
    await db_session.commit()
    exhausted = await client.post(TASKS + f"/{task_id}/resume", params=params,
                                  json={"expected_revision": 1}, headers=auth(token))
    assert exhausted.status_code == 429


@pytest.mark.asyncio
async def test_interrupted_running_task_resumes_after_stale_heartbeat(client, token, db_session, user_id):
    company_id = await make_company(db_session, user_id)
    created = await create_task(client, token, company_id)
    task_id = created["task_id"]
    params = {"company_id": str(company_id)}
    await client.post(TASKS + f"/{task_id}/start", params=params, json={"expected_revision": 1}, headers=auth(token))

    early = await client.post(TASKS + f"/{task_id}/resume", params=params,
                              json={"expected_revision": 1}, headers=auth(token))
    assert early.status_code == 409

    alive = await client.post(TASKS + f"/{task_id}/heartbeat", params=params, headers=auth(token))
    assert alive.status_code == 200

    await db_session.execute(
        text("UPDATE agents.agent_tasks SET heartbeat_at = now() - interval '10 minutes' WHERE task_id = :id"),
        {"id": uuid.UUID(task_id)},
    )
    await db_session.commit()
    resumed = await client.post(TASKS + f"/{task_id}/resume", params=params,
                                json={"expected_revision": 1}, headers=auth(token))
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "running"
    assert resumed.json()["attempts"] == 1


@pytest.mark.asyncio
async def test_approval_expires_after_ttl(client, token, db_session, user_id):
    company_id = await make_company(db_session, user_id)
    created = await create_task(client, token, company_id)
    await client.post(TASKS + f"/{created['task_id']}/start", params={"company_id": str(company_id)},
                      json={"expected_revision": 1}, headers=auth(token))
    run = await make_buyer_run(client, token, company_id)
    await client.post(TASKS + f"/{created['task_id']}/attach-run", params={"company_id": str(company_id)},
                      json={"run_id": run["id"]}, headers=auth(token))
    await db_session.execute(
        text("UPDATE agents.agent_tasks SET updated_at = now() - interval '25 hours' WHERE task_id = :id"),
        {"id": uuid.UUID(created["task_id"])},
    )
    await db_session.commit()
    late = await client.post(
        TASKS + f"/{created['task_id']}/approve", params={"company_id": str(company_id)},
        json={"expected_revision": 1, "approval": {"decision": "approved"},
              "result_artifact": {"type": "agent_run_result", "id": run["id"], "revision": run["revision"]}},
        headers=auth(token),
    )
    assert late.status_code == 409


@pytest.mark.asyncio
async def test_extraction_cache_binds_company_versions_and_purge(client, token, db_session, user_id, fake_provider):
    company_id = await make_company(db_session, user_id)
    other_id = await make_company(db_session, user_id)
    text_value = "Нужно 5000 бумажных стаканов в Москву за десять дней"
    calls = lambda: len(fake_provider.prompts)

    first = await make_buyer_run(client, token, company_id, text_value)
    assert first["state"] == "ready_for_review"
    after_first = calls()
    assert after_first > 0

    second = await make_buyer_run(client, token, company_id, text_value)
    assert second["state"] == "ready_for_review"
    assert calls() == after_first
    assert any(call["status"] == "cached" for call in second["tool_calls"])

    foreign = await make_buyer_run(client, token, other_id, text_value)
    assert foreign["state"] == "ready_for_review"
    assert calls() > after_first
    assert not any(call["status"] == "cached" for call in foreign["tool_calls"])

    invalidate = await client.post(
        f"/api/v2/agent-runs/{first['id']}/sources/request_text/invalidate",
        json={"expected_revision": first["revision"]}, headers=auth(token),
    )
    assert invalidate.status_code == 200
    third = await make_buyer_run(client, token, company_id, text_value)
    assert calls() > after_first
    assert not any(call["status"] == "cached" for call in third["tool_calls"])

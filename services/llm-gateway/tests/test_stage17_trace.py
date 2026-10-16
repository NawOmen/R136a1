"""Stage 17: one sanitized, response-derived agent task trace.

The optional JSON export is evidence for the contest material only.  It keeps
statuses, enum-like names, source metadata and hashes; identifiers, names,
free text and credentials never leave the test response boundary.
"""

import json
import re
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from test_agent_tasks import TASKS, auth, create_task, make_buyer_run, make_company


SAFE_EXECUTORS = {"model", "calculator", "human", "system"}
SAFE_TOOL_NAMES = {
    "extract_requirements",
    "search_capability_passports",
    "apply_user_clarification",
    "human_approval",
}
SAFE_TOOL_STATUSES = {"success", "failed", "cached", "skipped"}
SAFE_STATES = {
    "queued",
    "running",
    "needs_input",
    "awaiting_approval",
    "completed",
    "failed",
    "cancelled",
    "ready_for_review",
    "confirmed_by_user",
}


def _tool_calls(body: dict) -> list[dict]:
    """Keep only allowlisted response fields and values."""
    rows = []
    for call in body.get("tool_calls", []):
        tool = call.get("tool_name")
        executor = call.get("executor")
        status = call.get("status")
        if tool in SAFE_TOOL_NAMES and executor in SAFE_EXECUTORS and status in SAFE_TOOL_STATUSES:
            rows.append({"tool": tool, "executor": executor, "status": status})
    return rows


def _state(body: dict) -> str | None:
    state = body.get("state")
    return state if state in SAFE_STATES else None


def _source_refs(body: dict) -> list[dict]:
    refs = []
    for source in body.get("source_refs", []):
        kind = source.get("type")
        version = source.get("version")
        if kind in {"text", "file", "document", "image", "audio"} and type(version) is int:
            refs.append({"kind": kind, "version": version})
    return refs


def _safe_snapshot(events: list[dict], *, source_refs: list[dict], input_hash: str | None) -> dict:
    snapshot = {
        "schema": "stage17-trace-1",
        "fixture": "synthetic",
        "execution": "ASGI/PostgreSQL; model provider stubbed",
        "source_refs": source_refs,
        "input_hash": input_hash if isinstance(input_hash, str) and re.fullmatch(r"[0-9a-f]{64}", input_hash) else None,
        "events": events,
    }
    destination = os.environ.get("STAGE17_TRACE_PATH")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    return snapshot


@pytest.mark.asyncio
async def test_actual_task_trace_denial_recovery_and_artifact(client, token, db_session, user_id):
    company_id = await make_company(db_session, user_id)
    created = await create_task(client, token, company_id, key="stage17-trace")
    params = {"company_id": str(company_id)}
    events = [{"kind": "task", "operation": "create", "status": 201, "state": _state(created)}]

    started = await client.post(
        TASKS + f"/{created['task_id']}/start", params=params,
        json={"expected_revision": 1}, headers=auth(token),
    )
    assert started.status_code == 200
    events.append({"kind": "task", "operation": "start", "status": started.status_code,
                   "state": _state(started.json())})

    early = await client.post(
        TASKS + f"/{created['task_id']}/resume", params=params,
        json={"expected_revision": 1}, headers=auth(token),
    )
    assert early.status_code == 409
    events.append({"kind": "denial", "operation": "resume_while_live", "status": early.status_code})

    heartbeat = await client.post(
        TASKS + f"/{created['task_id']}/heartbeat", params=params, headers=auth(token),
    )
    assert heartbeat.status_code == 200
    await db_session.execute(
        text("UPDATE agents.agent_tasks SET heartbeat_at = now() - interval '10 minutes' WHERE task_id = :id"),
        {"id": uuid.UUID(created["task_id"])},
    )
    await db_session.commit()
    resumed = await client.post(
        TASKS + f"/{created['task_id']}/resume", params=params,
        json={"expected_revision": 1}, headers=auth(token),
    )
    assert resumed.status_code == 200
    events.append({"kind": "recovery", "operation": "resume_after_stale_heartbeat",
                   "status": resumed.status_code, "state": _state(resumed.json())})

    run = await make_buyer_run(client, token, company_id)
    events.append({"kind": "run", "operation": "buyer_run", "status": 201,
                   "state": _state(run), "tool_calls": _tool_calls(run)})
    clarified_response = await client.post(
        f"/api/v1/agent-runs/{run['id']}/clarify", headers=auth(token),
        json={"answers": {"quantity_units": 5000}},
    )
    assert clarified_response.status_code == 200
    clarified = clarified_response.json()
    events.append({"kind": "run", "operation": "clarify", "status": clarified_response.status_code,
                   "state": _state(clarified), "tool_calls": _tool_calls(clarified)})

    attached_response = await client.post(
        TASKS + f"/{created['task_id']}/attach-run", params=params,
        json={"run_id": run["id"]}, headers=auth(token),
    )
    assert attached_response.status_code == 200
    attached = attached_response.json()
    assert attached["state"] == "awaiting_approval"
    events.append({"kind": "task", "operation": "attach_run", "status": attached_response.status_code,
                   "state": _state(attached)})

    artifact_revision = clarified["revision"]
    artifact = {"type": "agent_run_result", "id": run["id"], "revision": artifact_revision}
    stale = await client.post(
        TASKS + f"/{created['task_id']}/approve", params=params,
        json={"expected_revision": 99, "approval": {"decision": "approved"},
              "result_artifact": artifact}, headers=auth(token),
    )
    assert stale.status_code == 409
    events.append({"kind": "denial", "operation": "approve_stale_revision", "status": stale.status_code})

    approved = await client.post(
        TASKS + f"/{created['task_id']}/approve", params=params,
        json={"expected_revision": 1, "approval": {"decision": "approved"},
              "result_artifact": artifact}, headers=auth(token),
    )
    assert approved.status_code == 200
    completed = approved.json()
    assert completed["state"] == "completed"
    events.append({"kind": "task", "operation": "approve", "status": approved.status_code,
                   "state": _state(completed), "artifact_type": completed["result_artifact"]["type"],
                   "artifact_revision": completed["result_artifact"]["revision"]})

    reopened_response = await client.get(
        TASKS + f"/{created['task_id']}", params=params, headers=auth(token),
    )
    assert reopened_response.status_code == 200
    reopened = reopened_response.json()
    assert reopened["state"] == "completed"
    assert reopened["result_artifact"]["type"] == "agent_run_result"
    assert reopened["result_artifact"]["revision"] == artifact_revision
    events.append({"kind": "artifact", "operation": "reopen", "status": reopened_response.status_code,
                   "state": _state(reopened), "artifact_type": reopened["result_artifact"]["type"],
                   "artifact_revision": reopened["result_artifact"]["revision"]})

    snapshot = _safe_snapshot(
        events,
        source_refs=_source_refs(created),
        input_hash=(created.get("required_response") or {}).get("input_hash"),
    )
    assert snapshot["schema"] == "stage17-trace-1"
    assert snapshot["source_refs"] == [{"kind": "text", "version": 1}]
    assert snapshot["input_hash"]
    executors = {call["executor"] for event in events for call in event.get("tool_calls", [])}
    assert {"model", "calculator", "human"} <= executors
    assert all("id" not in event and "text" not in event for event in events)

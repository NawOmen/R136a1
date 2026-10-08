"""Сохраняемый task-contract: сквозная задача, повторы, heartbeat и кеш (S04.02, S04.04).

Задача связывает покупателя, расчётчик, поставщика и согласование: остановка
и продолжение не теряют состояние. Повторная попытка не создаёт второй
write-эффект, истёкшая версия не возобновляется с правами старого согласия,
ошибка не маскируется пустым успешным результатом. Кеш привязан к компании,
входной ревизии и версиям источников.
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AgentRun, AgentSource, AgentTask, AgentTaskCache, ToolCall
from .role_passports import SCHEMA_VERSION, TASK_CONTRACT_VERSION

SCENARIO_TYPES = frozenset({
    "buyer_investigation",
    "seller_explain",
    "marketplace_match",
    "coalition_build",
    "resilience_plan",
})

TASK_STATES = frozenset({
    "queued", "running", "needs_input", "awaiting_approval",
    "completed", "failed", "cancelled",
})
TERMINAL_STATES = frozenset({"completed", "cancelled"})

TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"needs_input", "awaiting_approval", "completed", "failed", "cancelled"}),
    "needs_input": frozenset({"running", "failed", "cancelled"}),
    "awaiting_approval": frozenset({"completed", "running", "needs_input", "failed", "cancelled"}),
    "failed": frozenset({"running", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}

BACKOFF_SECONDS = (60, 600, 3600)
HEARTBEAT_TIMEOUT_SECONDS = 300
APPROVAL_TTL_SECONDS = 24 * 3600

STEP_TEXT = {
    "queued": "Задача создана и ожидает запуска.",
    "running": "Задача выполняется; дождитесь шага, ответа или результата.",
    "needs_input": "Требуется ответ: см. required_response.",
    "awaiting_approval": "Требуется согласие человека: проверьте условия и подтвердите.",
    "completed": "Задача завершена сохранённым артефактом.",
    "failed": "Задача завершилась ошибкой; возможен повтор с актуальной версией входа.",
    "cancelled": "Задача отменена; дальнейшие переходы запрещены.",
}

ARTIFACT_TYPES = frozenset({
    "agent_run_result",
    "coalition_calculation",
    "resilience_plan",
})

SCENARIO_ARTIFACTS: dict[str, frozenset[str]] = {
    "buyer_investigation": frozenset({"agent_run_result"}),
    "seller_explain": frozenset({"agent_run_result"}),
    "marketplace_match": frozenset({"agent_run_result"}),
    "coalition_build": frozenset({"agent_run_result", "coalition_calculation"}),
    "resilience_plan": frozenset({"agent_run_result", "resilience_plan"}),
}

RUN_READY_STATES = frozenset({"ready_for_review", "confirmed_by_user"})

RUN_STATE_TO_TASK = {
    "processing_sources": "running",
    "extracting_requirements": "running",
    "running": "running",
    "needs_clarification": "needs_input",
    "ready_for_review": "awaiting_approval",
    "completed": "awaiting_approval",
    "completed_with_fallback": "awaiting_approval",
    "confirmed_by_user": "completed",
    "failed": "failed",
}


def canonical_hash(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_artifact(artifact: dict | None) -> dict:
    if not isinstance(artifact, dict) or artifact.get("type") not in ARTIFACT_TYPES:
        raise HTTPException(422, "Завершение требует сохранённый артефакт, а не текст модели")
    if not artifact.get("id"):
        raise HTTPException(422, "Артефакт обязан ссылаться на сохранённую сущность (id)")
    if artifact["type"] == "agent_run_result" and not artifact.get("revision"):
        raise HTTPException(422, "Снимок процесса обязан содержать ревизию результата")
    return artifact


def validate_approval(approval: dict | None) -> dict:
    if not isinstance(approval, dict) or approval.get("decision") != "approved" or not approval.get("by_user_id"):
        raise HTTPException(422, "Завершение требует явного согласия человека")
    return approval


def _touch(task: AgentTask, state: str) -> None:
    if state not in TRANSITIONS.get(task.state, frozenset()):
        raise HTTPException(409, f"Переход {task.state} → {state} запрещён контрактом задачи")
    task.state = state
    task.current_step = STEP_TEXT[state]
    task.heartbeat_at = _utcnow()


async def owned_task(db: AsyncSession, task_id: uuid.UUID, company_id: uuid.UUID, *, lock=False) -> AgentTask:
    query = select(AgentTask).where(AgentTask.task_id == task_id, AgentTask.company_id == company_id)
    task = await db.scalar(query.with_for_update() if lock else query)
    if task is None:
        raise HTTPException(404, "Задача не найдена в этой компании")
    return task


async def create_task(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    scenario_type: str,
    input_payload: dict,
    source_refs: list,
    idempotency_key: str,
    parent_task_id: uuid.UUID | None = None,
    model_version: str | None = None,
    prompt_version: str | None = None,
) -> tuple[AgentTask, bool]:
    """Создать задачу. Повтор с тем же ключом возвращает существующую без нового эффекта."""
    if scenario_type not in SCENARIO_TYPES:
        raise HTTPException(422, f"Неизвестный тип сценария: {scenario_type}")
    if parent_task_id is not None:
        parent = await db.scalar(
            select(AgentTask).where(
                AgentTask.task_id == parent_task_id, AgentTask.company_id == company_id
            )
        )
        if parent is None:
            raise HTTPException(404, "Родительская задача не найдена в этой компании")
    existing = await db.scalar(
        select(AgentTask).where(
            AgentTask.company_id == company_id, AgentTask.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return existing, False
    task = AgentTask(
        company_id=company_id,
        actor_user_id=actor_user_id,
        scenario_type=scenario_type,
        parent_task_id=parent_task_id,
        input_revision=1,
        idempotency_key=idempotency_key,
        model_version=model_version,
        prompt_version=prompt_version,
        schema_version=SCHEMA_VERSION,
        source_refs=source_refs,
        state="queued",
        current_step=STEP_TEXT["queued"],
        required_response={"input_hash": canonical_hash(input_payload)},
        heartbeat_at=_utcnow(),
    )
    db.add(task)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(AgentTask).where(
                AgentTask.company_id == company_id, AgentTask.idempotency_key == idempotency_key
            )
        )
        if existing is None:
            raise
        return existing, False
    await db.refresh(task)
    return task, True


def start_task(task: AgentTask, expected_revision: int | None = None) -> AgentTask:
    if expected_revision is not None and expected_revision != task.input_revision:
        raise HTTPException(409, "Входная версия устарела; продолжение с правами старого согласия запрещено")
    if task.state != "queued":
        raise HTTPException(409, "Повторный запуск — только через продолжение с контролем попыток и задержки")
    _touch(task, "running")
    return task


def submit_task_input(
    task: AgentTask, input_payload: dict, source_refs: list, expected_revision: int
) -> AgentTask:
    if expected_revision != task.input_revision:
        raise HTTPException(409, "Входная версия устарела; ответ принят только на актуальной версии")
    if task.state != "needs_input":
        raise HTTPException(409, f"Ответ не ожидается в состоянии {task.state}")
    task.input_revision += 1
    task.source_refs = source_refs
    task.required_response = {"input_hash": canonical_hash(input_payload)}
    task.approval = None
    _touch(task, "running")
    return task


async def verify_run_artifact(db: AsyncSession, task: AgentTask, artifact: dict) -> None:
    """Проверка сохранённой сущности в транзакции: существование, компания,
    допустимость для сценария, текущая ревизия, готовность и свежесть источников."""
    if artifact["type"] not in SCENARIO_ARTIFACTS.get(task.scenario_type, frozenset()):
        raise HTTPException(422, f"Артефакт {artifact['type']} недопустим для сценария {task.scenario_type}")
    if artifact["type"] != "agent_run_result":
        return
    try:
        run_id = uuid.UUID(str(artifact["id"]))
    except ValueError:
        raise HTTPException(422, "Артефакт обязан ссылаться на сохранённый процесс") from None
    run = await db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(409, "Связанный процесс не найден; завершение без сохранённого результата запрещено")
    if run.company_id != task.company_id:
        raise HTTPException(403, "Процесс принадлежит другой компании")
    if artifact.get("revision") != run.revision:
        raise HTTPException(409, "Ревизия процесса изменилась; согласие на старых условиях недействительно")
    if run.state not in RUN_READY_STATES:
        raise HTTPException(409, f"Процесс в состоянии {run.state} не готов к согласию")
    stale_sources = await db.scalar(
        select(AgentSource.run_id).where(
            AgentSource.run_id == run.id, AgentSource.active.is_(False)
        ).limit(1)
    )
    if stale_sources is not None:
        raise HTTPException(409, "Источники процесса изменились; требуется новое согласование")


async def approve_task(
    db: AsyncSession, task: AgentTask, *, approval: dict, result_artifact: dict, expected_revision: int
) -> tuple[AgentTask, bool]:
    """Завершить задачу согласием. Повтор с тем же артефактом возвращает задачу без нового эффекта."""
    validate_approval(approval)
    validate_artifact(result_artifact)
    if task.state == "completed":
        if task.result_artifact == result_artifact:
            return task, False
        raise HTTPException(409, "Задача уже завершена другим артефактом")
    if expected_revision != task.input_revision:
        raise HTTPException(409, "Входная версия устарела; согласие на старых условиях недействительно")
    if task.state != "awaiting_approval":
        raise HTTPException(409, f"Согласие не ожидается в состоянии {task.state}")
    if task.approval_requested_at is None:
        raise HTTPException(409, "Срок согласия не зафиксирован; запросите актуальные условия заново")
    if (_utcnow() - task.approval_requested_at) > timedelta(seconds=APPROVAL_TTL_SECONDS):
        raise HTTPException(409, "Срок согласия истёк; запросите актуальные условия заново")
    await verify_run_artifact(db, task, result_artifact)
    task.approval = approval
    task.result_artifact = result_artifact
    task.error = None
    _touch(task, "completed")
    return task, True


def fail_task(task: AgentTask, error: str) -> AgentTask:
    if task.state in TERMINAL_STATES:
        raise HTTPException(409, f"Задача уже завершена состоянием {task.state}")
    task.error = error or "Неизвестная ошибка"
    task.result_artifact = None
    _touch(task, "failed")
    return task


def cancel_task(task: AgentTask, reason: str | None = None) -> AgentTask:
    if task.state in TERMINAL_STATES:
        raise HTTPException(409, f"Задача уже завершена состоянием {task.state}")
    task.error = reason or "Отменена пользователем"
    _touch(task, "cancelled")
    return task


def resume_task(task: AgentTask, expected_revision: int) -> AgentTask:
    """Продолжить после сбоя или перезапуска. Проверяет версию, лимит и backoff."""
    if expected_revision != task.input_revision:
        raise HTTPException(409, "Входная версия устарела; продолжение с правами старого согласия запрещено")
    interrupted = (
        task.state == "running"
        and task.heartbeat_at is not None
        and (_utcnow() - task.heartbeat_at) > timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)
    )
    if task.state == "failed":
        pass
    elif interrupted:
        task.error = f"Прервана без heartbeat {HEARTBEAT_TIMEOUT_SECONDS} c; продолжение с новой попытки"
    else:
        raise HTTPException(409, f"Продолжение невозможно из состояния {task.state}")
    if task.attempts >= task.max_attempts:
        raise HTTPException(429, "Исчерпаны попытки повтора; создайте задачу заново")
    if task.attempts >= 1:
        wait = BACKOFF_SECONDS[min(task.attempts - 1, len(BACKOFF_SECONDS) - 1)]
        if task.updated_at is not None and (_utcnow() - task.updated_at) < timedelta(seconds=wait):
            raise HTTPException(429, f"Повторная попытка доступна через backoff {wait} c")
    task.attempts += 1
    task.error = None
    if interrupted:
        task.heartbeat_at = _utcnow()
        task.current_step = STEP_TEXT["running"]
    else:
        _touch(task, "running")
    return task


def heartbeat_task(task: AgentTask) -> AgentTask:
    if task.state in TERMINAL_STATES:
        raise HTTPException(409, f"Задача уже завершена состоянием {task.state}")
    task.heartbeat_at = _utcnow()
    return task


async def attach_run(db: AsyncSession, task: AgentTask, run: AgentRun) -> AgentTask:
    """Связать процесс с задачей и отразить его шаг. Подтверждённый процесс
    завершает задачу только сохранённым артефактом с ревизией и согласием человека."""
    if run.company_id is not None and run.company_id != task.company_id:
        raise HTTPException(403, "Процесс принадлежит другой компании")
    if task.state in TERMINAL_STATES:
        raise HTTPException(409, f"Задача уже завершена состоянием {task.state}")
    mapped = RUN_STATE_TO_TASK.get(run.state)
    if mapped is None:
        raise HTTPException(409, f"Состояние процесса {run.state} не продолжается задачей")
    task.linked_run_id = run.id
    if run.state == "confirmed_by_user":
        consent_rows = (await db.execute(
            select(ToolCall).where(
                ToolCall.run_id == run.id, ToolCall.tool_name == "human_approval",
                ToolCall.status == "success",
            )
        )).scalars().all()
        if not consent_rows:
            raise HTTPException(409, "Подтверждение человека в процессе отсутствует")
        task.approval = {"decision": "approved", "by_user_id": "run:human_approval",
                         "contract": f"task-contract-{TASK_CONTRACT_VERSION}"}
        task.result_artifact = {"type": "agent_run_result", "id": str(run.id), "revision": run.revision}
        task.error = None
        _touch(task, "completed")
        return task
    if mapped != task.state:
        task.approval = None
        _touch(task, mapped)
    else:
        task.heartbeat_at = _utcnow()
    if mapped == "needs_input":
        result = run.result or {}
        task.required_response = {
            "questions": [{"key": item.get("key"), "question": item.get("question")}
                          for item in result.get("questions", [])],
            "conflicts": [{"key": item.get("key"), "impact": item.get("impact")}
                          for item in result.get("conflicts", [])],
            "run_id": str(run.id),
            "run_revision": run.revision,
        }
    elif mapped == "awaiting_approval":
        task.required_response = {
            "summary": (run.result or {}).get("summary", ""),
            "run_id": str(run.id),
            "run_revision": run.revision,
        }
        task.approval_requested_at = _utcnow()
    elif mapped == "failed":
        task.error = run.error or "Процесс завершился ошибкой"
        task.result_artifact = None
    return task


def extraction_cache_key(scenario_type: str, model_version: str, prompt_version: str, schema_version: str) -> str:
    """Ключ кеша содержит версии модели, промпта и схемы: смена любой версии
    делает старый результат несопоставимым и даёт промах, а не чужую трассу."""
    return f"extraction:{scenario_type}:{model_version}:{prompt_version}:{schema_version}"


async def cache_lookup(
    db: AsyncSession, *, company_id: uuid.UUID, cache_key: str,
    input_hash: str, source_versions_hash: str,
) -> dict | None:
    row = await db.scalar(
        select(AgentTaskCache).where(
            AgentTaskCache.company_id == company_id,
            AgentTaskCache.cache_key == cache_key,
            AgentTaskCache.input_hash == input_hash,
            AgentTaskCache.source_versions_hash == source_versions_hash,
        )
    )
    return dict(row.payload) if row is not None else None


async def cache_store(
    db: AsyncSession, *, company_id: uuid.UUID, cache_key: str,
    input_hash: str, source_versions_hash: str, run_id: uuid.UUID | None,
    source_ids: list, payload: dict,
) -> None:
    row = await db.scalar(
        select(AgentTaskCache).where(
            AgentTaskCache.company_id == company_id,
            AgentTaskCache.cache_key == cache_key,
            AgentTaskCache.input_hash == input_hash,
            AgentTaskCache.source_versions_hash == source_versions_hash,
        )
    )
    if row is None:
        db.add(AgentTaskCache(
            company_id=company_id, cache_key=cache_key, input_hash=input_hash,
            source_versions_hash=source_versions_hash, run_id=run_id,
            source_ids=source_ids, payload=payload,
        ))
    else:
        row.run_id = run_id
        row.source_ids = source_ids
        row.payload = payload
    await db.commit()


async def cache_purge_run(db: AsyncSession, run_id: uuid.UUID) -> int:
    rows = (await db.execute(
        select(AgentTaskCache).where(AgentTaskCache.run_id == run_id)
    )).scalars().all()
    for row in rows:
        await db.delete(row)
    await db.commit()
    return len(rows)

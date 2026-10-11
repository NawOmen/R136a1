import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import HumanApprovalRecord, TrustAuditEvent

GENESIS_HASH = "0" * 64
AUDIT_LOCK_ID = 7_071_367


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


_SECRET_KEY = re.compile(r"(?:password|passwd|pwd|secret|token|api[_-]?key|authorization|cookie|credential)", re.I)
_SECRET_TEXT = re.compile(
    r"(?i)(?:\bBearer\s+[^\s,;]+|\b(?:[\w-]*(?:password|secret|token|api[_-]?key|authorization|credential)[\w-]*)"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+))"
)


def scrub_secrets(value: Any) -> Any:
    """Structured secrets and labelled free-text credentials are removed before hashing.

    No regexp can identify every arbitrary unlabelled secret. Callers must never
    supply original documents or opaque credentials as journal prose.
    """
    if isinstance(value, dict):
        return {key: ("[скрыто]" if isinstance(key, str) and _SECRET_KEY.search(key)
                       else scrub_secrets(item)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub_secrets(item) for item in value]
    if isinstance(value, str):
        return _SECRET_TEXT.sub("[скрыто]", value)
    return value


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _event_material(event: TrustAuditEvent) -> dict:
    return {
        "sequence": event.sequence,
        "previous_hash": event.previous_hash,
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": str(event.entity_id) if event.entity_id else None,
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "actor_company_id": str(event.actor_company_id) if event.actor_company_id else None,
        "source_refs": event.source_refs,
        "explanation": event.explanation,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
    }


async def append_audit_event(
    db: AsyncSession,
    *,
    event_type: str,
    entity_type: str,
    explanation: str,
    entity_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_company_id: uuid.UUID | None = None,
    source_refs: list[dict] | None = None,
    payload: dict | None = None,
) -> TrustAuditEvent:
    """Добавить событие в последовательную хеш-цепочку внутри текущей транзакции."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": AUDIT_LOCK_ID})
    previous = (
        await db.execute(select(TrustAuditEvent).order_by(TrustAuditEvent.sequence.desc()).limit(1))
    ).scalar_one_or_none()
    event = TrustAuditEvent(
        sequence=(previous.sequence + 1) if previous else 1,
        previous_hash=previous.event_hash if previous else GENESIS_HASH,
        event_hash="",
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        actor_company_id=actor_company_id,
        source_refs=scrub_secrets(source_refs or []),
        explanation=scrub_secrets(explanation),
        payload=scrub_secrets(payload or {}),
        created_at=datetime.now(timezone.utc),
    )
    event.event_hash = payload_hash(_event_material(event))
    db.add(event)
    await db.flush()
    return event


async def record_human_approval(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    actor_user_id: uuid.UUID,
    permission: str,
    decision: str,
    payload: dict,
    explanation: str,
    entity_id: uuid.UUID | None = None,
    actor_company_id: uuid.UUID | None = None,
    reason: str | None = None,
    source_refs: list[dict] | None = None,
) -> HumanApprovalRecord:
    if decision not in {"approved", "rejected"}:
        raise ValueError("Решение Human Approval Guard должно быть явным")
    approval = HumanApprovalRecord(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        actor_company_id=actor_company_id,
        permission=permission,
        decision=decision,
        reason=scrub_secrets(reason),
        payload_hash=payload_hash(payload),
    )
    db.add(approval)
    await db.flush()
    await append_audit_event(
        db,
        event_type="human_approval_recorded",
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        actor_company_id=actor_company_id,
        source_refs=source_refs,
        explanation=explanation,
        payload={
            "approval_id": str(approval.id),
            "action": action,
            "permission": permission,
            "decision": decision,
            "payload_hash": approval.payload_hash,
            "decision_payload": payload,
        },
    )
    return approval


def verify_event(previous_hash: str, event: TrustAuditEvent) -> bool:
    return event.previous_hash == previous_hash and event.event_hash == payload_hash(_event_material(event))

"""Guaranteed, idempotent expiry alerts and a durable document/rematch outbox.

Company locks are released before rematch touches needs/resources. Multiple
workers may run: each expiry is serialized with human document decisions and
outbox rows are claimed with SKIP LOCKED. Existing obligations are retained.
"""
import asyncio
import hashlib
import json
import logging
from datetime import date, timedelta

from sqlalchemy import select, text

from .database import SessionLocal
from .models import Document, MatchEvent
from .resources import lock_company
from .trust import append_audit_event

logger = logging.getLogger(__name__)


async def process_expiry(db, document_id, *, today=None):
    from .api.documents import _notify_company, _notify_affected_deals, _reevaluate_products, _queue_document_rematch
    today = today or date.today()
    document = await db.get(Document, document_id)
    if document is None:
        return False
    await lock_company(db, document.company_id)
    document = await db.scalar(select(Document).where(Document.id == document_id)
        .with_for_update().execution_options(populate_existing=True))
    if (document is None or document.verification_status != "verified" or document.valid_until is None
            or document.valid_until > today + timedelta(days=30)):
        return False
    kind = "document_expired" if document.valid_until < today else "document_expiring"
    revision = hashlib.sha256(json.dumps({
        "verified_at": str(document.verified_at), "valid_until": str(document.valid_until),
        "scope": [document.scope_category, document.scope_subcategory], "confirms": document.confirms,
    }, sort_keys=True).encode()).hexdigest()
    previous = await db.scalar(text("SELECT id FROM marketplace.trust_audit_events "
        "WHERE entity_id=:id AND event_type=:kind AND payload->>'revision'=:revision LIMIT 1"),
        {"id": document.id, "kind": kind, "revision": revision})
    if previous:
        return False
    lost = []
    if kind == "document_expired":
        lost = await _reevaluate_products(db, document.company_id, document.scope_category, document.scope_subcategory)
        _queue_document_rematch(db, document.id)
    message = (f"Документ «{document.name}»: срок {'истёк' if kind == 'document_expired' else 'истекает'} "
               f"{document.valid_until.isoformat()}. Ответственному нужно продлить подтверждение. "
               "Действующие договорённости сохраняются; новые действия проверяют актуальный допуск.")
    await _notify_company(db, document.company_id, message)
    await _notify_affected_deals(db, document.company_id, document.name,
                               document.scope_category, document.scope_subcategory)
    await append_audit_event(db, event_type=kind, entity_type="document", entity_id=document.id,
        actor_company_id=document.company_id, explanation=message,
        payload={"revision": revision, "valid_until": str(document.valid_until),
                 "products_without_admission": lost, "responsible": "company_admin"},
        source_refs=[{"type": "document", "id": str(document.id)}])
    return True


async def drain_rematches(db, *, limit=100):
    from .matching import run_market_rematch
    events = list((await db.scalars(select(MatchEvent).where(
        MatchEvent.event_type == "document_admission_changed", MatchEvent.status == "pending")
        .order_by(MatchEvent.created_at).limit(limit).with_for_update(skip_locked=True))).all())
    for event in events:
        await run_market_rematch(db, event.event_type, event.entity_id, event=event)
    return len(events)


async def lifecycle_pass():
    from .category_runtime import current_registry_context
    async with SessionLocal() as db:
        ids = list((await db.scalars(select(Document.id).where(
            Document.verification_status == "verified", Document.valid_until <= date.today() + timedelta(days=30)))).all())
    for document_id in ids:
        async with SessionLocal() as db, current_registry_context(db):
            try:
                await db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                await process_expiry(db, document_id)
                await db.commit()
            except Exception:
                await db.rollback()
                logger.warning("Проверка срока документа отложена; следующая попытка в очередном проходе")
    async with SessionLocal() as db, current_registry_context(db):
        # Yield to foreground commitments before PostgreSQL deadlock detection.
        await db.execute(text("SET LOCAL lock_timeout = '250ms'"))
        await drain_rematches(db, limit=10)
        await db.commit()


async def lifecycle_worker():
    while True:
        try:
            await lifecycle_pass()
        except Exception:
            # Do not log database credentials, source contents or arbitrary exception text.
            logger.error("Проверка сроков документов/повторный подбор не завершены; очередь сохранена для повтора")
        await asyncio.sleep(60)

import importlib.util
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.deps import CurrentUser, notify
from app.notification_links import default_notification_href, internal_notification_href
from app.schemas import NotificationOut
from app.api.notifications import read_notification


@pytest.mark.parametrize("kind,path", [
    ("offer_received", "/needs"), ("offer_selected", "/deals"),
    ("deal_fulfillment_updated", "/deals"), ("support_ticket_created", "/admin#tickets"),
    ("support_ticket_updated", "/support"), ("reserve_invitation", "/seller/reserves"),
    ("market_demand_changed", "/seller/requests"), ("market_supply_changed", "/catalog"),
])
def test_legacy_destinations_have_an_actionable_section(kind, path):
    assert default_notification_href(kind) == path


@pytest.mark.parametrize("href", ["https://example.test", "//example.test", "/\\example.test", "javascript:alert(1)", "/needs\n/other", "/" + "x" * 501])
def test_notification_refuses_external_or_malformed_links(href):
    with pytest.raises(ValueError):
        internal_notification_href(href)


@pytest.mark.asyncio
async def test_specific_entity_link_is_saved_and_returned_without_changing_the_business():
    saved = []
    user_id, need_id = uuid.uuid4(), uuid.uuid4()
    await notify(SimpleNamespace(add=saved.append), user_id, "Получено КП", "offer_received", href=f"/needs/{need_id}")
    item = saved[0]
    item.id = uuid.uuid4()
    item.is_read = False
    assert NotificationOut.model_validate(item).model_dump()["href"] == f"/needs/{need_id}"
    assert item.user_id == user_id and item.type == "offer_received"


def test_old_notification_contract_accepts_missing_destination():
    old = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), message="Старое событие", type="info", is_read=False)
    assert NotificationOut.model_validate(old).href is None


@pytest.mark.asyncio
async def test_read_receipt_never_marks_another_users_notification():
    owner, outsider = uuid.uuid4(), uuid.uuid4()
    item = SimpleNamespace(id=uuid.uuid4(), user_id=owner, is_read=False, href="/deals")
    class DB:
        committed = False
        async def get(self, *_): return item
        async def commit(self): self.committed = True
        async def refresh(self, _): pass
    db = DB()
    with pytest.raises(HTTPException) as error:
        await read_notification(item.id, CurrentUser(outsider), db)
    assert error.value.status_code == 404 and not item.is_read and not db.committed
    result = await read_notification(item.id, CurrentUser(owner), db)
    assert result.is_read and db.committed and result.href == "/deals"


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="Requires isolated PostgreSQL")
async def test_notification_link_migration_roundtrip_keeps_legacy_messages():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0036_notification_links.py"
    spec = importlib.util.spec_from_file_location("notification_link_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = "test_notification_links_" + uuid.uuid4().hex
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f"CREATE SCHEMA {schema}"))
                await connection.execute(text(f"CREATE TABLE {schema}.notifications (id INTEGER PRIMARY KEY, message TEXT NOT NULL, is_read BOOLEAN NOT NULL)"))
                await connection.execute(text(f"INSERT INTO {schema}.notifications VALUES (1, 'Старое уведомление', false)"))
                def run(sync, direction):
                    class Operations:
                        def execute(self, statement): return sync.execute(text(statement.replace("marketplace.", schema + ".")))
                    migration.op = Operations()
                    getattr(migration, direction)()
                await connection.run_sync(run, "upgrade")
                await connection.run_sync(run, "upgrade")
                assert (await connection.execute(text(f"SELECT message,is_read,href FROM {schema}.notifications"))).one() == ("Старое уведомление", False, None)
                await connection.execute(text(f"UPDATE {schema}.notifications SET href='/deals?deal=specific'"))
                await connection.run_sync(run, "upgrade")
                assert await connection.scalar(text(f"SELECT href FROM {schema}.notifications")) == "/deals?deal=specific"
                await connection.run_sync(run, "downgrade")
                await connection.run_sync(run, "upgrade")
                assert (await connection.execute(text(f"SELECT message,is_read,href FROM {schema}.notifications"))).one() == ("Старое уведомление", False, None)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_legacy_supplier_chat_recovers_exact_recipient_not_the_notifications_list():
    from datetime import datetime, timezone
    from app.notification_links import resolved_notification_href
    buyer, seller, need, request = (uuid.uuid4() for _ in range(4))
    row = (request, need, buyer, seller, seller)
    class DB:
        async def execute(self, statement, args):
            assert 'm.user_id=:uid' in str(statement)
            return SimpleNamespace(all=lambda: [row])
    item = SimpleNamespace(type='info', href='/notifications', message='Новое сообщение по запросу КП: Крепёж',
        created_at=datetime.now(timezone.utc), user_id=uuid.uuid4())
    assert await resolved_notification_href(DB(), item) == f'/seller/inquiries?company={seller}&request={request}'


@pytest.mark.asyncio
async def test_ambiguous_legacy_offer_does_not_open_another_order():
    from datetime import datetime, timezone
    from app.notification_links import resolved_notification_href, message_notification_href
    class DB:
        async def execute(self, *_): return SimpleNamespace(all=lambda: [(uuid.uuid4(),uuid.uuid4()),(uuid.uuid4(),uuid.uuid4())])
    item = SimpleNamespace(type='offer_received',href=None,message='Новое КП',created_at=datetime.now(timezone.utc),user_id=uuid.uuid4())
    assert await resolved_notification_href(DB(), item) == '/needs'
    deal = uuid.uuid4()
    assert message_notification_href(f'Подтверждено по сделке {deal} (запрос {uuid.uuid4()})') == f'/deals?deal={deal}'


@pytest.mark.asyncio
@pytest.mark.parametrize("href", ["/notifications", "/notifications?read=1", "/notifications#notice", "/deals"])
async def test_legacy_self_link_cannot_hide_an_explicit_related_deal(href):
    from app.notification_links import resolved_notification_href
    identifier=uuid.uuid4()
    item=SimpleNamespace(href=href,message=f"Обновлена сделка {identifier}",type="deal_fulfillment_updated")
    assert await resolved_notification_href(None,item)==f"/deals?deal={identifier}"

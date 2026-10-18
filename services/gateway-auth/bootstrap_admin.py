"""Appoint the first operator account locally, without loading sample accounts or companies."""
import argparse
import asyncio
import uuid

from sqlalchemy import select, text
from app.database import SessionLocal
from app.models import AccountAgreement, SecurityEvent, User
from app.api.auth import RULES_VERSION, PRIVACY_VERSION


async def bootstrap(email: str) -> None:
    async with SessionLocal() as db:
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('first-marketplace-admin', 0))"))
        user = await db.scalar(select(User).where(User.email == email))
        if user is None or user.account_status != 'active':
            raise ValueError('Сначала зарегистрируйте действующий аккаунт через сайт.')
        if user.is_marketplace_admin:
            return
        if await db.scalar(select(User.id).where(User.is_marketplace_admin.is_(True)).limit(1)):
            raise ValueError('Администратор уже назначен. Команда предназначена только для первого назначения.')
        agreements = (await db.scalars(select(AccountAgreement).where(AccountAgreement.user_id == user.id))).all()
        if not {('rules', RULES_VERSION), ('privacy', PRIVACY_VERSION)} <= {(row.document,row.version) for row in agreements}:
            raise ValueError('Аккаунт должен подтвердить действующие правила через регистрацию на сайте.')
        user.is_marketplace_admin = True
        db.add(SecurityEvent(id=uuid.uuid4(), event='admin.first_operator', target_id=user.id,
            after_value='administrator', correlation_id=str(uuid.uuid4()), reason='Первое назначение через служебную команду оператора'))
        await db.commit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Первое назначение администратора площадки')
    parser.add_argument('--email', required=True, help='Почта уже зарегистрированного аккаунта')
    args = parser.parse_args()
    try:
        asyncio.run(bootstrap(args.email))
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print('Аккаунт первого администратора готов. Войдите на сайт заново.')

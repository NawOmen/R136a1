"""Self-service account access. Recovery challenges never leave email or hashed storage."""
import asyncio
import hashlib
import hmac
import uuid
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import SessionLocal, get_db
from ..deps import get_current_user
from ..models import AccountRecovery, User
from ..schemas import TokenResponse, UserOut
from ..security import create_access_token, hash_password, verify_password
from ..security_events import audit, throttle, logger

router = APIRouter(prefix="/auth", tags=["account"])
NOTICE = "Если аккаунт существует, письмо с кодом придёт на указанную почту. Код действует 15 минут."


class RecoveryRequest(BaseModel):
    email: EmailStr


class NewPassword(BaseModel):
    password: str = Field(min_length=12, max_length=128)
    @field_validator("password")
    @classmethod
    def password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Пароль слишком длинный. Используйте меньше символов.")
        return value


class PasswordReset(NewPassword):
    code: str = Field(min_length=32, max_length=128)


class PasswordChange(NewPassword):
    current_password: str = Field(max_length=128)


def mail_enabled() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def send_recovery_email(recipient: str, code: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = "Восстановление доступа к ПоРукам"
    message.set_content(f"Код восстановления:\n\n{code}\n\nОткройте страницу восстановления доступа на ПоРукам и вставьте код. Он действует 15 минут и только один раз. Если вы не запрашивали смену пароля, ничего делать не нужно. Никому не сообщайте код.")
    connection = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
    with connection(settings.smtp_host, settings.smtp_port, timeout=8, **({"context": ssl.create_default_context()} if settings.smtp_use_ssl else {})) as smtp:
        if settings.smtp_starttls and not settings.smtp_use_ssl:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def recovery_code(nonce: uuid.UUID) -> str:
    # Persist only a public random nonce and the hash. The mailbox code requires
    # the server secret and can be re-created for durable delivery after restart.
    return hmac.new(settings.jwt_secret.encode(), b"porukam-recovery-v1:" + nonce.bytes, hashlib.sha256).hexdigest()


async def deliver(digest: str, request: Request) -> None:
    async with SessionLocal() as db:
        challenge = await db.scalar(select(AccountRecovery).where(AccountRecovery.token_hash == digest).with_for_update(skip_locked=True))
        now = datetime.now(timezone.utc)
        if not challenge or challenge.delivery_status != "pending" or challenge.used_at or challenge.expires_at <= now:
            return
        user = await db.get(User, challenge.user_id)
        if not user or user.account_status != "active" or user.token_version != challenge.token_version:
            challenge.delivery_status = "cancelled"
            await db.commit()
            return
        code = recovery_code(challenge.nonce)
        if not hmac.compare_digest(hashlib.sha256(code.encode()).hexdigest(), challenge.token_hash):
            challenge.delivery_status = "cancelled"
            await db.commit()
            return
        challenge.delivery_attempts += 1
        try:
            await asyncio.to_thread(send_recovery_email, user.email, code)
            challenge.delivery_status = "sent"
            event = "auth.recovery_sent"
        except Exception:
            challenge.delivery_status = "failed" if challenge.delivery_attempts >= 3 else "pending"
            challenge.next_attempt_at = now + timedelta(seconds=60 * challenge.delivery_attempts)
            event = "auth.recovery_delivery_failed"
            logger.warning("Account recovery email delivery failed")
        await audit(db, request, event, actor=user.id)
        await db.commit()


async def delivery_worker() -> None:
    while True:
        if mail_enabled():
            try:
                async with SessionLocal() as db:
                    now = datetime.now(timezone.utc)
                    pending = (await db.scalars(select(AccountRecovery.token_hash).where(
                        AccountRecovery.delivery_status == "pending", AccountRecovery.next_attempt_at <= now,
                        AccountRecovery.expires_at > now, AccountRecovery.used_at.is_(None)).limit(10))).all()
                for digest in pending:
                    await deliver(digest, Request({"type": "http", "headers": []}))
            except Exception:
                logger.warning("Account recovery delivery worker temporarily unavailable")
        await asyncio.sleep(5)


@router.get("/capabilities")
async def capabilities():
    return {"password_recovery": mail_enabled(), "minimum_password_length": 12}


@router.post("/password/recovery", status_code=202)
async def request_recovery(data: RecoveryRequest, request: Request, tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    await throttle(db, request, str(data.email), "recovery")
    if not mail_enabled():
        raise HTTPException(503, "Восстановление по почте сейчас недоступно. Попробуйте позже или обратитесь в поддержку.")
    user = await db.scalar(select(User).where(User.email == str(data.email)).with_for_update())
    await db.execute(delete(AccountRecovery).where(AccountRecovery.expires_at < datetime.now(timezone.utc)))
    if user is not None and user.account_status == "active":
        nonce = uuid.uuid4()
        code = recovery_code(nonce)
        digest = hashlib.sha256(code.encode()).hexdigest()
        db.add(AccountRecovery(token_hash=digest, nonce=nonce, user_id=user.id,
            token_version=user.token_version, expires_at=datetime.now(timezone.utc) + timedelta(minutes=15)))
        tasks.add_task(deliver, digest, request)
    await audit(db, request, "auth.recovery_requested")
    await db.commit()
    return {"message": NOTICE}


@router.post("/password/reset")
async def reset_password(data: PasswordReset, request: Request, db: AsyncSession = Depends(get_db)):
    digest = hashlib.sha256(data.code.encode()).hexdigest()
    await throttle(db, request, digest, "password_reset")
    challenge = await db.get(AccountRecovery, digest)
    invalid = HTTPException(400, "Код недействителен или истёк. Запросите новое письмо.")
    if challenge is None:
        raise invalid
    user = await db.scalar(select(User).where(User.id == challenge.user_id).with_for_update().execution_options(populate_existing=True))
    challenge = await db.scalar(select(AccountRecovery).where(AccountRecovery.token_hash == digest).with_for_update().execution_options(populate_existing=True))
    if not user or user.account_status != "active" or not challenge or challenge.used_at or challenge.expires_at <= datetime.now(timezone.utc) or challenge.token_version != user.token_version:
        raise invalid
    user.password_hash = hash_password(data.password)
    user.token_version += 1
    challenge.used_at = datetime.now(timezone.utc)
    await audit(db, request, "auth.password_reset", actor=user.id)
    await db.commit()
    return {"message": "Пароль изменён. Войдите с новым паролем. Все прежние сеансы завершены."}


@router.post("/password/change", response_model=TokenResponse)
async def change_password(data: PasswordChange, request: Request, current: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await throttle(db, request, str(current.id), "password_change")
    user = await db.scalar(select(User).where(User.id == current.id).with_for_update().execution_options(populate_existing=True))
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(400, "Текущий пароль указан неверно.")
    if verify_password(data.password, user.password_hash):
        raise HTTPException(422, "Новый пароль должен отличаться от текущего.")
    user.password_hash = hash_password(data.password)
    user.token_version += 1
    await audit(db, request, "auth.password_changed", actor=user.id)
    await db.commit()
    return TokenResponse(user=UserOut.model_validate(user), access_token=create_access_token(user.id, user.token_version))


@router.post("/sessions/end", response_model=TokenResponse)
async def end_other_sessions(request: Request, current: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.id == current.id).with_for_update().execution_options(populate_existing=True))
    user.token_version += 1
    await audit(db, request, "auth.sessions_ended", actor=user.id)
    await db.commit()
    return TokenResponse(user=UserOut.model_validate(user), access_token=create_access_token(user.id, user.token_version))


@router.post("/logout", status_code=204)
async def logout(request: Request, current: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.id == current.id).with_for_update().execution_options(populate_existing=True))
    user.token_version += 1
    await audit(db, request, "auth.logout", actor=user.id)
    await db.commit()

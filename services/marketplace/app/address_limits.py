"""Company-wide address-provider quota, shared by all API workers."""
import uuid

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ADDRESS_REQUESTS_PER_MINUTE = 30


async def reserve_address_request(db: AsyncSession, company_id: uuid.UUID) -> None:
    # No address strings or provider credentials are persisted. A single atomic
    # upsert serializes concurrent requests, including requests from other users.
    await db.execute(text("DELETE FROM marketplace.address_suggestion_limits WHERE bucket < floor(extract(epoch FROM now()) / 60) - 2"))
    count = (await db.execute(text("""
        INSERT INTO marketplace.address_suggestion_limits (company_id, bucket, attempts)
        VALUES (:company_id, floor(extract(epoch FROM now()) / 60), 1)
        ON CONFLICT (company_id, bucket) DO UPDATE
            SET attempts = LEAST(marketplace.address_suggestion_limits.attempts + 1, 1000000)
        RETURNING attempts
    """), {"company_id": company_id})).scalar_one()
    # Count failures too; rollback after a provider outage must not bypass quota.
    await db.commit()
    if count > ADDRESS_REQUESTS_PER_MINUTE:
        raise HTTPException(429, "Слишком много запросов подсказок. Повторите через минуту или введите адрес вручную.",
                            headers={"Retry-After": "60"})

"""S14.02: точка расширения внешних провайдеров (ЭДО, реестр, логистика).

Живой провайдер не подключён: нет договоров, лицензий и доступа, а секреты
в репозитории запрещены. Маршруты отвечают честным статусом not_connected
и ничего не записывают — ложного успеха нет. Файл проверки применимости
или макет накладной не выдаются за подписанный документ.
"""
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import CurrentUser, get_current_user

router = APIRouter(prefix="/integrations", tags=["integrations"])

PROVIDER_SLUGS = ("edo", "registry", "logistics")
PROVIDER_NEEDS = {
    "edo": "Договор с оператором ЭДО, права и выбранные типы документов",
    "registry": "Основание доступа к реестру и разделение проверки и физического аудита",
    "logistics": "Договор с перевозчиком; площадка перевозчиком не является",
}
SLUG_PATTERN = re.compile(r"^[a-z0-9-]{1,40}$")


class ProviderEventIn(BaseModel):
    idempotency_key: uuid.UUID
    event_type: str = Field(min_length=1, max_length=64)
    payload: dict = Field(default_factory=dict)


@router.get("/providers")
async def list_providers(user: CurrentUser = Depends(get_current_user)):
    return [{"slug": slug, "status": "not_connected", "needs": PROVIDER_NEEDS[slug]}
            for slug in PROVIDER_SLUGS]


@router.post("/providers/{provider}/events", status_code=409)
async def receive_provider_event(
    provider: str,
    data: ProviderEventIn,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not SLUG_PATTERN.match(provider) or provider not in PROVIDER_SLUGS:
        raise HTTPException(422, "Неизвестный провайдер интеграции")
    return {"status": "not_connected", "provider": provider,
            "idempotency_key": str(data.idempotency_key),
            "needs": PROVIDER_NEEDS[provider],
            "explanation": "Провайдер не подключён: событие не обработано и не записано"}

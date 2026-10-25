"""Read-only price outlook: Decimal trend calculation and local model commentary.

The model selects reviewed caveats; it never supplies prices or market facts.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from urllib.parse import quote
import json
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_serializer

from .config import settings
from .providers import ModelUnavailable, RoutedProvider
from .security import CurrentUser, get_current_user

router = APIRouter(tags=["price-forecast"])
NOTES = {
    "seller_history": "Оценка опирается только на опубликованные цены этого товара, а не на цены совершённых сделок.",
    "no_market_factors": "Спрос, сезонность, стоимость сырья и будущие решения продавца в расчёт не входят.",
    "limited_sample": "Редкие изменения цены могут не отражать весь рынок. Перед закупкой запросите условия у продавца.",
}


class HistoryPoint(BaseModel):
    date: date
    average_unit_price_rub: Decimal = Field(gt=0, max_digits=24, decimal_places=12, allow_inf_nan=False)
    offers_count: int = Field(ge=1)


class ForecastIn(BaseModel):
    product_id: uuid.UUID


class ForecastPoint(BaseModel):
    date: date
    price_rub: Decimal

    @field_serializer("price_rub")
    def exact_price(self, value):
        return str(value)


class ForecastOut(BaseModel):
    contract_version: Literal["price-forecast-1"] = "price-forecast-1"
    method: Literal["linear-trend-1"] = "linear-trend-1"
    product_id: uuid.UUID
    status: Literal["ready", "insufficient_data", "stale_data", "unstable_data"]
    observations: int
    history_from: date | None = None
    history_to: date | None = None
    points: list[ForecastPoint] = Field(default_factory=list)
    ai_status: Literal["not_requested", "completed", "unavailable"] = "not_requested"
    notes: list[str] = Field(default_factory=list)


class Commentary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note_ids: list[Literal["seller_history", "no_market_factors", "limited_sample"]] = Field(min_length=1, max_length=3)


def calculate(product_id: uuid.UUID, history: list[HistoryPoint], today: date) -> ForecastOut:
    # Only a recent, comparable daily series; never extend stale or future data.
    daily = {p.date: p for p in history if today - timedelta(days=90) <= p.date <= today}
    series = [daily[day] for day in sorted(daily)]
    result = ForecastOut(product_id=product_id, status="insufficient_data", observations=len(series),
                         history_from=series[0].date if series else None, history_to=series[-1].date if series else None)
    if len(series) < 6 or (series[-1].date - series[0].date).days < 14:
        result.notes = ["Для оценки нужны цены минимум за шесть разных дней и период от двух недель. История не дополняется вымышленными наблюдениями."]
        return result
    if (today - series[-1].date).days > 14:
        result.status = "stale_data"
        result.notes = ["Последняя цена опубликована больше двух недель назад. Для оценки нужны свежие данные."]
        return result
    xs = [Decimal((p.date - series[0].date).days) for p in series]
    ys = [p.average_unit_price_rub for p in series]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / sum((x - mean_x) ** 2 for x in xs)
    predictions = [(today + timedelta(days=days), mean_y + slope * (Decimal((today - series[0].date).days + days) - mean_x)) for days in (7, 14, 30)]
    # Refuse unsupported extrapolation instead of clipping it into a plausible price.
    if any(value < Decimal("0.005") or abs(value / ys[-1] - 1) > Decimal("0.5") for _, value in predictions):
        result.status = "unstable_data"
        result.notes = ["Цены менялись слишком резко для устойчивой оценки. Запросите актуальные условия у производителя."]
        return result
    result.status = "ready"
    result.points = [ForecastPoint(date=day, price_rub=value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) for day, value in predictions]
    result.notes = ["Расчётный тренд, не гарантия будущей цены. Цена в каталоге и условия сделки не изменяются.", NOTES["seller_history"]]
    return result


async def load_history(product_id: uuid.UUID) -> list[HistoryPoint]:
    # Fixed service origin; the client cannot provide a URL or private company data.
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            product = await client.get(f"{settings.marketplace_base_url}/api/v1/products/{product_id}/detail")
            if product.status_code == 404:
                raise HTTPException(404, "Товар не найден")
            product.raise_for_status()
            category = product.json()["category"]
            response = await client.get(f"{settings.marketplace_base_url}/api/v1/price-index/{quote(category, safe='')}", params={"product_id": str(product_id)})
            response.raise_for_status()
            return [HistoryPoint.model_validate(row) for row in response.json()]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "История цен временно недоступна. Повторите попытку.") from exc


@router.post("/api/v1/price-forecasts", response_model=ForecastOut)
async def price_forecast(data: ForecastIn, request: Request, user: CurrentUser = Depends(get_current_user)):
    del user
    history = await load_history(data.product_id)
    from datetime import datetime, timezone
    result = calculate(data.product_id, history, datetime.now(timezone.utc).date())
    if result.status != "ready":
        return result
    provider = getattr(request.app.state, "llm_provider", None) or RoutedProvider()
    try:
        selection = await provider.local.structured(
            "Проанализируй ряд цен и выбери note_ids с наиболее важными ограничениями оценки. "
            "Только JSON по схеме. Не рассчитывай цену и не добавляй рыночные факты. "
            "seller_history: только цены продавца; no_market_factors: нет внешних факторов; limited_sample: редкие наблюдения.",
            json.dumps({"observations": [p.model_dump(mode="json") for p in history if result.history_from <= p.date <= result.history_to][-91:], "forecast": result.model_dump(mode="json")}, ensure_ascii=False),
            Commentary,
        )
        selected = Commentary.model_validate(selection)
        result.ai_status = "completed"
        result.notes.extend(NOTES[key] for key in dict.fromkeys(selected.note_ids) if NOTES[key] not in result.notes)
    except (ModelUnavailable, ValueError):
        result.ai_status = "unavailable"
        result.notes.append("ИИ-анализ временно недоступен. Показан только программный расчёт тренда.")
    return result

from datetime import date, timedelta
from decimal import Decimal
import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.price_forecast import Commentary, HistoryPoint, calculate, router
from app.security import CurrentUser, get_current_user
from app.providers import ModelUnavailable

TODAY = date(2026, 10, 25)
PRODUCT = uuid.uuid4()


def history(prices=None, age=0):
    prices = prices or [100, 101, 102, 103, 104, 105, 106]
    return [HistoryPoint(date=TODAY - timedelta(days=42 - i * 7 + age), average_unit_price_rub=Decimal(value), offers_count=1) for i, value in enumerate(prices)]


def test_forecast_uses_calendar_spacing_and_decimal_rounding():
    result = calculate(PRODUCT, history(), TODAY)
    assert result.status == "ready"
    assert [p.price_rub for p in result.points] == [Decimal("107.00"), Decimal("108.00"), Decimal("110.29")]
    assert result.points[-1].date == TODAY + timedelta(days=30)
    assert result.ai_status == "not_requested"


def test_sparse_stale_and_unstable_series_never_invent_predictions():
    assert calculate(PRODUCT, history()[:2], TODAY).status == "insufficient_data"
    assert calculate(PRODUCT, history(age=20), TODAY).status == "stale_data"
    assert calculate(PRODUCT, history([106, 90, 70, 50, 30, 20, 1]), TODAY).status == "unstable_data"
    assert not calculate(PRODUCT, history()[:2], TODAY).points


def test_future_and_old_points_are_excluded_and_same_day_not_overweighted():
    rows = history()
    rows += [HistoryPoint(date=TODAY + timedelta(days=1), average_unit_price_rub=99999, offers_count=1),
             HistoryPoint(date=TODAY - timedelta(days=150), average_unit_price_rub=99999, offers_count=1)]
    rows += [rows[-3]]
    result = calculate(PRODUCT, rows, TODAY)
    assert result.observations == 7
    assert result.points[0].price_rub == Decimal("107.00")


@pytest.mark.asyncio
@pytest.mark.parametrize("model_available", [True, False, "injected_price"])
async def test_api_model_cannot_supply_prices_and_fallback_is_explicit(monkeypatch, model_available):
    app = FastAPI()
    app.include_router(router)
    async def authenticated():
        return CurrentUser(uuid.uuid4())
    app.dependency_overrides[get_current_user] = authenticated
    async def load(product_id):
        assert product_id == PRODUCT
        from datetime import datetime, timezone
        shift = datetime.now(timezone.utc).date() - TODAY
        return [p.model_copy(update={"date": p.date + shift}) for p in history()]
    monkeypatch.setattr("app.price_forecast.load_history", load)
    class Provider:
        @property
        def local(self):
            return self
        async def structured(self, system, prompt, schema):
            assert schema is Commentary
            assert "цены" in prompt
            if not model_available:
                raise ModelUnavailable("Недоступно")
            if model_available == "injected_price":
                return {"note_ids":["no_market_factors"], "price_rub":"1"}
            return Commentary(note_ids=["no_market_factors"])
    app.state.llm_provider = Provider()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/price-forecasts", json={"product_id": str(PRODUCT)})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["points"][0]["price_rub"] == "107.00"
    assert result["ai_status"] == ("completed" if model_available is True else "unavailable")
    assert result["contract_version"] == "price-forecast-1"


@pytest.mark.asyncio
async def test_public_history_reader_preserves_product_admission_and_encoded_category(monkeypatch):
    from httpx import Request, Response
    from app.price_forecast import load_history
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, **kwargs):
            if url.endswith("/detail"):
                return Response(404, request=Request("GET", url))
            pytest.fail("Hidden product history must not be queried")
    monkeypatch.setattr("app.price_forecast.httpx.AsyncClient", Client)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await load_history(PRODUCT)
    assert error.value.status_code == 404

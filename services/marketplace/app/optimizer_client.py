from datetime import date
from .money import exact_json, money_values

import httpx
from fastapi import HTTPException, status

from .config import settings


async def optimize_allocations(payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.optimizer_timeout_seconds) as client:
            response = await client.post(
                f"{settings.optimizer_url.rstrip('/')}/api/v2/optimize/allocations",
                json=exact_json(payload), headers={"X-Optimizer-Token": settings.optimizer_token},
            )
            response.raise_for_status()
            return money_values(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Оптимизатор временно недоступен",
        ) from exc


async def evaluate_coalition(payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.optimizer_timeout_seconds) as client:
            response = await client.post(
                f"{settings.optimizer_url.rstrip('/')}/api/v2/optimize/coalition",
                json=exact_json(payload), headers={"X-Optimizer-Token": settings.optimizer_token},
            )
            response.raise_for_status()
            return money_values(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Оптимизатор временно недоступен",
        ) from exc


async def calculate_resilience(payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.optimizer_timeout_seconds) as client:
            response = await client.post(
                f"{settings.optimizer_url.rstrip('/')}/api/v2/optimize/resilience",
                json=exact_json(payload), headers={"X-Optimizer-Token": settings.optimizer_token},
            )
            response.raise_for_status()
            return money_values(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Оптимизатор устойчивости временно недоступен",
        ) from exc


def days_until(target: date) -> int:
    return max(1, (target - date.today()).days)

from datetime import date

import httpx
from fastapi import HTTPException, status

from .config import settings


async def optimize_allocations(payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.optimizer_timeout_seconds) as client:
            response = await client.post(
                f"{settings.optimizer_url.rstrip('/')}/api/v1/optimize/allocations",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Оптимизатор временно недоступен: {exc}",
        ) from exc


async def evaluate_coalition(payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.optimizer_timeout_seconds) as client:
            response = await client.post(
                f"{settings.optimizer_url.rstrip('/')}/api/v1/optimize/coalition",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Оптимизатор временно недоступен: {exc}",
        ) from exc


async def calculate_resilience(payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.optimizer_timeout_seconds) as client:
            response = await client.post(
                f"{settings.optimizer_url.rstrip('/')}/api/v1/optimize/resilience",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Оптимизатор устойчивости временно недоступен: {exc}",
        ) from exc


def days_until(target: date) -> int:
    return max(1, (target - date.today()).days)

"""Marketplace Service — каталог, потребности, предложения и сделки.

На этапе 2 сервис поднимается с минимальной точкой здоровья.
Схема БД `marketplace`, каталог, карточки потребностей и предложения
появятся на этапе 3.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Marketplace Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/health")
async def api_health() -> dict:
    return {"service": "marketplace", "status": "ok"}

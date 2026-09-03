from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import addresses, capacity, documents, health, market, needs, notifications, offers, products, production, resilience, stage8, stage9, trust
from .config import settings

app = FastAPI(title="Marketplace Service", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(addresses.router, prefix="/api/v1")
app.include_router(production.router, prefix="/api/v1")
app.include_router(products.router, prefix="/api/v1")
app.include_router(capacity.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(needs.router, prefix="/api/v1")
app.include_router(offers.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(market.router, prefix="/api/v1")
app.include_router(resilience.router, prefix="/api/v1")
app.include_router(trust.router, prefix="/api/v1")
app.include_router(stage8.router, prefix="/api/v1")
app.include_router(stage9.router, prefix="/api/v1")

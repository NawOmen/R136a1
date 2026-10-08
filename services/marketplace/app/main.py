from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    addresses,
    agent_scorecard,
    capacity,
    catalog_import,
    commerce,
    category_profiles,
    category_editor,
    physical_quantities,
    documents,
    health,
    market,
    needs,
    notifications,
    offers,
    products,
    production,
    resilience,
    stage8,
    stage9,
    trust,
)
from .config import settings

app = FastAPI(title="Marketplace Service", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(addresses.router, prefix="/api/v1")
app.include_router(production.router, prefix="/api/v1")
app.include_router(products.router, prefix="/api/v1")
app.include_router(catalog_import.router, prefix="/api/v1")
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
app.include_router(agent_scorecard.router, prefix="/api/v1")

app.include_router(commerce.router, prefix="/api/v1")

app.include_router(category_profiles.router, prefix="/api/v1")

app.include_router(category_editor.router, prefix="/api/v1")

app.include_router(physical_quantities.router, prefix="/api/v2")

from .api import packaging_conversion
app.include_router(packaging_conversion.router, prefix="/api/v1")

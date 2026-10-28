import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    addresses,
    agent_scorecard,
    capacity,
    catalog_import,
    coalition_changes,
    commerce,
    category_profiles,
    category_editor,
    physical_quantities,
    documents,
    health,
    integration_providers,
    market,
    needs,
    notifications,
    offers,
    products,
    production,
    resilience,
    resource_reconciliation,
    stage8,
    stage9,
    trust,
)
from .config import settings

@asynccontextmanager
async def lifespan(app):
    from .document_lifecycle import lifecycle_worker
    worker = asyncio.create_task(lifecycle_worker())
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


app = FastAPI(title="Marketplace Service", version="0.2.0", lifespan=lifespan)

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
app.include_router(coalition_changes.router, prefix="/api/v1")
app.include_router(integration_providers.router, prefix="/api/v1")
app.include_router(resilience.router, prefix="/api/v1")
app.include_router(resource_reconciliation.router, prefix="/api/v1")
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

# v3 exposes exact decimal strings; v1/v2 keep their numeric wire contracts.
from .money import MoneyWireMiddleware, wire
from decimal import Decimal
from fastapi.encoders import ENCODERS_BY_TYPE
ENCODERS_BY_TYPE[Decimal] = wire
app.add_middleware(MoneyWireMiddleware)
for exact_router in (addresses, production, products, catalog_import, capacity, documents, needs, offers,
                     notifications, market, coalition_changes, integration_providers, resilience, resource_reconciliation, trust, stage8, stage9, agent_scorecard, commerce,
                     category_profiles, category_editor, packaging_conversion):
    app.include_router(exact_router.router, prefix='/api/v3')
app.include_router(physical_quantities.router, prefix='/api/v3/physical')

from .api import fulfillment
app.include_router(fulfillment.router, prefix="/api/v3")

from .api import quality_evidence
app.include_router(quality_evidence.router, prefix="/api/v3")

from .api import supplier_requests
app.include_router(supplier_requests.router, prefix="/api/v3")

from .api import order_export
app.include_router(order_export.router, prefix="/api/v3")

from .denials import BusinessDenied, handle_denial
app.add_exception_handler(BusinessDenied, handle_denial)

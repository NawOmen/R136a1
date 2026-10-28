from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import settings
from .price_forecast import router as price_forecast_router
from .procurement_assistant import router as procurement_assistant_router

app = FastAPI(title="ПоРукам — LLM Gateway", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(price_forecast_router)
app.include_router(procurement_assistant_router)

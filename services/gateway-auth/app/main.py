from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin, auth, companies, health
from .config import settings
from .security_events import correlation, logger
import json
from datetime import datetime, timezone
from fastapi import Request

app = FastAPI(title="Gateway Auth", version="1.0.0")


@app.middleware("http")
async def security_log(request: Request, call_next):
    request_id = correlation(request)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    if response.status_code in (401, 403, 429):
        logger.warning(json.dumps({"event": "auth.denied", "status": response.status_code,
                                   "time": datetime.now(timezone.utc).isoformat(),
                                   "correlation_id": request_id}))
    return response

# Только явно настроенные origins. Для сети используется same-origin HTTPS-прокси.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(companies.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")

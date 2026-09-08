from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin, auth, companies, health
from .config import settings

app = FastAPI(title="Gateway Auth", version="1.0.0")

# Для прототипа разрешаем CORS с фронтенда и инструментов разработки.
# Список явных origins дополняется regex: любой адрес приватной локальной сети
# (localhost, 10.x, 172.16-31.x, 192.168.x) разрешён автоматически — при смене
# IP компьютера в локальной сети ничего перенастраивать не нужно.
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

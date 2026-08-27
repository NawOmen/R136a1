from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin, auth, companies, health

app = FastAPI(title="Gateway Auth", version="1.0.0")

# Для прототипа разрешаем CORS с фронтенда и инструментов разработки.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(companies.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")

"""Published rules are request-local, persistent and identical across workers."""
from contextlib import asynccontextmanager
from sqlalchemy import select
from .models import CategoryRegistryRevision
from .category_registry import registry_context


@asynccontextmanager
async def current_registry_context(db):
    revision=await db.scalar(select(CategoryRegistryRevision).order_by(CategoryRegistryRevision.sequence.desc()).limit(1))
    with registry_context(revision.registry if revision else None):
        yield

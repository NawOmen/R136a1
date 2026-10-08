"""Explicit profile adoption never rewrites active needs or commercial records."""
import uuid
from copy import deepcopy
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..deps import CurrentUser, get_current_user, require_company_admin, require_company_seller, require_company_buyer
from ..models import Product, Need
from ..category_registry import resolve_category, registry_snapshot
from ..category_profile_revision import revision_preview
from ..category_characteristics import validate_profile_values
from ..trust import record_human_approval

router = APIRouter(tags=['category-profiles'])


class ProfileAdoptionIn(BaseModel):
    approved: Literal[True]
    expected_specification_hash: str = Field(min_length=64,max_length=64)
    expected_snapshot_hash: str = Field(min_length=64,max_length=64)
    expected_current_hash: str = Field(min_length=64,max_length=64)
    expected_revision: int | None = Field(default=None,gt=0)


@router.get('/categories/profiles')
async def category_profiles(db: AsyncSession=Depends(get_db)):
    return registry_snapshot()


async def owned_record(kind,identifier,user,db, *, lock=False):
    model = Product if kind == 'products' else Need
    query = select(model).where(model.id == identifier)
    if lock:query=query.with_for_update()
    record = await db.scalar(query)
    if record is None:raise HTTPException(404,'Запись не найдена')
    permission = require_company_seller if kind == 'products' else require_company_buyer
    await permission(record.company_id,user,db)
    return record


@router.get('/{kind}/{identifier}/category-profile')
async def profile_preview(kind: Literal['products','needs'], identifier: uuid.UUID,
                          user: CurrentUser=Depends(get_current_user),db: AsyncSession=Depends(get_db)):
    record=await owned_record(kind,identifier,user,db)
    return revision_preview(record)


@router.post('/{kind}/{identifier}/category-profile/adopt')
async def adopt_profile(kind: Literal['products','needs'],identifier: uuid.UUID,data: ProfileAdoptionIn,
                        user: CurrentUser=Depends(get_current_user),db: AsyncSession=Depends(get_db)):
    record=await owned_record(kind,identifier,user,db,lock=True)
    await require_company_admin(record.company_id,user,db)
    if (kind == 'products' and record.is_published) or (kind == 'needs' and record.status != 'draft'):
        raise HTTPException(409,'Правила принимаются в черновике. Согласованные обязательства сохраняют прежнюю версию')
    if kind == 'needs' and data.expected_revision != record.revision:
        raise HTTPException(409,'Потребность изменилась. Обновите сравнение правил')
    preview=revision_preview(record)
    if preview['expected_specification_hash'] != data.expected_specification_hash or preview['expected_snapshot_hash'] != data.expected_snapshot_hash or preview['expected_current_hash'] != data.expected_current_hash:
        raise HTTPException(409,'Правила или спецификация изменились. Обновите сравнение')
    if preview['current'] is None:raise HTTPException(422,'Сначала выберите раздел и подкатегорию каталога')
    errors=validate_profile_values(record.category,record.subcategory,record.characteristics,
                                   require_product_fields=kind=='products')
    if errors:raise HTTPException(422,'; '.join(errors))
    if preview['state']=='current':return preview
    previous=deepcopy(record.category_profile)
    record.category_profile=preview['current']
    if kind=='products':record.quantity_conversion=None
    if kind=='needs':record.revision+=1
    await record_human_approval(db,action='adopt_category_profile',entity_type=kind[:-1],entity_id=record.id,
        actor_user_id=user.id,actor_company_id=record.company_id,permission='company_admin+owner',decision='approved',
        payload={'previous':previous,'current':deepcopy(record.category_profile),'characteristics':deepcopy(record.characteristics),
                 'category':record.category,'subcategory':record.subcategory,'revision':getattr(record,'revision',None)},
        source_refs=[{'type':kind[:-1],'id':str(record.id)}],
        explanation='Администратор компании просмотрел изменения и явно принял новую версию правил для черновика.')
    await db.commit()
    return revision_preview(record)

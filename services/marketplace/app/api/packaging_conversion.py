import uuid
from copy import deepcopy
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..deps import CurrentUser,get_current_user,require_company_admin,require_company_seller
from ..models import Product
from ..packaging_conversion import packaging_definition,packaging_equivalent
from ..trust import record_human_approval

router=APIRouter(tags=['packaging-conversion'])


class PackagingReviewIn(BaseModel):
    target_unit:str=Field(min_length=1,max_length=32)
    factor:int=Field(gt=0,le=2147483647,strict=True)
    expected_specification_hash:str|None=Field(default=None,min_length=64,max_length=64)
    expected_review_hash:str|None=Field(default=None,min_length=64,max_length=64)
    approved:bool=False


@router.post('/products/{identifier}/packaging-conversion')
async def review_packaging(identifier:uuid.UUID,data:PackagingReviewIn,user:CurrentUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    product=await db.scalar(select(Product).where(Product.id==identifier).with_for_update())
    if product is None:raise HTTPException(404,'Товар не найден')
    await require_company_seller(product.company_id,user,db)
    await require_company_admin(product.company_id,user,db)
    try:definition=packaging_definition(product,data.target_unit,data.factor)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    if not data.approved:return definition
    if data.expected_specification_hash!=definition['specification_hash']:raise HTTPException(409,'Спецификация изменилась; обновите проверку коэффициента')
    if data.expected_review_hash != definition['review_hash']:raise HTTPException(409,'Коэффициент или единица изменились; заново проверьте пересчёт')
    previous=deepcopy(product.quantity_conversion)
    product.quantity_conversion=definition
    await record_human_approval(db,action='packaging_conversion_confirmed',entity_type='product',entity_id=product.id,
        actor_user_id=user.id,actor_company_id=product.company_id,permission='company_admin+seller',decision='approved',
        payload={'previous':previous,'current':deepcopy(definition),'category_profile':deepcopy(product.category_profile)},
        explanation='Продавец явно подтвердил содержимое упаковки этой спецификации; единица сделки не заменяется автоматически')
    await db.commit()
    return definition


@router.get('/products/{identifier}/packaging-equivalent')
async def equivalent(identifier:uuid.UUID,quantity:int=1,user:CurrentUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    product=await db.get(Product,identifier)
    if product is None:raise HTTPException(404,'Товар не найден')
    await require_company_seller(product.company_id,user,db)
    try:return packaging_equivalent(product,quantity)
    except ValueError as exc:raise HTTPException(409,str(exc)) from None

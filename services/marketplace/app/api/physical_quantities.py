"""Versioned fractional input; v1 retains integer quantities and stored units."""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..deps import CurrentUser,get_current_user,require_company_admin,require_company_seller,require_company_buyer
from ..schemas import ProductIn,ProductPatch,NeedIn,NeedEditIn,ProductOut,NeedOut
from ..physical_quantities import normalize_physical
from ..category_units import order_unit
from ..resources import lock_company
from ..trust import record_human_approval
from ..requirements import lock_specification_edit
from ..models import Product,Need
from .products import create_product,update_product
from .needs import create_need,edit_need,preview_need_edit

router=APIRouter(tags=['physical-quantities'])


def normalized(kind,raw,model):
    try:
        values,_=normalize_physical(kind,raw)
        data = model.model_validate(values)
        if kind == 'need':
            data._physical_quantity_input = {"value": str(raw.get("volume_units", "")), "unit": order_unit(raw.get("characteristics", {}))}
        return data
    except (ValueError,ValidationError,TypeError,KeyError) as exc:
        raise HTTPException(422,str(exc)) from None


async def approve_conversion(kind,raw,company_id,user,db):
    _,preview=normalize_physical(kind,raw)
    if preview['factor']==1:return
    permission=require_company_seller if kind=='product' else require_company_buyer
    await permission(company_id,user,db)
    await require_company_admin(company_id,user,db)
    await record_human_approval(db,action='physical_quantity_conversion',entity_type='company',entity_id=company_id,
        actor_user_id=user.id,actor_company_id=company_id,permission='company_admin+owner',decision='approved',
        payload={'kind':kind,'input':{key:raw[key] for key in ('characteristics','volume_units','moq_units','stock_units','price_rub','price_tiers') if key in raw},'conversion':preview},
        explanation='Владелец явно подтвердил точный пересчёт физического объёма и цены в меньшую единицу; округление не выполнялось')


@router.post('/physical-quantities/preview')
async def physical_preview(raw:dict,db:AsyncSession=Depends(get_db)):
    kind=raw.get('kind')
    if kind not in {'product','need'}:raise HTTPException(422,'Выберите товар или потребность')
    try:
        values,preview=normalize_physical(kind,raw.get('values',{}),require_approval=False)
        return {'normalized':values,'conversion':preview}
    except (ValueError,TypeError,KeyError) as exc:raise HTTPException(422,str(exc)) from None


@router.post('/companies/{company_id}/products',response_model=ProductOut,status_code=201)
async def create_physical_product(company_id:uuid.UUID,raw:dict,user:CurrentUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    data=normalized('product',raw,ProductIn)
    await approve_conversion('product',raw,company_id,user,db)
    return await create_product(company_id,data,user,db)


@router.patch('/products/{product_id}',response_model=ProductOut)
async def edit_physical_product(product_id:uuid.UUID,raw:dict,user:CurrentUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    if 'characteristics' not in raw:raise HTTPException(422,'Для физического пересчёта передайте полную спецификацию; обычный PATCH доступен в v1')
    data=normalized('product',raw,ProductPatch)
    product=await db.get(Product,product_id)
    if product is None:raise HTTPException(404,'Товар не найден')
    await require_company_seller(product.company_id, user, db)
    await require_company_admin(product.company_id, user, db)
    # Read the unit under the same transaction lock used by v1 updates.
    # A concurrent unit change must not turn this into a partial conversion.
    await lock_company(db, product.company_id)
    await db.refresh(product)
    if order_unit(data.characteristics) != order_unit(product.characteristics):
        required = {'price_rub', 'moq_units', 'stock_units', 'price_tiers'}
        if not required.issubset(raw):
            raise HTTPException(422, 'При смене единицы передайте цену, минимальный заказ, остаток '
                                'и все ценовые ступени в исходной единице пересчёта. '
                                'Если ступеней нет, передайте пустой список; неизвестный остаток — null')
    await approve_conversion('product',raw,product.company_id,user,db)
    return await update_product(product_id,data,user,db)


@router.post('/needs',response_model=NeedOut,status_code=201)
async def create_physical_need(raw:dict,user:CurrentUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    data=normalized('need',raw,NeedIn)
    await approve_conversion('need',raw,data.company_id,user,db)
    return await create_need(data,user,db)


@router.put('/needs/{need_id}',response_model=NeedOut)
async def edit_physical_need(need_id:uuid.UUID,raw:dict,user:CurrentUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    data=normalized('need',raw,NeedEditIn)
    need=await db.get(Need,need_id)
    if need is None:raise HTTPException(404,'Потребность не найдена')
    # Conversion writes the audit chain: take the edit boundary before that
    # lock as well as before the Need row lock in the shared handler.
    await lock_specification_edit(db)
    await approve_conversion('need',raw,need.company_id,user,db)
    return await edit_need(need_id,data,user,db)


@router.post('/needs/{need_id}/edit-preview')
async def preview_physical_need(need_id:uuid.UUID,raw:dict,user:CurrentUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    data=normalized('need',raw,NeedEditIn)
    return await preview_need_edit(need_id,data,user,db)

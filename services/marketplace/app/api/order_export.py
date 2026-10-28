import json
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..deps import CurrentUser, get_current_user
from ..order_export import commerceml, order_csv, csv_bytes
from ..category_units import order_unit
from .commerce import party
from .supplier_requests import buyer_need

router = APIRouter(tags=["order-export"])


@router.get("/deals/{deal_id}/export-1c")
async def export_order(deal_id: uuid.UUID, company_id: uuid.UUID, format: Literal["xml", "csv"] = "xml", user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deal = await party(db, deal_id, company_id, user)
    companies = []
    for cid in (deal.buyer_company_id, deal.seller_company_id):
        row = (await db.execute(text("SELECT id, full_name, display_name, legal_form, inn, kpp, legal_address, country FROM auth.companies WHERE id=:id"), {"id": cid})).mappings().first()
        if not row or row["country"] != "RU":
            raise HTTPException(409, "Экспорт доступен только для российских компаний")
        companies.append(dict(row))
    content = (commerceml if format == "xml" else order_csv)(deal, *companies)
    return Response(content, media_type="application/xml" if format == "xml" else "text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="porukam-order-{deal.id}.{format}"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Export-Contract": "porukam-1c-1"})


@router.get("/needs/{need_id}/specification.csv")
async def export_specification(need_id: uuid.UUID, company_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    need = await buyer_need(db, need_id, company_id, user)
    rows = [["Категория", "Подкатегория", "Количество", "Единица", "Срок поставки", "Характеристики", "Версия"],
            [need.category, need.subcategory or "", need.volume_units, order_unit(need.characteristics), need.deadline_date.strftime("%d.%m.%y"), json.dumps(need.characteristics, ensure_ascii=False), need.revision]]
    return Response(csv_bytes(rows), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="porukam-specification-{need.id}-v{need.revision}.csv"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

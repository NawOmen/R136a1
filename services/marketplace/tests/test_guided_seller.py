from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from conftest import make_user, make_company, make_token
from app.models import ProductionProfile, CapabilityPassport, Product, CapacityEntry


async def test_seller_guidance_follows_missing_prerequisite_and_stock_does_not_require_capacity(client, db_session, monkeypatch):
    user = await make_user(db_session)
    company = await make_company(db_session,user,can_buy=False,can_sell=True,verified=True)
    headers={"Authorization": f"Bearer {make_token(user)}"}
    async def step():
        r=await client.get(f'/api/v3/next-step?company_id={company}&mode=sell',headers=headers)
        assert r.status_code == 200,r.text
        return r.json()['href']
    assert await step() == '/seller/profile'
    db_session.add(ProductionProfile(company_id=company,production_site_address='ул. Синтетическая, д. 1',region='Москва'))
    await db_session.commit()
    assert await step() == '/seller/passport'
    passport=CapabilityPassport(company_id=company,details={'business_kind':'manufacturer','category_scopes':[{'category_id':'packaging.boxes','unit':'шт','min_units':1}]})
    db_session.add(passport);await db_session.commit()
    assert await step() == '/seller/products'
    product=Product(company_id=company,name='Синтетический короб',category='Упаковка и тара',subcategory='Коробки',
        characteristics={'unit':'шт','material':'гофрокартон','dimensions_mm':'400×300×300'},price_rub=Decimal('10'),moq_units=1,lead_time_days=5,is_published=False)
    db_session.add(product);await db_session.commit()
    blocked=True
    async def admission(*args,**kwargs):return SimpleNamespace(supported=True,blocking_open=int(blocked))
    monkeypatch.setattr('app.api.stage9.company_admission',admission)
    assert await step() == '/seller/documents'
    blocked=False
    assert await step() == '/seller/products'
    product.is_published=True;await db_session.commit()
    assert await step() == '/seller/capacity'
    passport.details={**passport.details,'business_kind':'stock_supplier'};await db_session.commit()
    assert await step() == '/seller/products'
    product.stock_units=25;await db_session.commit()
    assert await step() == '/seller/requests'
    passport.details={**passport.details,'business_kind':'both'};await db_session.commit()
    assert await step() == '/seller/requests'
    product.stock_units=0;await db_session.commit()
    assert await step() == '/seller/capacity'
    db_session.add(CapacityEntry(company_id=company,date=datetime.now(timezone.utc).date(),available_units=50))
    await db_session.commit()
    assert await step() == '/seller/requests'

import uuid
from datetime import date, timedelta
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from app.models import Need, Deal, Offer, Product, SupplierRequestMessage, HumanApprovalRecord
from conftest import make_company, make_token, make_user


@pytest.fixture
async def workspace(client, db_session):
    buyer_user, seller_user, other_user = [await make_user(db_session) for _ in range(3)]
    buyer = await make_company(db_session, buyer_user, can_buy=True, can_sell=False)
    seller = await make_company(db_session, seller_user, can_buy=False, can_sell=True)
    other = await make_company(db_session, other_user)
    need = Need(company_id=buyer, category="Упаковка и тара", subcategory="Бумажные стаканы", characteristics={"unit": "шт", "material": "бумага"},
        volume_units=100, budget_rub=Decimal("9999"), deadline_date=date.today()+timedelta(days=30), status="open_for_offers")
    product = Product(company_id=seller, name="Стакан из бумаги", category=need.category, subcategory=need.subcategory,
        characteristics=need.characteristics, price_rub=Decimal("7"), moq_units=10, lead_time_days=5, is_published=True)
    db_session.add_all([need, product]); await db_session.commit()
    headers = [{"Authorization": f"Bearer {make_token(uid)}"} for uid in (buyer_user, seller_user, other_user)]
    response = await client.post(f"/api/v3/needs/{need.id}/supplier-requests", json={"company_id": str(buyer), "seller_company_id": str(seller), "expected_need_revision": 1}, headers=headers[0])
    assert response.status_code == 201, response.text
    return {"buyer": buyer, "seller": seller, "other": other, "headers": headers, "need": need, "row": response.json()}


def update(w, **changes):
    return {"company_id": str(w["buyer"]), "expected_revision": w["row"]["revision"], "status": "sent", "human_approved": True, **changes}


async def mark_sent(client, w):
    response = await client.patch(f'/api/v3/supplier-requests/{w["row"]["id"]}', json=update(w), headers=w["headers"][0])
    assert response.status_code == 200, response.text
    w["row"] = response.json()


async def test_draft_is_private_idempotent_and_has_no_budget_or_source_files(client, workspace):
    w=workspace; row=w["row"]; path=f'/api/v3/supplier-requests/{row["id"]}'
    assert row["status"] == "draft" and "budget_rub" not in row["specification"]
    again=await client.post(f'/api/v3/needs/{w["need"].id}/supplier-requests', json={"company_id":str(w["buyer"]),"seller_company_id":str(w["seller"]),"expected_need_revision":1},headers=w["headers"][0])
    assert again.json()["id"] == row["id"]
    for company, headers in [(w["seller"],w["headers"][1]),(w["other"],w["headers"][2])]:
        for suffix in ("context","messages","files"):
            assert (await client.get(f'{path}/{suffix}?company_id={company}',headers=headers)).status_code==404
    inbox=await client.get(f'/api/v3/supplier-requests?company_id={w["seller"]}&role=seller',headers=w["headers"][1])
    assert inbox.json()==[]
    suppliers=await client.get(f'/api/v3/needs/{w["need"].id}/suppliers?company_id={w["buyer"]}',headers=w["headers"][0])
    assert next(r for r in suppliers.json() if r["company_id"]==str(w["seller"]))["relevant"] is True


async def test_human_sent_conversation_replays_and_board_selection_is_not_deal(client, workspace, db_session):
    w=workspace; path=f'/api/v3/supplier-requests/{w["row"]["id"]}'
    payload={"company_id":str(w["buyer"]),"expected_revision":1,"message":"Просим КП на 100 бумажных стаканов.","request_key":str(uuid.uuid4())}
    assert (await client.post(path+'/messages',json=payload,headers=w["headers"][0])).status_code==422
    payload["human_approved"]=True
    first=await client.post(path+'/messages',json=payload,headers=w["headers"][0]); assert first.status_code==201,first.text
    repeat=await client.post(path+'/messages',json=payload,headers=w["headers"][0]); assert repeat.json()["id"]==first.json()["id"]
    changed=await client.post(path+'/messages',json={**payload,"message":"Другой текст"},headers=w["headers"][0]); assert changed.status_code==409
    reply=await client.post(path+'/messages',json={**payload,"company_id":str(w["seller"]),"expected_revision":2,"request_key":str(uuid.uuid4()),"message":"Цена 7 рублей, срок 5 дней."},headers=w["headers"][1]); assert reply.status_code==201,reply.text
    rows=await client.get(f'/api/v3/supplier-requests?company_id={w["buyer"]}',headers=w["headers"][0]); w["row"]=rows.json()[0]
    assert w["row"]["status"]=="replied"
    selected=await client.patch(path,json=update(w,status="selected",quoted_price_rub="7.123456789123",price_basis="unit",note="Внутренняя заметка"),headers=w["headers"][0])
    assert selected.status_code==200,selected.text
    assert selected.json()["quoted_price_rub"]=="7.123456789123"
    assert await db_session.scalar(select(func.count()).select_from(Deal))==0
    assert await db_session.scalar(select(func.count()).select_from(SupplierRequestMessage))==2
    assert await db_session.scalar(select(func.count()).select_from(HumanApprovalRecord))==3
    seller_view=(await client.get(f'/api/v3/supplier-requests?company_id={w["seller"]}&role=seller',headers=w["headers"][1])).json()[0]
    assert seller_view["note"]=="" and seller_view["quoted_price_rub"] is None


async def test_stale_revision_and_wrong_role_cannot_change_card(client, workspace):
    w=workspace; await mark_sent(client,w); path=f'/api/v3/supplier-requests/{w["row"]["id"]}'
    assert (await client.patch(path,json=update(w,expected_revision=1,status="selected"),headers=w["headers"][0])).status_code==409
    assert (await client.patch(path,json=update(w,company_id=str(w["seller"]),status="selected"),headers=w["headers"][1])).status_code==404
    assert (await client.patch(path,json=update(w,status="draft"),headers=w["headers"][0])).status_code==409
    for bad in ("NaN","-1","Infinity","1.0000000000001"):
        assert (await client.patch(path,json=update(w,quoted_price_rub=bad),headers=w["headers"][0])).status_code==422


async def test_changed_need_draft_cannot_be_sent(client, workspace, db_session):
    w=workspace; w["need"].revision=2; await db_session.commit()
    assert (await client.patch(f'/api/v3/supplier-requests/{w["row"]["id"]}',json=update(w),headers=w["headers"][0])).status_code==409


async def test_reply_files_deduplicate_validate_and_stay_buyer_private(client, workspace):
    w=workspace; await mark_sent(client,w); path=f'/api/v3/supplier-requests/{w["row"]["id"]}/files'
    content="Цена за единицу: 7,12 ₽. Срок: 5 дней.".encode()
    first=await client.post(f'{path}?company_id={w["buyer"]}',files={"file":("Ответ.txt",content,"text/plain")},headers=w["headers"][0]); assert first.status_code==201,first.text
    again=await client.post(f'{path}?company_id={w["buyer"]}',files={"file":("Ещё.txt",content,"text/plain")},headers=w["headers"][0]); assert again.json()["id"]==first.json()["id"]
    download=await client.get(f'{path}/{first.json()["id"]}?company_id={w["buyer"]}',headers=w["headers"][0]); assert download.content==content
    assert download.headers["cache-control"]=="no-store" and download.headers["x-content-type-options"]=="nosniff"
    assert (await client.get(f'{path}/{first.json()["id"]}?company_id={w["seller"]}',headers=w["headers"][1])).status_code==404
    bad=await client.post(f'{path}?company_id={w["buyer"]}',files={"file":("bad.pdf",b"not-pdf","application/pdf")},headers=w["headers"][0]); assert bad.status_code==422


async def test_specification_export_is_private_and_has_no_made_up_price(client, workspace):
    w=workspace; path=f'/api/v3/needs/{w["need"].id}/specification.csv'
    response=await client.get(f'{path}?company_id={w["buyer"]}',headers=w["headers"][0]); assert response.status_code==200
    assert "Количество;Единица;Срок поставки" in response.content.decode('utf-8-sig')
    assert "9999" not in response.text and "Цена" not in response.text
    assert (await client.get(f'{path}?company_id={w["seller"]}',headers=w["headers"][1])).status_code in {403,404}


@pytest.mark.parametrize('price',['7','0.123456789123'])
async def test_order_export_checks_parties_and_uses_frozen_terms(client,workspace,db_session,price):
    from app.commercial import estimate,frozen_snapshot
    from app.money import amount
    w=workspace; need=w['need']
    offer=Offer(need_id=need.id,company_id=w['seller'],price_rub=Decimal(price),available_units=100,lead_time_days=5,delivery_cost_rub=100,moq_units=1)
    db_session.add(offer);await db_session.flush()
    total=amount(Decimal(price)*100)+100
    value=estimate(units=100,unit_price=price,delivery=100,terms={'delivery_method':'separate','delivery_conditions':'Тестовый адрес','tax_basis':'includes_vat','vat_rate_pct':'20'},buyer=w['buyer'],seller=w['seller'],source={'type':'offer','id':str(offer.id),'revision':1})
    deal=Deal(offer_id=offer.id,need_id=need.id,buyer_company_id=w['buyer'],seller_company_id=w['seller'],units=100,total_price_rub=total,unit_price_rub=Decimal(price),commercial_snapshot=frozen_snapshot(estimate_value=value,need=need,offer=offer))
    db_session.add(deal);await db_session.commit()
    path=f'/api/v3/deals/{deal.id}/export-1c'
    first=await client.get(f'{path}?company_id={w["buyer"]}',headers=w['headers'][0])
    assert first.status_code==(200 if price=='7' else 409),first.text
    if price=='7':
        need.characteristics={'unit':'кг','material':'сталь'};offer.price_rub=999;await db_session.commit()
        again=await client.get(f'{path}?company_id={w["seller"]}',headers=w['headers'][1])
        assert again.content==first.content and b'700.00' in again.content
        assert first.headers['x-export-contract']=='porukam-1c-1'
        assert '<Ставка>20</Ставка>' in first.text and '2E+1' not in first.text
    else:
        precise=await client.get(f'{path}?company_id={w["buyer"]}&format=csv',headers=w['headers'][0])
        assert precise.status_code==200 and price in precise.content.decode('utf-8-sig')
        import csv, io
        records=list(csv.DictReader(io.StringIO(precise.content.decode('utf-8-sig')),delimiter=';'))
        assert records[0]['Ставка НДС, %']=='20' and records[0]['НДС в сумме, ₽']
    assert (await client.get(f'{path}?company_id={w["other"]}',headers=w['headers'][2])).status_code==404

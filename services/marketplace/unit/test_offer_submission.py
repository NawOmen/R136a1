from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import uuid
import pytest
from fastapi import HTTPException
from app import offer_resources as resources
from app.api import offers
from app.deps import CurrentUser
from app.schemas import OfferIn, OfferPatch
from app.category_registry import resolve_category


def proposal(**changes):
    return OfferIn.model_validate(dict(company_id=uuid.uuid4(), price_rub='4.80', available_units=20000,
        lead_time_days=2, commercial_terms={'delivery_method':'self_pickup','tax_basis':'no_vat',
        'delivery_conditions':'Самовывоз со склада продавца в Москве'}, **changes))


def test_receipt_terms_missing_tax_and_unknown_delivery_are_blocked():
    assert resources.commercial_send_blockers(proposal()) == []
    item=proposal(); item.commercial_terms.delivery_conditions='   '
    assert 'Не подтверждено место получения товара' in resources.commercial_send_blockers(item)
    item.commercial_terms.delivery_method='unknown'; item.commercial_terms.tax_basis='unknown'
    assert len(resources.commercial_send_blockers(item)) >= 2


def test_patch_can_explicitly_clear_the_product_when_switching_to_capacity():
    patch=OfferPatch.model_validate({'expected_revision':3,'resource_kind':'capacity','product_id':None})
    assert patch.model_dump(exclude_unset=True)=={'expected_revision':3,'resource_kind':'capacity','product_id':None}


@pytest.mark.asyncio
@pytest.mark.parametrize('age,fresh',[(1,True),(6.99,True),(7.01,False),(None,False),(-1,False)])
async def test_stock_freshness_and_free_stock_exclude_other_commitments(monkeypatch,age,fresh):
    company=uuid.uuid4(); product=NS(id=uuid.uuid4(),company_id=company,stock_units=30000,
        stock_updated_at=None if age is None else datetime.now(timezone.utc)-timedelta(days=age))
    held=[NS(product_id=product.id,units=10000,status='committed')]
    monkeypatch.setattr(resources,'reservations',AsyncMock(return_value=held))
    need=NS(characteristics={'unit':'шт'},deadline_date=date.today()+timedelta(days=10))
    value=await resources.offer_resource(NS(get=AsyncMock(return_value=product)),need,company,'stock',product.id)
    assert value['free_units']==20000 and value['fresh']==fresh
    assert bool(value['blockers']) is not fresh


@pytest.mark.asyncio
async def test_capacity_uses_daily_coefficients_deadline_and_occupied_resource(monkeypatch):
    company=uuid.uuid4(); leaf=resolve_category('Строительство','Крепёж'); today=date.today()
    def entry(day,available,version=None):return NS(id=uuid.uuid4(),date=day,available_units=available,unit='мин',category_conversions=[dict(category_id=leaf['id'],order_unit='шт',resource_units_per_order_unit=2,profile_version=version or leaf['technical_profile']['version'])])
    rows=[entry(today,25),entry(today+timedelta(days=2),1000),entry(today,1000,999)]
    held=[NS(capacity_entry_id=rows[0].id,resource_units=5,units=2,status='committed')]
    monkeypatch.setattr(resources,'reservations',AsyncMock(return_value=held))
    db=NS(scalars=AsyncMock(return_value=NS(all=lambda:rows)))
    need=NS(category='Строительство',subcategory='Крепёж',characteristics={'unit':'шт'},deadline_date=today+timedelta(days=1))
    value=await resources.offer_resource(db,need,company,'capacity')
    assert value['free_units']==10
    db.scalars=AsyncMock(return_value=NS(all=lambda:[]))
    assert (await resources.offer_resource(db,need,company,'capacity'))['free_units']==0


@pytest.mark.asyncio
async def test_empty_capacity_is_a_blocker_not_unknown_permission_to_send(monkeypatch):
    monkeypatch.setattr(offers,'_sending_warnings',AsyncMock(return_value=[]))
    monkeypatch.setattr(offers,'offer_resource',AsyncMock(return_value={'free_units':0,'blockers':[]}))
    blockers,_=await offers._send_blockers(None,need=NS(deadline_date=date.today()+timedelta(days=5)),company_id=uuid.uuid4(),moq_units=1,available_units=20,lead_time_days=1,resource_kind='capacity',product_id=None)
    assert any('мощность' in value for value in blockers)


@pytest.mark.asyncio
async def test_patch_requires_current_revision_before_mutating_or_checking_resources(monkeypatch):
    company=uuid.uuid4(); offer=NS(id=uuid.uuid4(),company_id=company,need_id=uuid.uuid4(),revision=4,status='sent',price_rub='4.8')
    db=NS(get=AsyncMock(return_value=offer),scalar=AsyncMock(return_value=NS()),refresh=AsyncMock(),commit=AsyncMock())
    monkeypatch.setattr(offers,'require_company_seller',AsyncMock());monkeypatch.setattr(offers,'require_company_admin',AsyncMock());monkeypatch.setattr(offers,'require_verified_seller',AsyncMock())
    with pytest.raises(HTTPException) as error:
        await offers.update_offer(offer.id,OfferPatch(expected_revision=3,price_rub='4.9'),CurrentUser(uuid.uuid4()),db)
    assert error.value.status_code==409 and offer.price_rub=='4.8'
    db.commit.assert_not_awaited()

@pytest.mark.asyncio
@pytest.mark.parametrize('initial_status', ['sent', 'stale'])
async def test_confirmed_edit_rechecks_resource_and_notifies_buyer_with_new_revision(monkeypatch, initial_status):
    company=uuid.uuid4(); buyer=uuid.uuid4()
    offer=NS(id=uuid.uuid4(),need_id=uuid.uuid4(),company_id=company,revision=3,status=initial_status,commercial_quote={'old':True},
        price_rub='4.80',available_units=20,lead_time_days=1,delivery_cost_rub=0,moq_units=1,price_tiers=[],valid_until=None,
        resource_kind='capacity',product_id=None,commercial_terms={'delivery_method':'self_pickup','tax_basis':'no_vat','delivery_conditions':'Москва, склад продавца'})
    need=NS(status='waiting_for_match',created_by_user_id=buyer,revision=1,id=offer.need_id)
    db=NS(get=AsyncMock(return_value=offer),scalar=AsyncMock(return_value=need),refresh=AsyncMock(),commit=AsyncMock())
    for name in ['require_company_seller','require_company_admin','require_verified_seller','require_current_evidence','record_human_approval','run_market_rematch','notify']:
        monkeypatch.setattr(offers,name,AsyncMock())
    monkeypatch.setattr(offers,'need_is_current',lambda _:True)
    check=AsyncMock(return_value=([],[]));monkeypatch.setattr(offers,'_send_blockers',check)
    monkeypatch.setattr(offers,'offer_quote',AsyncMock(return_value={'new':True}))
    updated=await offers.update_offer(offer.id,OfferPatch(expected_revision=3,price_rub='4.90'),CurrentUser(uuid.uuid4()),db)
    assert updated.status=='sent'
    assert updated.revision==4 and str(updated.price_rub)=='4.90' and updated.commercial_quote=={'new':True}
    check.assert_awaited_once(); db.commit.assert_awaited_once()
    assert offers.notify.await_args.kwargs['href']==f'/needs/{need.id}#offer-{offer.id}'
    assert offers.record_human_approval.await_args.kwargs['action']=='seller_quote_changed'

@pytest.mark.asyncio
async def test_edit_preview_allows_own_proposal_but_reports_a_stale_revision(monkeypatch):
    from app.schemas import OfferSendPreviewIn
    data=proposal(); need=NS(id=uuid.uuid4(),company_id=uuid.uuid4(),status='waiting_for_match',visibility='open_anonymized')
    existing=NS(id=uuid.uuid4(),status='sent',revision=4)
    db=NS(scalar=AsyncMock(side_effect=[need,existing]))
    for name in ['require_company_seller','require_verified_seller','require_company_admin','require_current_evidence']:
        monkeypatch.setattr(offers,name,AsyncMock())
    monkeypatch.setattr(offers,'need_is_current',lambda _:True)
    monkeypatch.setattr(offers,'_send_blockers',AsyncMock(return_value=([],[])))
    result=await offers.preview_offer_send(need.id,OfferSendPreviewIn(**data.model_dump(),offer_id=existing.id,expected_revision=3),CurrentUser(uuid.uuid4()),db)
    assert not result.can_send and any('изменилось' in text for text in result.blockers)
    assert not any('уже отправила' in text for text in result.blockers)


@pytest.mark.asyncio
async def test_admission_failure_blocks_sending_instead_of_warning(monkeypatch):
    monkeypatch.setattr(offers, '_sending_warnings', AsyncMock(return_value=['Допуск продавца не подтверждён: заключение о спецификации']))
    monkeypatch.setattr(offers, 'offer_resource', AsyncMock(return_value={'free_units': 20000, 'blockers': []}))
    blockers, warnings = await offers._send_blockers(None, need=NS(deadline_date=date.today()+timedelta(days=5)),
        company_id=uuid.uuid4(), moq_units=1, available_units=20000, lead_time_days=1, resource_kind='capacity', product_id=None)
    assert len(blockers) == 1 and 'заключение о спецификации' in blockers[0]
    assert warnings == []

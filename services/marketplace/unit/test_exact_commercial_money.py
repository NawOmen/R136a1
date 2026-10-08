from decimal import Decimal
from types import SimpleNamespace as NS
import uuid
from datetime import date
import pytest
from fastapi import HTTPException
from app.commercial import estimate, distribute, require_complete, frozen_snapshot, baseline_comparable
from app.money import amount, Money, Amount
from pydantic import TypeAdapter, ValidationError

TERMS = {'delivery_method':'separate','tax_basis':'no_vat','delivery_conditions':'Синтетический адрес получателя, Россия'}

def bill(units=100,price='7',delivery=0,terms=None,shared=0,**kwargs):
    return estimate(units=units,unit_price=price,delivery=delivery,terms=terms or TERMS,buyer='buyer',seller='seller',
                    source={'type':'offer','revision':1},shared=shared,**kwargs)


def test_precise_price_large_batch_and_half_up_amount():
    assert bill(units=1_000_000_000,price='0.00000000125')['total_rub']=='1.25'
    assert bill(units=1,price='0.005')['total_rub']=='0.01'
    assert amount('2.675')==Decimal('2.68')
    assert amount('-2.675')==Decimal('-2.68')
    for invalid in (True,'NaN','Infinity','0.1234567890123','не число',{},'1e999'):
        with pytest.raises((ValidationError,ValueError)):TypeAdapter(Money).validate_python(invalid)
    for invalid in ('2.675','1e999','не число',{}):
        with pytest.raises(ValidationError):TypeAdapter(Amount).validate_python(invalid)


def test_distribution_is_exact_deterministic_and_not_order_dependent():
    weights={'c':1,'a':1,'b':1}
    parts=distribute('0.02',weights)
    assert parts=={'a':Decimal('.01'),'b':Decimal('.01'),'c':Decimal(0)}
    assert parts==distribute('0.02',dict(reversed(list(weights.items()))))
    assert sum(parts.values())==Decimal('.02')


def test_control_group_bill_and_individual_loss_remain_visible():
    volumes=[5000,10000,35000]
    shared=distribute(5000,dict(enumerate(volumes)))
    totals=[]
    for index,(units,operation,delivery,service,reserve) in enumerate(zip(volumes,[1000,2000,7000],[1000,1500,3000],[200,400,1400],[300,600,2100])):
        expenses=[{'code':code,'title':title,'amount_rub':value,'source':'Синтетический тариф производителя','version':'1'}
                  for code,title,value in [('individual_operations','Операции',operation),('other','Услуги изготовителя',service),('reserve_holding','Удержание изготовителем',reserve)]]
        value=bill(units=units,delivery=delivery,shared=shared[index],terms={**TERMS,'expenses':expenses})
        require_complete(value)
        totals.append(Decimal(value['total_rub']))
        assert sum(Decimal(line['amount_rub']) for line in value['lines'])==totals[-1]
        assert all(Decimal(line['amount_rub'])==0 for line in value['lines'] if line['code'].startswith('platform_'))
    assert totals==[Decimal(38000),Decimal(75500),Decimal(262000)]
    assert sum(totals)==Decimal(375500)
    assert sum([Decimal(42000),Decimal(84000),Decimal(294000)])-sum(totals)==Decimal(44500)
    assert Decimal(42000)-(totals[0]+5000)==Decimal(-1000)


def test_unknown_delivery_mandatory_expenses_and_included_tax_are_not_zero_or_added_twice():
    for value in (bill(delivery=None),bill(terms={**TERMS,'tax_basis':'unknown'}),
                  bill(terms={**TERMS,'expenses':[{'code':'other','title':'Неуточнённая услуга','amount_rub':None,'source':'Тариф','version':'1'}]})):
        assert value['total_rub'] is None
        with pytest.raises(HTTPException):require_complete(value)
    value=bill(price='1.01',terms={**TERMS,'tax_basis':'includes_vat','vat_rate_pct':'22'})
    assert value['total_rub']=='101.00'
    assert value['lines'][0]['included_vat_rub']=='18.21'
    assert not bill(terms={**TERMS,'delivery_conditions':None})['complete']


def test_switching_is_conditional_and_holding_is_not_billed_again():
    terms={**TERMS,'expenses':[{'code':code,'title':code,'amount_rub':value,'source':'Тариф','version':'1'}
                              for code,value in [('reserve_holding',10),('switching',20)]]}
    assert bill(price=1,terms=terms)['total_rub']=='110.00'
    assert bill(price=1,terms=terms,switching=True)['total_rub']=='120.00'


def test_commercial_snapshot_is_detached_and_baseline_requires_same_confirmed_conditions():
    need=NS(id=uuid.uuid4(),revision=2,category='Строительство',subcategory='Крепёж',characteristics={'unit':'шт'},
            category_profile={'profile_version':2},volume_units=100,deadline_date=date.today(),delivery_address_id=None)
    quote=frozen_snapshot(estimate_value=bill(),need=need)
    quote['offer']={'moq_units':1,'available_units':100,'lead_time_days':0,'valid_until':None}
    assert baseline_comparable(quote,need,bill(delivery=5000))  # Same service, price may differ.
    assert not baseline_comparable(quote,need,bill(terms={**TERMS,'delivery_conditions':'Другой адрес'}))
    assert not baseline_comparable(quote,need,bill(terms={**TERMS,'tax_basis':'includes_vat','vat_rate_pct':'22'}))
    equivalent_a=bill(terms={**TERMS,'tax_basis':'includes_vat','vat_rate_pct':'22.00'})
    equivalent_b=bill(terms={**TERMS,'tax_basis':'includes_vat','vat_rate_pct':'22'})
    assert equivalent_a['terms']==equivalent_b['terms']
    need.characteristics['unit']='упак'
    need.category_profile['profile_version']=3
    assert quote['need']['characteristics']=={'unit':'шт'}
    assert quote['need']['category_profile']['profile_version']==2
    assert not baseline_comparable(quote,need,bill())


def test_money_contract_is_identical_in_both_service_images_and_holding_survives_cancellation():
    from pathlib import Path
    from app.commercial import holding_quotes, holding_total
    root=Path(__file__).resolve().parents[3]
    assert (root/'services/marketplace/app/money.py').read_bytes()==(root/'services/optimizer/app/money.py').read_bytes()
    quote={'estimate':{'source':{'id':'commitment','revision':1},'lines':[{'code':'reserve_holding','amount_rub':'50.00'}]}}
    snapshot={'holding_quotes':[quote]}
    rejected=NS(confirmation_status='rejected',commercial_snapshot=quote)
    approved=NS(confirmation_status='approved',commercial_snapshot=quote)
    assert holding_total(holding_quotes(snapshot,[rejected]))==Decimal('50.00')
    assert holding_total(holding_quotes(snapshot,[approved]))==Decimal('50.00')
    from copy import deepcopy
    new_quote=deepcopy(quote);new_quote['estimate']['source']['revision']=2;new_quote['estimate']['lines'][0]['amount_rub']='70.00'
    renewed=NS(confirmation_status='approved',commercial_snapshot=new_quote)
    assert holding_total(holding_quotes(snapshot,[renewed]))==Decimal('120.00')
    assert quote['estimate']['lines'][0]['amount_rub']=='50.00'

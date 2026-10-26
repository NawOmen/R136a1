import csv,io,uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import pytest
from fastapi import HTTPException
from app.order_export import commerceml, order_csv, csv_bytes, NAMESPACE


def example(price="7", quantity=100):
    buyer, seller=uuid.uuid4(),uuid.uuid4()
    total=(Decimal(price)*quantity).quantize(Decimal('.01'))+Decimal('100')
    deal=SimpleNamespace(id=uuid.uuid4(),need_id=uuid.uuid4(),seller_company_id=seller,buyer_company_id=buyer,units=quantity,total_price_rub=total,status="created",created_at=datetime(2026,10,26,tzinfo=timezone.utc))
    deal.commercial_snapshot={"need":{"category":"Упаковка","characteristics":{"unit":"шт","material":"бумага"},"deadline_date":"2026-11-10"},
        "product":{"name":"Стакан <бумажный> & крышка"},"estimate":{"complete":True,"unit_price_rub":price,"terms":{"tax_basis":"no_vat"},"lines":[
            {"code":"goods","title":"Продукция","amount_rub":str(total-100),"payee_company_id":str(seller),"tax_basis":"no_vat"},
            {"code":"delivery","title":"Доставка","amount_rub":"100.00","payee_company_id":str(seller),"tax_basis":"no_vat"}]}}
    companies=[{"id":cid,"display_name":"Тестовая компания","full_name":"ООО «Синтетика»","inn":"0000000000","kpp":"000000000","legal_form":"ООО","legal_address":"Тестовый адрес"} for cid in (buyer,seller)]
    return deal,companies


def test_xml_preserves_contract_totals_ids_escaping_and_is_deterministic():
    deal,companies=example(); data=commerceml(deal,*companies)
    assert data==commerceml(deal,*companies)
    root=ET.fromstring(data); ns={'c':NAMESPACE}
    assert root.attrib['ВерсияСхемы']=='2.10'
    assert root.findtext('c:Документ/c:Ид',namespaces=ns)==str(deal.id)
    assert root.findtext('c:Документ/c:Сумма',namespaces=ns)=='800.00'
    rows=root.findall('.//c:Товары/c:Товар',ns)
    assert rows[0].findtext('c:Наименование',namespaces=ns)=='Стакан <бумажный> & крышка'
    assert sum(Decimal(r.findtext('c:Сумма',namespaces=ns)) for r in rows)==Decimal('800.00')
    assert 'СтранаПроисхождения' not in data.decode()


def test_fractional_unit_price_never_silently_rounds_and_exact_csv_is_available():
    deal,companies=example('0.123456789123',1000)
    with pytest.raises(HTTPException) as err:commerceml(deal,*companies)
    assert err.value.status_code==409
    assert '0.123456789123' in order_csv(deal,*companies).decode('utf-8-sig')


@pytest.mark.parametrize('broken',['missing_snapshot','cancelled','wrong_sum','other_payee'])
def test_unusable_order_is_rejected(broken):
    deal,companies=example()
    if broken=='missing_snapshot':deal.commercial_snapshot=None
    if broken=='cancelled':deal.status='cancelled'
    if broken=='wrong_sum':deal.total_price_rub+=1
    if broken=='other_payee':deal.commercial_snapshot['estimate']['lines'][0]['payee_company_id']='platform'
    with pytest.raises(HTTPException):commerceml(deal,*companies)


def test_csv_formula_protection_and_multiline_quoting():
    data=csv_bytes([['=HYPERLINK("bad")','\t=1+1','+1','Обычный; текст\nвторая строка']])
    row=next(csv.reader(io.StringIO(data.decode('utf-8-sig')),delimiter=';'))
    assert all(s.startswith("'") for s in row[:3])
    assert row[3]=='Обычный; текст\nвторая строка'

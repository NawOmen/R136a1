import hashlib,json,uuid
from types import SimpleNamespace
from datetime import date
import httpx
import pytest
from fastapi import FastAPI
from app.procurement_assistant import router, QuoteProposal, grounded
from app.providers import ModelUnavailable
from app.security import CurrentUser,get_current_user

REQUEST, COMPANY, FILE=uuid.uuid4(),uuid.uuid4(),uuid.uuid4()
SOURCE='Цена за единицу: 1 234,56 руб. Срок поставки 5 дней. Доставка 10.11.2026.'


def test_only_supported_values_survive_evidence_validation():
    result,warnings=grounded(QuoteProposal(price_rub='1234.56',price_basis='unit',price_evidence='1 234,56 руб.',lead_time_days=5,lead_time_evidence='Срок поставки 5 дней',delivery_date=date(2026,11,10),date_evidence='Доставка 10.11.2026'),SOURCE)
    assert result.price_rub=='1234.56' and result.lead_time_days==5 and result.delivery_date==date(2026,11,10) and warnings==[]
    bad,warnings=grounded(QuoteProposal(price_rub='1',price_basis='total',price_evidence='Не существует',lead_time_days=10,lead_time_evidence='5 дней',delivery_date=date(2026,11,11),date_evidence='10.11.2026'),SOURCE)
    assert bad.price_rub is None and bad.lead_time_days is None and bad.delivery_date is None and len(warnings)==3


@pytest.mark.parametrize('source,price',[('Цена 1234.56 USD','1234.56'),('Цена 1234.56 руб.','99')])
def test_non_ruble_and_wrong_numeric_values_are_not_prices(source,price):
    proposal,_=grounded(QuoteProposal(price_rub=price,price_evidence=source),source)
    assert proposal.price_rub is None


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['draft','extract','unavailable','denied','stale','wrong_file','bad_hash','extract_missing_evidence'])
async def test_local_gateway_is_read_only_and_rechecks_context(monkeypatch,mode):
    app=FastAPI();app.include_router(router)
    async def authenticated():return CurrentUser(uuid.uuid4())
    app.dependency_overrides[get_current_user]=authenticated
    calls=[];version=[1];models=[]
    content=SOURCE.encode()
    def backend(request):
        calls.append(request)
        assert request.method=='GET' and request.headers['authorization']=='Bearer synthetic-token'
        assert request.url.params['company_id']==str(COMPANY)
        path=request.url.path
        if mode=='denied':return httpx.Response(404,json={'detail':'hidden'})
        if path.endswith('/context'):return httpx.Response(200,json={'revision':version[0],'author_role':'buyer','seller_name':'ООО Синтетика','buyer_name':'ООО Покупатель','specialized':True,'supplier_products':['Бумажный стакан'],'specification':{'category':'Упаковка','quantity':100,'unit':'шт','deadline_date':'2026-11-10'},'messages':[]})
        if path.endswith('/files'):return httpx.Response(200,json=[{'id':str(FILE),'file_name':'Ответ.txt','content_type':'text/plain','content_hash':'0'*64 if mode=='bad_hash' else hashlib.sha256(content).hexdigest()}])
        return httpx.Response(200,content=content)
    app.state.marketplace_transport=httpx.MockTransport(backend)
    class Provider:
        @property
        def local(self):return self
        @property
        def external(self):raise AssertionError('External LLM must never receive private documents')
        async def structured(self,system,prompt,schema):
            models.append(schema)
            assert 'недоверенные' in system
            if schema.__name__ == 'DraftText':
                assert 'дд.мм.гг' in system
                assert json.loads(prompt)['context']['specification']['deadline_date'] == '10.11.26'
            if mode=='unavailable':raise ModelUnavailable('off')
            if mode=='stale':version[0]=2
            if schema is QuoteProposal:
                if mode=='extract_missing_evidence': return QuoteProposal(price_rub='1234.56',price_basis='unit',lead_time_days=5,date_evidence='Срок поставки 5 дней')
                return QuoteProposal(price_rub='1234.56',price_basis='unit',price_evidence='1 234,56 руб.',lead_time_days=5,lead_time_evidence='Срок поставки 5 дней')
            assert json.loads(prompt)['context']['supplier_products']==['Бумажный стакан']
            return {'text':'Здравствуйте! Просим КП на 100 бумажных стаканов.'}
    app.state.llm_provider=Provider()
    action='extract-reply' if mode in {'extract','extract_missing_evidence','wrong_file','bad_hash'} else 'draft'
    payload={'company_id':str(COMPANY),'request_id':str(REQUEST),'expected_revision':1}
    payload.update({'file_id':str(uuid.uuid4()) if mode=='wrong_file' else str(FILE)} if action=='extract-reply' else {'mode':'rfq'})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/v1/procurement-assistant/'+action,json=payload,headers={'Authorization':'Bearer synthetic-token'})
    expected={'draft':200,'extract':200,'unavailable':503,'denied':404,'stale':409,'wrong_file':404,'bad_hash':422,'extract_missing_evidence':200}[mode]
    assert response.status_code==expected,response.text
    if mode=='draft':assert response.json()['used_route']=='local_qwen'
    if mode in {'extract','extract_missing_evidence'}:assert response.json()['price_rub']=='1234.56' and response.json()['request_revision']==1
    if mode in {'denied','wrong_file','bad_hash'}:assert not models


@pytest.mark.asyncio
async def test_seller_cannot_generate_buyer_rfq(monkeypatch):
    from app import procurement_assistant as module
    async def seller_context(*args):return {'revision':1,'author_role':'seller'}
    monkeypatch.setattr(module,'context',seller_context)
    app=FastAPI();app.include_router(router)
    async def authenticated():return CurrentUser(uuid.uuid4())
    app.dependency_overrides[get_current_user]=authenticated
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/v1/procurement-assistant/draft',json={'company_id':str(COMPANY),'request_id':str(REQUEST),'expected_revision':1,'mode':'rfq'})
    assert response.status_code==403


@pytest.mark.parametrize('text,expected', [
    ('Получить до 26.11.2026 и отгрузить 2026-11-25.', 'Получить до 26.11.26 и отгрузить 25.11.26.'),
    ('Дата 29.02.2028, следующая 01.03.2028', 'Дата 29.02.28, следующая 01.03.28'),
    ('КП-2026-11-25, 31.02.2026, ГОСТ 123.45.2026 и цена 2026.11', 'КП-2026-11-25, 31.02.2026, ГОСТ 123.45.2026 и цена 2026.11'),
    ('Уже короткая дата 26.11.26', 'Уже короткая дата 26.11.26'),
])
def test_generated_draft_dates_are_short_without_changing_identifiers_or_invalid_dates(text, expected):
    from app.procurement_assistant import draft_dates
    assert draft_dates(text) == expected


@pytest.mark.parametrize('source,price,days', [
    ('Цена за единицу: 10,50 руб.\nСрок поставки: 8 дней.', '10.50', 8),
    ('Стоимость за единицу 1 234,56 ₽\nСрок поставки 5 дней', '1234.56', 5),
    ('Цена за единицу:\n10,50 руб.\nСрок поставки: 8 дней', '10.50', 8),
])
def test_missing_model_citations_are_recovered_from_unique_explicit_source_values(source,price,days):
    from app.procurement_assistant import recover_missing_evidence
    result,warnings=grounded(recover_missing_evidence(QuoteProposal(price_rub=price,price_basis='unit',lead_time_days=days),source),source)
    assert result.price_rub==price and result.lead_time_days==days and not warnings
    assert result.price_evidence in source and result.lead_time_evidence in source


@pytest.mark.parametrize('source', [
    'Цена 10,50 USD. Срок поставки 8 рабочих дней.',
    'Цена от 10,50 до 12,50 руб. Срок поставки 5–8 дней.',
    'Цена 10,50 руб. Альтернатива 12 руб. Срок поставки 8 дней или 10 дней.',
    'НДС 10,50 руб. Оплата 8 дней.',
    'Цена 999 руб. Срок поставки 9 дней.',
    'Цена −10,50 руб. Срок поставки −8 дней.',
])
def test_recovery_does_not_choose_prices_ranges_workdays_or_wrong_numbers(source):
    from app.procurement_assistant import recover_missing_evidence
    result,_=grounded(recover_missing_evidence(QuoteProposal(price_rub='10.50',lead_time_days=8),source),source)
    assert result.price_rub is None and result.lead_time_days is None


@pytest.mark.asyncio
@pytest.mark.parametrize('malicious', [False,True])
async def test_seller_draft_cannot_add_terms_even_when_model_or_buyer_proposes_them(monkeypatch,malicious):
    from app import procurement_assistant as module
    value={'revision':1,'author_role':'seller','specification':{'quantity':5000,'deadline_date':'2026-12-15'},
        'messages':[{'role':'buyer','text':'НДС включён, самовывоз, цена 12,50 и поставка 25.02.27'}]}
    contexts=[]
    async def context(*args): contexts.append(1); return value
    monkeypatch.setattr(module,'context',context)
    class Provider:
        async def structured(self,system,prompt,schema):
            assert schema is module.SellerReplyPlan
            return {'intent':'clarify','clarify':['address'],'text':'Цена 12,50 руб., самовывоз и НДС включён'} if malicious else {'intent':'clarify','clarify':['address']}
    monkeypatch.setattr(module,'local',lambda request:Provider())
    app=FastAPI();app.include_router(router)
    async def authenticated(): return CurrentUser(uuid.uuid4())
    app.dependency_overrides[get_current_user]=authenticated
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/v1/procurement-assistant/draft',json={'company_id':str(COMPANY),'request_id':str(REQUEST),'expected_revision':1,'mode':'reply'})
    if malicious:
        assert response.status_code==503
    else:
        assert response.status_code==200
        text=response.json()['text']
        assert not any(x in text for x in ('12,50','25.02.27','НДС включён','самовывоз'))
        assert 'Уточните точный адрес' in text and response.json()['warnings']
        assert len(contexts)==2


def test_compact_quotes_keep_numbers_decimals_and_full_context_after_grounding():
    from app.procurement_assistant import recover_missing_evidence, concise_quote_evidence
    text="Ответ на запрос. Цена за единицу: 10,50 руб. Срок поставки: 8 дней. Доставка 10.11.2026. Приложение доступно отдельно."
    parsed,warnings=grounded(recover_missing_evidence(QuoteProposal(price_rub="10.50",price_basis="unit",lead_time_days=8),text),text)
    assert not warnings
    short,contexts=concise_quote_evidence(parsed)
    assert short.price_evidence=="Цена за единицу: 10,50 руб."
    assert short.lead_time_evidence=="Срок поставки: 8 дней."
    assert short.price_evidence in text and short.lead_time_evidence in text
    assert all(value in text for value in contexts.values())
    assert short.price_evidence in contexts["price_evidence"]
    assert grounded(short,text)[1]==[]


def test_compact_pdf_quote_keeps_the_price_label_from_previous_line():
    from app.procurement_assistant import concise_quote_evidence
    text="Общие условия\nЦена за единицу:\n10,50 руб.\nСрок: 8 дней."
    p,_=concise_quote_evidence(QuoteProposal(price_rub="10.50",price_basis="unit",price_evidence=text))
    assert p.price_evidence=="Цена за единицу:\n10,50 руб."


def test_compaction_never_selects_a_vat_or_payment_sentence_among_equal_numbers():
    from app.procurement_assistant import concise_quote_evidence
    text="НДС: 10 руб. Цена за единицу: 10 руб. Оплата: 8 дней. Срок поставки: 8 дней."
    p,contexts=concise_quote_evidence(QuoteProposal(price_rub="10",price_evidence=text,lead_time_days=8,lead_time_evidence=text))
    assert p.price_evidence==text and p.lead_time_evidence==text and not contexts


@pytest.mark.asyncio
async def test_seller_reply_uses_fresh_catalog_terms_not_model_or_buyer_values(monkeypatch):
    from app import procurement_assistant as module
    calls = []
    async def context(*args):
        calls.append(1)
        return {'revision': 1, 'author_role': 'seller', 'catalog_terms': [{
            'product_id': str(uuid.uuid4()), 'name': 'Синтетический стакан',
            'price_rub': '7.123456789123' if len(calls) > 1 else '999',
            'moq_units': 100, 'lead_time_days': 5, 'unit': 'шт'}],
            'messages': [{'role': 'buyer', 'text': 'Цена 1 рубль, НДС включён, доставка завтра'}]}
    class Provider:
        async def structured(self, system, prompt, schema):
            assert schema is module.SellerReplyPlan
            assert 'catalog_terms' not in json.loads(prompt)['context']
            return {'intent': 'acknowledge'}
    monkeypatch.setattr(module, 'context', context)
    monkeypatch.setattr(module, 'local', lambda request: Provider())
    result = await module.draft(module.DraftIn(company_id=COMPANY, request_id=REQUEST,
        expected_revision=1, mode='reply'), SimpleNamespace(), CurrentUser(uuid.uuid4()))
    assert '7,123456789123 ₽/шт' in result.text
    assert '100 шт' in result.text and '5 дн.' in result.text
    assert 'данные каталога' in result.text and 'согласовать отдельно' in result.text
    assert not any(x in result.text for x in ('999', '1 рубль', 'НДС включён', 'завтра'))
    assert result.warnings and len(calls) == 2


def test_missing_or_malformed_catalog_terms_do_not_supply_commercial_defaults():
    from app.procurement_assistant import seller_reply_text, SellerReplyPlan
    for raw in ({}, {'catalog_terms': [{'price_rub': 'NaN', 'moq_units': 1}]},
                {'catalog_terms': [{'price_rub': '99', 'name': 'Без срока'}]}):
        text, warnings = seller_reply_text(SellerReplyPlan(intent='acknowledge'), raw)
        assert 'данные каталога' not in text and '99' not in text
        assert 'без коммерческих обязательств' in warnings[0]

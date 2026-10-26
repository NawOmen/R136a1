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
@pytest.mark.parametrize('mode',['draft','extract','unavailable','denied','stale','wrong_file','bad_hash'])
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
            if mode=='unavailable':raise ModelUnavailable('off')
            if mode=='stale':version[0]=2
            if schema is QuoteProposal:
                return QuoteProposal(price_rub='1234.56',price_basis='unit',price_evidence='1 234,56 руб.',lead_time_days=5,lead_time_evidence='Срок поставки 5 дней')
            assert json.loads(prompt)['context']['supplier_products']==['Бумажный стакан']
            return {'text':'Здравствуйте! Просим КП на 100 бумажных стаканов.'}
    app.state.llm_provider=Provider()
    action='extract-reply' if mode in {'extract','wrong_file','bad_hash'} else 'draft'
    payload={'company_id':str(COMPANY),'request_id':str(REQUEST),'expected_revision':1}
    payload.update({'file_id':str(uuid.uuid4()) if mode=='wrong_file' else str(FILE)} if action=='extract-reply' else {'mode':'rfq'})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/v1/procurement-assistant/'+action,json=payload,headers={'Authorization':'Bearer synthetic-token'})
    expected={'draft':200,'extract':200,'unavailable':503,'denied':404,'stale':409,'wrong_file':404,'bad_hash':422}[mode]
    assert response.status_code==expected,response.text
    if mode=='draft':assert response.json()['used_route']=='local_qwen'
    if mode=='extract':assert response.json()['price_rub']=='1234.56' and response.json()['request_revision']==1
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

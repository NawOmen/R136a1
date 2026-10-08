"""Versioned full estimates and frozen conditions; fees are never guessed."""
from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR
from typing import Literal
from pydantic import BaseModel, Field, model_validator, field_validator
from fastapi import HTTPException
from .money import Amount, MAX_AMOUNT, amount, decimal, exact_json

PLATFORM_FEE_POLICY = {'version':1,'service_rub':'0.00','reserve_holding_rub':'0.00','switching_rub':'0.00'}


class Expense(BaseModel):
    code: Literal['individual_operations','reserve_holding','switching','other']
    title: str = Field(min_length=1,max_length=160)
    amount_rub: Amount | None = Field(default=None,ge=0)
    required: bool = True
    payer: Literal['buyer'] = 'buyer'
    source: str = Field(min_length=1,max_length=300)
    version: str = Field(min_length=1,max_length=80)

    @field_validator('title','source','version')
    @classmethod
    def meaningful_text(cls, value):
        value=value.strip()
        if not value:raise ValueError('Название статьи, источник и версия не могут быть пустыми')
        return value


class CommercialTerms(BaseModel):
    delivery_method: Literal['included','separate','self_pickup','unknown'] = 'unknown'
    tax_basis: Literal['includes_vat','no_vat','unknown'] = 'unknown'
    vat_rate_pct: Decimal | None = Field(default=None,ge=0,le=100,max_digits=5,decimal_places=2)
    delivery_conditions: str | None = Field(default=None,max_length=1000)
    exceptions: str = Field(default='',max_length=2000)
    expenses: list[Expense] = Field(default_factory=list,max_length=25)

    @model_validator(mode='after')
    def coherent(self):
        if self.vat_rate_pct is not None:self.vat_rate_pct=self.vat_rate_pct.normalize()
        if self.delivery_conditions is not None:self.delivery_conditions=self.delivery_conditions.strip() or None
        if self.tax_basis == 'includes_vat' and self.vat_rate_pct is None:
            raise ValueError('Укажите включённую ставку НДС')
        if self.tax_basis != 'includes_vat' and self.vat_rate_pct is not None:
            raise ValueError('Ставка НДС относится только к цене с включённым НДС')
        return self


def distribute(total, weights):
    """Largest remainder, stable keys: participants sum to the rounded shared bill."""
    cents = int(amount(total) * 100)
    denominator = sum(weights.values())
    if denominator <= 0 or cents < 0:
        raise ValueError('Некорректная база распределения общих расходов')
    exact = {key: Decimal(cents)*weight/denominator for key,weight in weights.items()}
    base = {key:int(value.to_integral_value(rounding=ROUND_FLOOR)) for key,value in exact.items()}
    ordered = sorted(weights,key=lambda key:(-(exact[key]-base[key]),str(key)))
    for key in ordered[:cents-sum(base.values())]:base[key]+=1
    return {key:Decimal(value)/100 for key,value in base.items()}


def estimate(*, units, unit_price, delivery, terms, buyer, seller, source, shared=0, switching=False, goods_override=None, destination=None):
    terms = CommercialTerms.model_validate(terms or {})
    missing = []
    if terms.tax_basis == 'unknown':missing.append('Налоговая база цены не подтверждена')
    if terms.delivery_method == 'unknown':missing.append('Условия доставки не подтверждены')
    if terms.delivery_method == 'separate' and delivery is None:missing.append('Стоимость доставки не подтверждена')
    if terms.delivery_method in {'included','self_pickup'} and delivery not in (None,0,Decimal(0)):
        missing.append('Включённая доставка/самовывоз не должны повторно оплачиваться отдельной строкой')
    if terms.delivery_method != 'unknown' and not terms.delivery_conditions and not destination:
        missing.append('Не подтверждено место получения товара')
    lines = []
    def add(code,title,value,*,required=True,conditional=False,payee=None,rule='individual',line_source=None):
        charge = amount(value) if value is not None else None
        if charge is not None and abs(charge)>MAX_AMOUNT:
            raise HTTPException(422,'Сумма статьи выходит за денежный диапазон платформы')
        if required and charge is None and not conditional:missing.append(f'Неизвестна обязательная статья: {title}')
        vat = amount(charge*terms.vat_rate_pct/(100+terms.vat_rate_pct)) if charge is not None and terms.tax_basis=='includes_vat' else None
        lines.append({'code':code,'title':title,'amount_rub':charge,'required':required,'conditional':conditional,
                      'payer_company_id':str(buyer),'payee_company_id':str(payee or seller),
                      'allocation_rule':rule,'source':line_source or source,'tax_basis':terms.tax_basis,
                      'vat_rate_pct':str(terms.vat_rate_pct) if terms.vat_rate_pct is not None else None,'included_vat_rub':vat})
    add('goods','Продукция',decimal(unit_price)*units if goods_override is None else goods_override,rule='individual' if goods_override is None else 'volume_largest_remainder')
    add('shared','Доля общих расходов',shared,rule='volume_largest_remainder')
    add('delivery','Доставка',0 if terms.delivery_method in {'included','self_pickup'} else delivery)
    for expense in terms.expenses:
        add(expense.code,expense.title,expense.amount_rub,required=expense.required,
            conditional=(expense.code=='switching' and not switching) or (expense.code=='reserve_holding' and switching),
            line_source={'type':'producer_expense','reference':expense.source,'version':expense.version})
    for code,title in [('platform_service','Сервис платформы'),('platform_reserve','Удержание резерва платформой'),('platform_switching','Переключение платформой')]:
        add(code,title,0,payee='platform',line_source={'type':'platform_fee_policy','version':1})
    total = sum((line['amount_rub'] for line in lines if line['amount_rub'] is not None and not line['conditional']),Decimal(0))
    if abs(total)>MAX_AMOUNT:raise HTTPException(422,'Полная смета выходит за денежный диапазон платформы')
    return exact_json({'schema_version':1,'currency':'RUB','rounding':'ROUND_HALF_UP_PER_LINE',
                      'units':units,'unit_price_rub':decimal(unit_price),'terms':terms.model_dump(),
                      'source':source,'lines':lines,'missing':missing,'complete':not missing,
                      'known_total_rub':amount(total),'total_rub':None if missing else amount(total)})


def require_complete(value):
    if not value or not value.get('complete'):
        reasons = value.get('missing',[]) if value else ['Согласованная коммерческая смета отсутствует']
        raise HTTPException(409,'Окончательное согласование недоступно: '+'; '.join(reasons))


def frozen_snapshot(*, estimate_value, need, offer=None, address=None, resource=None):
    return exact_json(deepcopy({'schema_version':1,'estimate':estimate_value,
        'need':{'id':str(need.id),'revision':need.revision,'category':need.category,'subcategory':need.subcategory,
                'characteristics':need.characteristics,'category_profile':need.category_profile,'units':need.volume_units,
                'deadline_date':str(need.deadline_date),'delivery_address_id':str(need.delivery_address_id) if need.delivery_address_id else None,'delivery_address':address},
        'offer':None if offer is None else {'id':str(offer.id),'revision':offer.revision,'product_id':str(offer.product_id) if offer.product_id else None,
                  'price_rub':offer.price_rub,'price_tiers':offer.price_tiers,'available_units':offer.available_units,'moq_units':offer.moq_units,'lead_time_days':offer.lead_time_days,
                  'valid_until':str(offer.valid_until) if offer.valid_until else None},
        'resource':resource,'platform_fee_policy':PLATFORM_FEE_POLICY}))


async def offer_quote(db, offer, need, *, units=None):
    from .models import DeliveryAddress, Product
    from .matching import offer_unit_price
    address = await db.get(DeliveryAddress,need.delivery_address_id) if need.delivery_address_id else None
    address_value = None if address is None else {key:getattr(address,key) for key in ('address','city','region')}
    value = estimate(units=units or need.volume_units,unit_price=offer_unit_price(offer,units or need.volume_units),
        delivery=offer.delivery_cost_rub,terms=offer.commercial_terms,buyer=need.company_id,seller=offer.company_id,
        source={'type':'offer','id':str(offer.id),'revision':offer.revision},destination=address_value)
    snapshot = frozen_snapshot(estimate_value=value,need=need,offer=offer,address=address_value,
        resource={'kind':offer.resource_kind,'product_id':str(offer.product_id) if offer.product_id else None,'available_units':offer.available_units})
    if offer.product_id:
        product = await db.get(Product,offer.product_id)
        snapshot['product'] = exact_json({key:getattr(product,key) for key in ('name','characteristics','category_profile','price_rub','price_tiers')}) if product else None
    return snapshot


def baseline_comparable(quote, need, estimate_value):
    if not quote or not quote.get('estimate',{}).get('complete'):
        return False
    from datetime import date
    offer = quote.get('offer') or {}
    if not (offer.get('moq_units', 1) <= need.volume_units <= offer.get('available_units', 0)):
        return False
    if offer.get('lead_time_days', 0) > (need.deadline_date-date.today()).days:
        return False
    if offer.get('valid_until') and date.fromisoformat(offer['valid_until']) < date.today():
        return False
    saved = quote['need']; old_terms = quote['estimate']['terms']; new_terms = estimate_value['terms']
    return (saved.get('delivery_address_id') == (str(need.delivery_address_id) if need.delivery_address_id else None) and saved['id']==str(need.id) and saved['revision']==need.revision and saved['units']==need.volume_units
            and saved['characteristics']==need.characteristics and saved['deadline_date']==str(need.deadline_date)
            and old_terms['delivery_method']==new_terms['delivery_method']
            and old_terms['delivery_conditions']==new_terms['delivery_conditions']
            and (old_terms['tax_basis'],old_terms['vat_rate_pct'])==(new_terms['tax_basis'],new_terms['vat_rate_pct']))


async def group_snapshot(db, estimate_value, need, *, resource):
    from .models import DeliveryAddress
    address = await db.get(DeliveryAddress, need.delivery_address_id) if need.delivery_address_id else None
    address_value = None if address is None else {key:getattr(address,key) for key in ('address','city','region')}
    return frozen_snapshot(estimate_value=estimate_value,need=need,address=address_value,resource=resource)


def holding_quotes(snapshot, commitments):
    """Accepted holding remains a spent cost; cancellation is not a refund."""
    accepted = deepcopy((snapshot or {}).get('holding_quotes', []))
    keys = {(quote['estimate']['source']['id'],quote['estimate']['source'].get('revision',1)) for quote in accepted}
    for item in commitments:
        if item.confirmation_status == 'approved' and item.commercial_snapshot:
            quote = item.commercial_snapshot
            key = (quote['estimate']['source']['id'],quote['estimate']['source'].get('revision',1))
            if key not in keys:
                accepted.append(deepcopy(quote)); keys.add(key)
    return accepted


def holding_total(quotes):
    return sum((decimal(line['amount_rub']) for quote in quotes for line in quote['estimate']['lines']
                if line['code']=='reserve_holding'), Decimal(0))

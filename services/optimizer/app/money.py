"""Rubles: exact 12-place unit prices, HALF_UP line totals; v1 numeric compatibility."""
import json
import math
from contextvars import ContextVar
from decimal import Decimal, ROUND_HALF_UP, getcontext, InvalidOperation
from typing import Annotated
from pydantic import BeforeValidator, Field, PlainSerializer

getcontext().prec = max(getcontext().prec, 50)

EXACT_WIRE = ContextVar('exact_money_wire', default=False)
CENT = Decimal('0.01')
PRICE_QUANTUM = Decimal('0.000000000001')
MAX_AMOUNT = Decimal('999999999999.99')


def decimal(value):
    if isinstance(value, bool):
        raise ValueError('Денежное значение не может быть логическим')
    try:result = Decimal(str(value))
    except (ValueError,InvalidOperation):raise ValueError('Укажите корректное десятичное денежное значение') from None
    if not result.is_finite():
        raise ValueError('Денежное значение должно быть конечным')
    return result


def amount(value):
    try:return decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:raise ValueError('Денежное значение выходит за допустимый диапазон') from None


def wire(value):
    return format(value, 'f') if EXACT_WIRE.get() else float(value)


Money = Annotated[Decimal, Field(max_digits=24, decimal_places=12, ge=Decimal('-999999999999.999999999999'), le=Decimal('999999999999.999999999999'), allow_inf_nan=False), BeforeValidator(decimal), PlainSerializer(wire, when_used='json')]


def exact_json(value):
    if isinstance(value, Decimal): return format(value, 'f')
    if isinstance(value, dict): return {key:exact_json(item) for key,item in value.items()}
    if isinstance(value, (list,tuple)): return [exact_json(item) for item in value]
    return value


def json_dumps(value, **kwargs):
    return json.dumps(exact_json(value), **kwargs)


def money_values(value):
    """Decode exact monetary JSON for arithmetic without changing non-money metadata."""
    if isinstance(value, list): return [money_values(item) for item in value]
    if isinstance(value, dict):
        return {key:decimal(item) if key.endswith('_rub') and item is not None else money_values(item) for key,item in value.items()}
    return value


class MoneyWireMiddleware:
    def __init__(self, app, *, exact_prefix='/api/v3'):
        self.app, self.exact_prefix = app, exact_prefix

    async def __call__(self, scope, receive, send):
        token = EXACT_WIRE.set(scope.get('path', '').startswith(self.exact_prefix))
        if scope.get('type')!='http':
            await self.app(scope,receive,send)
            EXACT_WIRE.reset(token)
            return
        start = None
        chunks = []
        async def compatible_send(message):
            nonlocal start
            if message['type']=='http.response.start':
                headers = dict(message.get('headers',[]))
                if b'application/json' in headers.get(b'content-type',b'') and b'content-disposition' not in headers and message['status'] not in {204,304}:
                    start=message
                    return
            if message['type']=='http.response.body' and start is not None:
                chunks.append(message.get('body',b''))
                if message.get('more_body'):return
                body = b''.join(chunks)
                if not body:
                    await send(start)
                    await send(message)
                    return
                def numeric_compatibility(value):
                    if isinstance(value,list):return [numeric_compatibility(item) for item in value]
                    if isinstance(value,dict):
                        result = {}
                        for key,item in value.items():
                            if key in {'characteristics','details','common_base','hard_constraints','individual_operations'}:
                                result[key]=item
                                continue
                            if key.endswith('_rub') and item is not None and EXACT_WIRE.get() and isinstance(item,(int,float)) and not isinstance(item,bool):
                                item=format(decimal(item),'f')
                            elif key.endswith('_rub') and isinstance(item,str) and not EXACT_WIRE.get():
                                try:
                                    numeric = float(decimal(item))
                                    if math.isfinite(numeric):item=numeric
                                except (ValueError,ArithmeticError):pass
                            result[key]=numeric_compatibility(item)
                        return result
                    return value
                body=json.dumps(numeric_compatibility(json.loads(body)),ensure_ascii=False,separators=(',',':')).encode()
                headers=[(key,value) for key,value in start['headers'] if key.lower()!=b'content-length']
                await send({**start,'headers':headers+[(b'content-length',str(len(body)).encode())]})
                await send({**message,'body':body})
                return
            await send(message)
        try:
            await self.app(scope, receive, compatible_send)
        finally:
            EXACT_WIRE.reset(token)


def cent_value(value):
    result = decimal(value)
    if result != amount(result):raise ValueError('Сумма или бюджет задаются с точностью до копейки; цена единицы допускает 12 знаков')
    return result

Amount = Annotated[Decimal, Field(max_digits=14,decimal_places=2,ge=-MAX_AMOUNT,le=MAX_AMOUNT,allow_inf_nan=False), BeforeValidator(cent_value), PlainSerializer(wire,when_used='json')]

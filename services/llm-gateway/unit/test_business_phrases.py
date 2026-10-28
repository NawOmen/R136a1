import pytest
from app.agents import merge_facts
from app.schemas import RawExtraction, RawFact, SourceDescriptor


def merge(text, facts=(), warnings=()):
    source = SourceDescriptor(id='text', kind='text', name='Запрос', text=text)
    raw = RawExtraction(category='Бумажные стаканы', facts=[RawFact(source_id='text', confidence=.99, **f) for f in facts])
    props, conflicts, questions = merge_facts(raw, [source], list(warnings))
    return {p.key:p for p in props}, conflicts, questions


@pytest.mark.parametrize('phrase,value', [('60 тысяч рублей',60000),('60 тыс. рублей',60000),('1,5 млн ₽',1500000),('2 миллиона рублей',2000000)])
@pytest.mark.parametrize('model_value', ['omitted','literal','normalized'])
def test_explicit_budget_multipliers_with_original_citation(phrase,value,model_value):
    text = f'Бюджет {phrase}'
    facts = [] if model_value == 'omitted' else [dict(key='budget_rub', value=value if model_value == 'normalized' else phrase, evidence=text)]
    props,_,_=merge(text,facts)
    p=props['budget_rub']
    assert float(p.value)==value and p.status=='confirmed'
    assert p.sources[0].excerpt in text and p.sources[0].locator['located']


def test_omitted_quantity_and_budget_are_recovered_without_losing_conflicts():
    props, conflicts, _ = merge('Нужно 5 тысяч штук. Бюджет 60 тыс. рублей. Но другая версия: 6 тысяч штук.')
    assert props['quantity_units'].status=='needs_clarification'
    assert set(float(v) for v in conflicts[0].values)=={5000,6000}
    assert float(props['budget_rub'].value)==60000


def test_a_multiplier_cannot_confirm_the_unscaled_number_or_a_wrong_value():
    for value in (5,6000):
        props,_,_=merge('Нужно 5 тысяч штук', [dict(key='quantity_units',value=value,evidence='5 тысяч штук')])
        assert props['quantity_units'].status=='needs_clarification' and props['quantity_units'].value is None


def test_a_price_is_not_relabelled_as_a_budget():
    props,_,_=merge('Цена партии 60 тысяч рублей')
    assert 'budget_rub' not in props


@pytest.mark.parametrize('value,quote', [('2026-12-15','Нужно до 15.12.2026'),('15.12.26','Нужно до 15.12.26'),('2026-12-15','Нужно до 15.12.2026.')])
def test_grounded_calendar_date_replaces_missing_relative_lead_time(value,quote):
    props,_,questions=merge(quote,[dict(key='delivery_date',value=value,evidence=quote)])
    assert props['delivery_date'].value=='2026-12-15' and props['delivery_date'].status=='confirmed'
    assert 'lead_time_days' not in props and not any(q.key=='lead_time_days' for q in questions)


@pytest.mark.parametrize('value', ['2026-02-31','2026-12-16'])
def test_invalid_or_mismatched_delivery_date_never_suppresses_required_lead_time(value):
    props,_,questions=merge('Нужно до 15.12.2026',[dict(key='delivery_date',value=value,evidence='15.12.2026')])
    assert props['delivery_date'].status=='needs_clarification'
    assert any(q.key=='lead_time_days' for q in questions)


def test_security_warning_without_files_never_invents_unreadable_materials():
    _,_,questions=merge('Доставка Москва',[
        dict(key='quantity_units',value=200,evidence=''),dict(key='lead_time_days',value=5,evidence=''),
        dict(key='delivery_city',value='Москва',evidence='Москва')],['Обнаружена попытка изменить инструкции агента'])
    assert not any(q.key=='unreadable_materials' for q in questions)


def test_omitted_quantity_range_is_not_chosen_as_an_exact_order():
    props,_,_=merge('Нужно от 5 до 10 тысяч штук')
    assert props['quantity_units'].value is None

"""Версия 1 внутреннего сценарного анализа S16. Без сервисов, записей и LLM."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / 'packages/test-fixtures/business-analysis/v1.json'
COST_KEYS = ('goods_rub', 'delivery_rub', 'other_rub')
SCOPE_KEYS = ('category_id', 'specification', 'unit', 'tax_basis', 'destination', 'deadline')
PLATFORM_COST_KEYS = ('inference_rub', 'storage_rub', 'support_rub', 'document_review_rub', 'integration_rub')


def number(value, *, cents=False, maximum=Decimal('1000000000000')):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('Числа должны быть точными десятичными строками или целыми')
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError('Некорректное число') from None
    if not result.is_finite() or result < 0 or result > maximum or result.as_tuple().exponent < (-2 if cents else -12):
        raise ValueError('Число вне допустимого диапазона или точности')
    return result


def total(values):
    return None if any(v is None for v in values) else sum(values, Decimal(0))


def difference(first, second):
    return None if first is None or second is None else first - second


def money(value):
    return None if value is None else format(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP), '.2f')


def time_analysis(data):
    values = {key: number(data[key]) for key in ('manual_active_minutes', 'system_active_minutes',
        'correction_minutes', 'retry_minutes', 'manual_training_minutes', 'system_training_minutes',
        'manual_wait_minutes', 'system_wait_minutes', 'model_wait_minutes')}
    rate = number(data['hourly_rate_rub'], cents=True)
    system = total([values[k] for k in ('system_active_minutes', 'correction_minutes', 'retry_minutes')])
    steady = difference(values['manual_active_minutes'], system)
    manual_total = total([values['manual_active_minutes'], values['manual_training_minutes']])
    system_total = total([system, values['system_training_minutes']])
    first = difference(manual_total, system_total)
    labour = None if first is None or rate is None else first * rate / 60
    return {'steady_active_saving_minutes': None if steady is None else str(steady),
            'first_use_active_saving_minutes': None if first is None else str(first),
            'labour_equivalent_rub': money(labour),
            'manual_total_active_minutes': None if manual_total is None else str(manual_total),
            'system_total_active_minutes': None if system_total is None else str(system_total),
            'system_labour_cost_equivalent_rub': money(None if system_total is None or rate is None else system_total * rate / 60),
            'active_components_minutes': {k: None if v is None else str(v)
                                         for k,v in values.items() if 'wait' not in k},
            'waiting_minutes': {k: None if values[k] is None else str(values[k])
                               for k in ('manual_wait_minutes', 'system_wait_minutes', 'model_wait_minutes')}}, labour


def comparable(first, second):
    # An unknown scope cannot become comparable merely because both sides omit it.
    for key in SCOPE_KEYS:
        if not isinstance(first.get(key), str) or not first[key].strip() or first[key] != second.get(key):
            return False
    quantity, other = number(first.get('quantity')), number(second.get('quantity'))
    return first['tax_basis'] in ('same_inclusive', 'same_exclusive') and quantity is not None and quantity > 0 and quantity == other


def analyse_case(case):
    if case['outcome'] not in ('completed', 'blocked', 'abandoned'):
        raise ValueError('Неизвестный исход сценария')
    buyer, seller, platform, reserve = (case[k] for k in ('buyer', 'seller', 'platform', 'reserve'))
    matched = comparable(buyer['baseline']['scope'], buyer['system']['scope'])
    baseline, system = [total([number(quote['costs'][k], cents=True) for k in COST_KEYS])
                        for quote in (buyer['baseline'], buyer['system'])]
    completed = case['outcome'] == 'completed'
    saving = difference(baseline, system) if matched and completed else None
    bt, labour = time_analysis(buyer['time'])
    st, seller_labour = time_analysis(seller['time'])
    if not matched or not completed:
        labour = seller_labour = None
        for metrics in (bt, st):
            for key in ('steady_active_saving_minutes', 'first_use_active_saving_minutes', 'labour_equivalent_rub'):
                metrics[key] = None
    units = number(seller['incremental_units'])
    revenue = number(seller['unit_revenue_rub'])
    cost = number(seller['unit_cost_rub'])
    new_cost = number(seller['new_expenses_rub'], cents=True)
    if not completed:
        additional = Decimal(0)
    elif units == 0:
        additional = Decimal(0)
    elif units is None or revenue is None or cost is None or seller['tax_comparable'] is not True:
        additional = None
    else:
        additional = (revenue - cost) * units
    income = total([number(platform[k], cents=True) for k in ('subscription_income_rub', 'commission_income_rub')])
    operating_cost = total([number(platform[k], cents=True) for k in PLATFORM_COST_KEYS])
    operating_result = difference(income, operating_cost) if platform['tax_comparable'] is True else None
    development = number(platform['allocated_development_rub'], cents=True)
    acquisition = number(platform['allocated_acquisition_rub'], cents=True)
    holding, switching, loss_without, loss_with = [number(reserve[k], cents=True) for k in
        ('holding_rub', 'switching_rub', 'loss_without_rub', 'loss_with_rub')]
    probability = number(reserve['incident_probability'], maximum=Decimal(1))
    gain = difference(difference(loss_without, loss_with), switching)
    expected = None if probability is None or gain is None else difference(probability * gain, holding)
    threshold = None if holding is None or gain is None or gain <= 0 else holding / gain
    return {'id': case['id'], 'label': case['label'], 'outcome': case['outcome'],
        'buyer': {'comparable': matched, 'baseline_total_rub': money(baseline),
                  'system_total_rub': money(system), 'procurement_saving_rub': money(saving),
                  'procurement_saving_percent': money(None if saving is None or not baseline else saving / baseline * 100),
                  'time': bt, 'value_equivalent_rub': money(total([saving, labour]))},
        'seller': {'time': st, 'incremental_contribution_rub': money(additional),
                   'new_expenses_rub': money(new_cost),
                   'value_equivalent_rub': money(difference(total([seller_labour, additional]), new_cost))
                       if completed and seller['tax_comparable'] is True else None,
                   'payments_rub': money(number(seller['payments_rub'], cents=True))},
        'platform': {'gmv_rub': money(number(platform['gmv_rub'], cents=True)),
                     'scenario_income_rub': money(income), 'operating_cost_rub': money(operating_cost),
                     'operating_result_rub': money(operating_result),
                     'allocated_development_rub': money(development), 'allocated_acquisition_rub': money(acquisition),
                     'after_development_and_acquisition_rub': money(difference(operating_result, total([development, acquisition])))},
        'reserve': {'conditional_net_effect_rub': money(difference(gain, holding)),
                    'expected_effect_rub': money(expected),
                    'break_even_probability': None if threshold is None else str(threshold),
                    'uncovered_units': None if reserve['uncovered_units'] is None else str(number(reserve['uncovered_units'])),
                    'sensitivity_rub': {p: money(None if gain is None else difference(Decimal(p) * gain, holding))
                                        for p in ('0', '0.1', '0.5', '1')}}}


def catalogue_analysis(root=ROOT):
    registry_path = root / 'services/marketplace/app/category_registry.json'
    fixture_path = root / 'services/marketplace/unit/fixtures/category_stage01.json'
    registry = json.loads(registry_path.read_text())
    fixtures = json.loads(fixture_path.read_text())
    ids = [l['id'] for g in registry['groups'] for l in g['leaves']]
    fixture_ids = [f['category_id'] for f in fixtures]
    if len(ids) != len(set(ids)) or len(fixture_ids) != len(set(fixture_ids)) or set(ids) != set(fixture_ids):
        raise ValueError('Профили и предметные примеры должны покрывать ровно один и тот же каталог')
    tree = ast.parse((root / 'services/marketplace/app/assortment.py').read_text())
    source = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'ASSORTMENT' for t in n.targets))
    seeded = {(r[2], r[3]) for r in ast.literal_eval(source)}
    examples = {f['category_id']: f for f in fixtures}
    rows = []
    for group in registry['groups']:
        for leaf in group['leaves']:
            passport = leaf['technical_profile']['passport']
            example = examples[leaf['id']]
            if (example['category'], example['subcategory']) != (group['label'], leaf['label']):
                raise ValueError('Предметный пример относится к другому листу')
            rows.append({'id': leaf['id'], 'group': group['label'], 'label': leaf['label'],
                'admission_state': leaf['admission_state'],
                'required_fields': passport['identification']['required'],
                'units': passport['units']['allowed'], 'logistics_risk': passport['logistics']['risk'],
                'acceptance_checks': passport['acceptance']['checks'],
                'document_review_required': passport['documents']['review_required'],
                'repeat_revalidate': passport['repeat']['revalidate'],
                'example_missing_field': example['missing_field'],
                'example_incompatible_fields': sorted(k for k,v in example['negative'].items() if v != example['positive'].get(k)),
                'seeded_working_leaf': (group['label'], leaf['label']) in seeded,
                'routes': example['route'], 'test_refs': leaf['test_refs']})
    return {'registry_version': registry['registry_version'], 'groups': len(registry['groups']),
            'leaves': len(rows), 'seeded_working_leaves': sum(r['seeded_working_leaf'] for r in rows),
            'admission_states': dict(Counter(r['admission_state'] for r in rows)), 'categories': rows}


def build_report(data, root=ROOT):
    if type(data['schema_version']) is not int or data['schema_version'] != 1 or data['kind'] != 'team_scenario_assumptions' or data['currency'] != 'RUB':
        raise ValueError('Нужен внутренний рублёвый набор версии 1')
    cases = data['cases']
    ids = [c['id'] for c in cases]
    if not cases or len(ids) != len(set(ids)):
        raise ValueError('Сценарии должны иметь уникальные ID')
    catalogue = catalogue_analysis(root)
    leaves = {row['id']: row for row in catalogue['categories']}
    for case in cases:
        for side in ('baseline', 'system'):
            category = case['buyer'][side]['scope'].get('category_id')
            if category is not None and category not in leaves:
                raise ValueError('Категория сценария отсутствует в текущем каталоге')
        selected = case['buyer']['system']['scope'].get('category_id')
        if selected in leaves and leaves[selected]['admission_state'] == 'unsupported' and case['outcome'] == 'completed':
            raise ValueError('Неподдерживаемый лист не может иметь завершённый торговый сценарий')
    with localcontext() as context:
        context.prec = 50
        results = [analyse_case(c) for c in cases]
    return {'format': 1, 'method': 'business-analysis-1', 'kind': data['kind'], 'currency': 'RUB',
            'scope': 'Внутренние расчётные сценарии команды; числа — явно заданные допущения.',
            'catalogue': catalogue, 'case_count': len(results),
            'outcomes': dict(Counter(r['outcome'] for r in results)), 'cases': results}


def markdown(report):
    lines = ['# Сценарный анализ этапа 16', '', report['scope'], '',
             'Денежные результаты в рублях. null означает неизвестное или несопоставимое.', '',
             '| Сценарий | Исход | Покупатель: стоимость / время, ₽ | Поставщик: вклад / время, ₽ | Платформа: результат, ₽ | Резерв: ожидаемый эффект, ₽ |',
             '|---|---|---|---|---|---|']
    for r in report['cases']:
        show = lambda value: 'не определено' if value is None else value
        lines.append(f"| {r['id']}: {r['label']} | {r['outcome']} | {show(r['buyer']['value_equivalent_rub'])} | {show(r['seller']['value_equivalent_rub'])} | {show(r['platform']['operating_result_rub'])} | {show(r['reserve']['expected_effect_rub'])} |")
    lines.extend(['', '## Все листья текущего каталога', '',
        'Профили и предметные примеры анализируются для каждого листа. Число товаров и прохождение коммерческого пути — отдельные свойства.', '',
        '| ID / раздел / лист | Допуск | Обязательные поля | Единицы | Проверки приёмки | Рабочее наполнение |',
        '|---|---|---|---|---|---|'])
    for r in report['catalogue']['categories']:
        lines.append(f"| {r['id']} / {r['group']} / {r['label']} | {r['admission_state']} | {', '.join(r['required_fields'])} | {', '.join(r['units'])} | {', '.join(r['acceptance_checks'])} | {'есть' if r['seeded_working_leaf'] else 'профиль'} |")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--markdown', action='store_true')
    args = parser.parse_args()
    try:
        report = build_report(json.loads(args.input.read_text()))
        if args.markdown:
            sys.stdout.write(markdown(report))
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, OSError, StopIteration) as error:
        print('Анализ не выполнен: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

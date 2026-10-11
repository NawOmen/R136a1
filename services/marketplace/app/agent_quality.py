"""Reproducible expert comparison of immutable initial results.

A valid JSON or a human-confirmed current result is not correctness evidence.
Legacy runs without original evidence remain unassessed.
"""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select, text
from .models import AgentQualityEvaluation
from .schemas import RoleQualityBenchmarkOut, RoleQualityOut, RoleQualityRoleOut

METHOD = 'role-quality-2'
MIN_OBSERVATIONS = 5
BANK = Path(__file__).parent / 'benchmarks' / 'ru_tasks.json'
TERMINAL = {'buyer_agent': 'confirmed_by_user', 'seller_agent': 'completed'}


def bank_tasks():
    try: return json.loads(BANK.read_text(encoding='utf-8'))['tasks']
    except (OSError, ValueError, KeyError): return []


def bank_info():
    tasks = bank_tasks()
    return RoleQualityBenchmarkOut(tasks=len(tasks), available=bool(tasks),
        compares=['expected_category', 'critical_fields', 'conflicts_expected', 'questions_expected', 'forbidden_values', 'must_warn', 'price_must_not_change'])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def equivalent(actual, expected):
    if isinstance(actual, bool) or isinstance(expected, bool): return actual is expected
    try:
        left, right = Decimal(str(actual)), Decimal(str(expected))
        if left.is_finite() and right.is_finite(): return left == right
    except ArithmeticError: pass
    return isinstance(actual, str) and isinstance(expected, str) and actual.strip().casefold() == expected.strip().casefold()


def compare(initial, reference):
    """Critical denominator comes from the reviewed reference, never arbitrary properties."""
    props = {p.get('key'): p.get('value') for p in initial.get('properties', []) if isinstance(p, dict)}
    checks = []
    for key, expected in reference.get('critical_fields', {}).items():
        actual = props.get(key, initial.get(key))
        checks.append({'key': key, 'present': actual is not None and actual != '', 'correct': equivalent(actual, expected)})
    if 'expected_category' in reference:
        category = initial.get('category')
        if isinstance(category, dict): category = category.get('value') or category.get('name')
        checks.append({'key': 'category', 'present': bool(category), 'correct': equivalent(category, reference['expected_category'])})
    for key, collection in [('conflicts_expected', 'conflicts'), ('questions_expected', 'questions')]:
        if key in reference:
            checks.append({'key': key, 'present': collection in initial, 'correct': collection in initial and bool(initial.get(collection)) == reference[key]})
    if reference.get('must_warn'):
        checks.append({'key': 'must_warn', 'present': 'warnings' in initial, 'correct': any('попытка изменить' in str(w).casefold() for w in initial.get('warnings', []))})
    if reference.get('forbidden_values'):
        forbidden = {str(v).casefold() for v in reference['forbidden_values']}
        checks.append({'key': 'forbidden_values', 'present': 'properties' in initial,
            'correct': all(str(v).casefold() not in forbidden for v in props.values() if v is not None)})
    if reference.get('price_must_not_change'):
        # Gateway's extractor has no authority to produce a price mutation.
        checks.append({'key': 'price_must_not_change', 'present': True,
            'correct': not any(k in initial or k in props for k in ('price_rub', 'unit_price_rub', 'price_mutation'))})
    return {'checks': checks, 'total': len(checks), 'present': sum(c['present'] for c in checks),
        'correct': sum(c['correct'] for c in checks), 'method_version': METHOD}


async def runs_available(db):
    if not await db.scalar(text("SELECT to_regclass('agents.agent_runs') IS NOT NULL")): return False
    return bool(await db.scalar(text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='agents' AND table_name='agent_runs' AND column_name='company_id')")))


async def run_rows(db, *, since, company_id):
    if not await runs_available(db): return []
    columns = set((await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='agents' AND table_name='agent_runs'"))).scalars())
    initial = 'initial_result' if 'initial_result' in columns else 'NULL::jsonb AS initial_result'
    corrections = 'human_corrections' if 'human_corrections' in columns else 'NULL::integer AS human_corrections'
    sql = f"SELECT id, company_id, agent_type, state, error, duration_ms, estimated_cost_rub, model_version, prompt_version, used_route, {initial}, {corrections} FROM agents.agent_runs WHERE created_at >= :since"
    if company_id is not None: sql += ' AND company_id = CAST(:company_id AS uuid)'
    sql += ' ORDER BY created_at, id'
    return list((await db.execute(text(sql), {'since': since, 'company_id': company_id})).mappings())


async def role_quality(db, *, scope, company_id, window_days):
    since = datetime.now(timezone.utc)-timedelta(days=window_days)
    rows = await run_rows(db, since=since, company_id=company_id)
    run_ids = [r['id'] for r in rows]
    evaluations = list((await db.scalars(select(AgentQualityEvaluation).where(AgentQualityEvaluation.run_id.in_(run_ids)).order_by(AgentQualityEvaluation.created_at))).all()) if run_ids else []
    # The latest explicitly approved expert reference wins; prior evidence stays
    # in append-only history. Re-evaluation never multiplies the sample size.
    by_run = {}
    for e in evaluations: by_run.setdefault(e.run_id, []).append(e)
    clarified, blocked = set(), {}
    if run_ids and await db.scalar(text("SELECT to_regclass('agents.tool_calls') IS NOT NULL")):
        calls = (await db.execute(text('SELECT run_id, tool_name, status FROM agents.tool_calls WHERE run_id = ANY(:ids)'), {'ids': run_ids})).mappings()
        for call in calls:
            if call['tool_name'] == 'apply_user_clarification' and call['status'] == 'success': clarified.add(call['run_id'])
            if call['status'] in {'blocked', 'denied'}: blocked[call['run_id']] = blocked.get(call['run_id'], 0)+1
    groups = {}
    for row in rows:
        ev = by_run.get(row['id'], [])
        valid = [e for e in ev if isinstance(row['initial_result'],dict) and e.result_hash == digest(row['initial_result'])]
        chosen = valid[-1] if valid else None
        task_scope = chosen.task_scope if chosen else 'unverified'
        key = (row['agent_type'], row['model_version'], row['prompt_version'], row['used_route'], task_scope)
        groups.setdefault(key, []).append((row, chosen))
    roles = []
    for key, sample in sorted(groups.items(), key=lambda p: str(p[0])):
        role, model, prompt, route, task_scope = key
        successful = [r for r,e in sample if r['state'] == TERMINAL.get(role) and r['error'] is None]
        failed = [r for r,e in sample if r['state'] == 'failed' or r['error'] is not None]
        verified_terminal = [e for r,e in sample if e is not None and (r['state'] in {'failed', 'confirmed_by_user', 'completed', 'completed_with_fallback'})]
        evidence = verified_terminal
        evaluated = len(verified_terminal) >= MIN_OBSERVATIONS and model is not None and prompt is not None and route is not None
        total = sum(e.assessment['total'] for e in evidence); present = sum(e.assessment['present'] for e in evidence); correct = sum(e.assessment['correct'] for e in evidence)
        durations = [r['duration_ms'] for r,e in sample if r['duration_ms'] is not None]
        costs = [Decimal(str(r['estimated_cost_rub'])) for r,e in sample if r['estimated_cost_rub'] is not None]
        initial_known = [r for r,e in sample if isinstance(r['initial_result'], dict)]
        roles.append(RoleQualityRoleOut(role=role, passport='Паспорт модельной роли S04', cohort_key=digest(key), task_scope=task_scope,
            sample=len(sample), status='evaluated' if evaluated else 'not_evaluated', completed_runs=len(successful),
            completed_share_pct=round(len(successful)/len(sample)*100,1) if evaluated else None,
            expert_verified_runs=len(evidence), initial_result_known_runs=len(initial_known),
            critical_fields_total=total, critical_fields_confirmed=present, critical_fields_correct=correct,
            critical_completeness_pct=round(present/total*100,1) if evaluated and total else None,
            critical_correctness_pct=round(correct/total*100,1) if evaluated and total else None,
            conflicts_found=sum(len(r['initial_result'].get('conflicts') or []) for r in initial_known),
            clarification_runs=sum(r['id'] in clarified for r,e in sample),
            human_corrections=sum(r['human_corrections'] or 0 for r,e in sample if r['initial_result'] is not None),
            corrections_known_runs=len(initial_known), blocked_actions=sum(blocked.get(r['id'],0) for r,e in sample),
            open_runs=sum(r['state'] not in {'failed','confirmed_by_user','completed','completed_with_fallback'} for r,e in sample),
            failed_runs=len(failed), fallback_runs=sum(r['state']=='completed_with_fallback' for r,e in sample),
            timed_runs=len(durations), average_duration_ms=round(sum(durations)/len(durations),1) if durations else None,
            known_cost_rub=sum(costs,Decimal(0)) if costs else None, costed_share_pct=round(len(costs)/len(sample)*100,1),
            model_versions=[model] if model else [], prompt_versions=[prompt] if prompt else [],
            assessments=[{'id':str(e.id),'run_id':str(e.run_id),'source':e.source,'reference_hash':e.reference_hash,
                'result_hash':e.result_hash,'reviewer_user_id':str(e.reviewer_user_id),'assessment':e.assessment} for e in evidence]))
    notes = ['Когорта: роль, модель, промпт, маршрут и экспертно подтверждённый класс задачи; минимум 5 завершённых проверенных прогонов.',
        'Правильность и полнота сравниваются с эталоном по неизменяемому первому результату. Подтверждение пользователем не является проверкой правильности.',
        'Незавершённые процессы не успешны; fallback и технический сбой показаны отдельно. Старые результаты без исходного снимка не оценены.',
        'Исправления и конфликты относятся к исходной модельной роли. Кодовые черновики и блокировки допуска в неё не входят.',
        'Блокировки модели — только отклонённые вызовы её инструментов; бизнес-блокировки приведены отдельно в scorecard.',
        'Человеко-время не измеряется в часах. Стоимость — сумма известных оценок с покрытием, не полный биллинг. Итогового рейтинга нет.']
    if not await runs_available(db): notes.append('Журнал LLM Gateway недоступен: роли не оценены.')
    return RoleQualityOut(scope=scope,window_days=window_days,method_version=METHOD,min_observations=MIN_OBSERVATIONS,
        benchmark=bank_info(),roles=roles,notes=notes)

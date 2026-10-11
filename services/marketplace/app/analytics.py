"""Commercial evidence, order cohorts and independent execution-event periods.

Only frozen contractual terms enter comparable cohorts. Legacy evidence is
labelled incomplete; neither current catalogue data nor unknown costs fill it.
"""
import hashlib
import json
from datetime import datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException
from sqlalchemy import select, text
from .models import Deal, DealCostSnapshot, DealCostVersion, DealExecutionEvent, Need, Offer, ParticipantOrder
from .commerce import execution_totals, financials
from .matching import order_unit


def contract(item, need):
    snap = item.commercial_snapshot or {}
    frozen_need = snap.get('need') or {}
    product = snap.get('product') or {}
    estimate = snap.get('estimate') or {}
    unit = order_unit(frozen_need.get('characteristics', need.characteristics))
    category = frozen_need.get('category', need.category)
    evidence = {'category': category, 'subcategory': frozen_need.get('subcategory'),
        'characteristics': product.get('characteristics', frozen_need.get('characteristics')),
        'category_profile': product.get('category_profile', frozen_need.get('category_profile')),
        'product_id': (snap.get('offer') or {}).get('product_id'), 'unit': unit,
        'terms': estimate.get('terms'), 'product_name': product.get('name')}
    # Unknown specifications cannot make two legacy orders comparable.
    comparable = bool(snap and evidence['characteristics'] is not None and evidence['terms'])
    key = hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest() if comparable else f'unknown:{item.id}'
    lines = estimate.get('lines', [])
    product_name = product.get('name') or frozen_need.get('subcategory')
    return {'cohort_key': key, 'comparable_specification': comparable, 'category': category, 'unit': unit,
        'product_name': product_name, 'deadline_date': frozen_need.get('deadline_date'),
        'discount_rub': estimate.get('discount_rub'), 'charge_lines': lines,
        'estimate_complete': estimate.get('complete', False), 'source_refs': estimate.get('source'),
        'missing': estimate.get('missing', []) if snap else ['Историческая спецификация и смета неизвестны']}


def in_period(stamp, start, end):
    day = stamp.astimezone(timezone.utc).date()
    return (not start or day >= start) and (not end or day <= end)


def cost_details(costs, versions):
    return {'cost_revision': costs.revision if costs else None,
        'cost_tax_basis': costs.tax_basis if costs else 'unknown',
        'cost_source': costs.note if costs else None,
        'cost_effective_from': costs.effective_from if isinstance(costs, DealCostVersion) else costs.updated_at if costs else None,
        'cost_history': [{'revision': c.revision, 'unit_cost_rub': c.unit_cost_rub,
            'attributable_expenses_rub': c.attributable_expenses_rub, 'tax_basis': c.tax_basis,
            'source': c.note, 'effective_from': c.effective_from, 'recorded_at': c.recorded_at,
            'legacy_history_unknown': c.legacy_history_unknown} for c in versions]}


def execution_evidence(deal, events, versions, seller):
    """Link returns to immutable acceptances by deterministic FIFO allocation.

    This is an accounting allocation, not a claim about a physical batch.
    Physical batch evidence remains accessible in the fulfillment record.
    """
    accepted = []
    output = []
    for event in sorted(events, key=lambda e: (e.decided_at or e.created_at, str(e.id))):
        stamp = event.decided_at or event.created_at
        links = []
        if event.kind == 'acceptance' and event.status == 'confirmed':
            accepted.append([event.id, event.units])
        if event.kind == 'return' and event.status == 'confirmed':
            rest = event.units
            for slot in accepted:
                quantity = min(rest, slot[1])
                if quantity:
                    links.append({'acceptance_event_id': slot[0], 'units': quantity, 'allocation': 'FIFO'})
                    slot[1] -= quantity
                    rest -= quantity
            if rest:
                links.append({'acceptance_event_id': None, 'units': rest, 'allocation': 'legacy_unknown'})
        applicable = [c for c in versions if c.effective_from <= stamp]
        cost = max(applicable, key=lambda c: c.revision) if applicable else None
        signed = event.units if event.kind == 'acceptance' else -event.units if event.kind == 'return' else 0
        result = {'event_id': event.id, 'deal_id': deal.id, 'kind': event.kind, 'status': event.status,
            'units': event.units, 'occurred_at': stamp, 'order_created_at': deal.created_at,
            'note': event.note, 'source_acceptances': links,
            'goods_value_rub': (deal.unit_price_rub * signed).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                if deal.unit_price_rub is not None and event.status == 'confirmed' else None}
        if seller:
            result.update(cost_revision=cost.revision if cost else None,
                          cost_history_unknown=not cost or cost.legacy_history_unknown)
        output.append(result)
    return output


def reliability(pairs, event_map, built_at):
    outcomes = {'on_time': 0, 'late': 0, 'overdue_open': 0, 'cancelled': 0, 'returned': 0, 'open': 0, 'unknown_deadline': 0}
    for deal, need in pairs:
        events = event_map.get(deal.id, [])
        totals = execution_totals(deal, events)
        raw = ((deal.commercial_snapshot or {}).get('need') or {}).get('deadline_date')
        if not raw:
            outcomes['unknown_deadline'] += 1
            continue
        deadline = datetime.fromisoformat(str(raw)).date()
        if totals['returned_units']:
            outcome = 'returned'
        elif totals['cancelled_units']:
            outcome = 'cancelled'
        elif totals['open_units']:
            outcome = 'overdue_open' if built_at.date() > deadline else 'open'
        else:
            stamps = [e.decided_at or e.created_at for e in events if e.kind == 'acceptance' and e.status == 'confirmed']
            outcome = 'on_time' if stamps and max(stamps).date() <= deadline else 'late'
        outcomes[outcome] += 1
    decided = sum(outcomes[k] for k in ('on_time', 'late', 'overdue_open', 'cancelled', 'returned'))
    return {'method_version': 'execution-reliability-1', 'cohort': 'filtered_direct_order_created_at',
        'orders': len(pairs), 'outcomes': outcomes, 'known_outcomes': decided, 'min_observations': 5,
        'status': 'evaluated' if decided >= 5 else 'not_evaluated',
        'on_time_share_pct': round(outcomes['on_time'] / decided * 100, 1) if decided >= 5 else None}


async def commercial_report(db, company_id, role, *, start=None, end=None, category=None,
                            status=None, counterparty=None, product=None, source='all'):
    if start and end and start > end:
        raise HTTPException(422, 'Начало периода должно быть не позже окончания')
    if source not in ('all', 'direct', 'group'):
        raise HTTPException(422, 'Источник заказа: all, direct или group')
    built_at = datetime.now(timezone.utc)
    owner = Deal.seller_company_id if role == 'seller' else Deal.buyer_company_id
    all_pairs = list((await db.execute(select(Deal, Need).join(Need, Need.id == Deal.need_id).where(owner == company_id))).all())
    group_owner = ParticipantOrder.seller_company_id if role == 'seller' else ParticipantOrder.buyer_company_id
    group_pairs = list((await db.execute(select(ParticipantOrder, Need).join(Need, Need.id == ParticipantOrder.need_id)
        .where(group_owner == company_id, ParticipantOrder.status != 'superseded'))).all())
    other_key = 'buyer_company_id' if role == 'seller' else 'seller_company_id'
    other_ids = list({getattr(d, other_key) for d, _ in all_pairs + group_pairs})
    names = dict((await db.execute(text('SELECT id, display_name FROM auth.companies WHERE id = ANY(:ids)'), {'ids': other_ids})).all()) if other_ids else {}
    def matches(item, need):
        frozen = contract(item, need)
        return ((not status or item.status == status) and (not category or frozen['category'] == category)
            and (not counterparty or counterparty.strip().casefold() in names.get(getattr(item, other_key), '').casefold())
            and (not product or product.strip().casefold() in (frozen['product_name'] or '').casefold()))
    filtered = [(d, n) for d, n in all_pairs if matches(d, n)] if source != 'group' else []
    pairs = sorted([(d, n) for d, n in filtered if in_period(d.created_at, start, end)], key=lambda p: p[0].created_at, reverse=True)
    ids = [d.id for d, _ in filtered]
    all_events = list((await db.scalars(select(DealExecutionEvent).where(DealExecutionEvent.deal_id.in_(ids), DealExecutionEvent.created_at <= built_at))).all()) if ids else []
    event_map = {}
    for event in all_events: event_map.setdefault(event.deal_id, []).append(event)
    versions_map = {}
    if ids and role == 'seller':
        for cost in (await db.scalars(select(DealCostVersion).where(DealCostVersion.deal_id.in_(ids), DealCostVersion.recorded_at <= built_at).order_by(DealCostVersion.revision))).all():
            versions_map.setdefault(cost.deal_id, []).append(cost)
    legacy_costs = {c.deal_id: c for c in (await db.scalars(select(DealCostSnapshot).where(DealCostSnapshot.deal_id.in_(ids)))).all()} if ids and role == 'seller' else {}
    evidence_map = {d.id: [{**e, 'unit': contract(d,n)['unit'], 'category': contract(d,n)['category']} for e in execution_evidence(d, event_map.get(d.id, []), versions_map.get(d.id, []), role == 'seller')] for d, n in filtered}
    rows = []
    for deal, need in pairs:
        totals = execution_totals(deal, event_map.get(deal.id, []))
        versions = versions_map.get(deal.id, [])
        applicable = [c for c in versions if c.effective_from <= built_at]
        costs = max(applicable, key=lambda c: c.revision) if applicable else legacy_costs.get(deal.id)
        values = financials(deal, totals, costs)
        if role == 'buyer':
            values = {k: v for k, v in values.items() if k in {'unit_price_rub', 'ordered_value_rub', 'delivery_price_rub', 'net_goods_revenue_rub', 'payments_rub', 'revenue_tax_basis'}}
        else: values.update(cost_details(costs, versions))
        rows.append({'deal_id': deal.id, 'created_at': deal.created_at, 'status': deal.status,
            **contract(deal, need), **totals, **values, 'events': evidence_map[deal.id]})
    aggregate = {}
    keys = ('ordered_value_rub', 'net_goods_revenue_rub', 'cost_of_goods_rub', 'gross_profit_rub', 'attributable_expenses_rub', 'contribution_rub') if role == 'seller' else ('ordered_value_rub', 'net_goods_revenue_rub')
    for key in keys:
        known = [r[key] for r in rows if r[key] is not None]
        aggregate[key] = sum(known, Decimal(0)) if rows and len(known) == len(rows) else None
        aggregate[f'{key}_known_orders'] = len(known)
    cohorts = {}
    monthly = {}
    for row in rows:
        if row['net_units'] >= 0 and row['net_goods_revenue_rub'] is not None and row['comparable_specification']:
            slot = cohorts.setdefault(row['cohort_key'], {'unit': row['unit'], 'value': Decimal(0), 'units': 0, 'accepted': 0, 'product_name': row['product_name']})
            slot['value'] += row['net_goods_revenue_rub']; slot['units'] += row['net_units']; slot['accepted'] += row['accepted_units']
        month = row['created_at'].strftime('%Y-%m')
        slot = monthly.setdefault(month, {'orders': 0, 'value': Decimal(0), 'known': 0, 'units': 0, 'keys': set(), 'unit': row['unit']})
        slot['orders'] += 1; slot['keys'].add(row['cohort_key']); slot['units'] += row['net_units']
        if row['net_goods_revenue_rub'] is not None: slot['known'] += 1; slot['value'] += row['net_goods_revenue_rub']
    average_prices = [{'cohort_key': key, 'unit': s['unit'], 'product_name': s['product_name'], 'accepted_units': s['accepted'], 'net_units': s['units'],
        'average_unit_price_rub': (s['value'] / s['units']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} for key, s in sorted(cohorts.items()) if s['units']>0]
    monthly_rows = [{'month': month, 'orders_count': s['orders'], 'accepted_value_rub': s['value'] if s['known'] == s['orders'] else None,
        'known_value_rub': s['value'] if s['known'] else None, 'value_known_orders': s['known'],
        'accepted_units': s['units'] if len(s['keys']) == 1 else None, 'unit': s['unit'] if len(s['keys']) == 1 else None}
        for month, s in sorted(monthly.items())]
    group_rows = [{'order_id': d.id, 'coalition_id': d.coalition_id, 'created_at': d.created_at, 'status': d.status,
        'units': d.units, 'contract_value_rub': d.total_price_rub, 'payments_rub': None, **contract(d, n)}
        for d, n in group_pairs if source != 'direct' and matches(d, n) and in_period(d.created_at, start, end)]
    oq = select(Offer).join(Need, Need.id == Offer.need_id).where((Offer.company_id if role == 'seller' else Need.company_id) == company_id)
    if start: oq = oq.where(Offer.created_at >= datetime.combine(start, time.min, tzinfo=timezone.utc))
    if end: oq = oq.where(Offer.created_at <= datetime.combine(end, time.max, tzinfo=timezone.utc))
    if category: oq = oq.where(Need.category == category)
    offers = list((await db.scalars(oq)).all())
    rejected = sum(o.status == 'rejected' for o in offers); selected = sum(o.status == 'selected' for o in offers)
    opened = sum(o.status == 'sent' and (o.valid_until is None or o.valid_until >= built_at.date()) for o in offers)
    known = rejected + selected
    period_events = [e for events in evidence_map.values() for e in events if in_period(e['occurred_at'], start, end)]
    historical = bool(end and any(e['occurred_at'].date() > end for d, _ in pairs for e in evidence_map[d.id])) or bool(end and any(c.recorded_at.date() > end for d, _ in pairs for c in versions_map.get(d.id, [])))
    return {'company_id': company_id, 'role': role, 'method_version': 'commercial-analytics-2',
        'period_basis': 'order_created_at_utc', 'event_period_basis': 'decided_at_or_created_at_utc', 'built_at': built_at,
        'historical_recalculated': historical,
        'filters': {'start': start.isoformat() if start else None, 'end': end.isoformat() if end else None,
            'category': category or None, 'status': status or None, 'counterparty': counterparty or None, 'product': product or None, 'source': source},
        'orders_count': len(rows), 'orders': rows, 'totals': aggregate, 'payments_rub': None,
        'offers_count': len(offers), 'rejected_offers_count': rejected,
        'rejection_rate': {'offers_total': len(offers), 'rejected': rejected, 'selected': selected, 'open': opened,
            'stale': len(offers)-known-opened, 'known_outcomes': known, 'rate_pct': round(rejected/known*100, 1) if known else None},
        'average_prices': average_prices, 'monthly': monthly_rows, 'group_orders_count': len(group_rows), 'group_orders': group_rows,
        'period_events': period_events, 'reliability': reliability(pairs, event_map, built_at),
        'explanation': 'Заказы отобраны по созданию (UTC, обе даты включительно), исполнение — на время построения. События периода показаны отдельно, включая заказы прошлого периода. Приёмка старого заказа остаётся в прошлом периоде создания. Возвраты связаны с исходной приёмкой учётным распределением FIFO; это не идентификатор физической партии. Исторический пересчёт отмечен явно. CSV со снимком сохраняет данные экрана. Средние цены — после возвратов, внутри одной замороженной спецификации и условий; неизвестные спецификации не сравниваются. Неполные месячные суммы и неизвестная налоговая база не дают полной суммы или прибыли. Прочие затраты относятся на заказ целиком; версии затрат сохраняются. Групповые обязательства не удваивают выручку. Платежи и чистая прибыль не рассчитываются. Отказы — отдельная когорта предложений по созданию, независимо от фильтров заказов.'}

"""Confirmed execution arithmetic. Never infer payment or costs from an order."""
from decimal import Decimal, ROUND_HALF_UP


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def execution_totals(deal, events):
    totals = {kind: sum(e.units for e in events if e.kind == kind and e.status == "confirmed")
              for kind in ("acceptance", "return", "cancellation")}
    return {
        "ordered_units": deal.units,
        "accepted_units": totals["acceptance"],
        "returned_units": totals["return"],
        "cancelled_units": totals["cancellation"],
        "net_units": totals["acceptance"] - totals["return"],
        "open_units": deal.units - totals["acceptance"] - totals["cancellation"],
    }


def financials(deal, totals, costs=None):
    price = deal.unit_price_rub
    revenue = money(price * totals["net_units"]) if price is not None else None
    cost = money(costs.unit_cost_rub * totals["net_units"]) if costs and costs.unit_cost_rub is not None else None
    gross = revenue - cost if revenue is not None and cost is not None else None
    expenses = costs.attributable_expenses_rub if costs else None
    return {
        "unit_price_rub": price, "ordered_value_rub": money(deal.total_price_rub),
        "delivery_price_rub": deal.delivery_price_rub,
        "net_goods_revenue_rub": revenue, "cost_of_goods_rub": cost,
        "gross_profit_rub": gross, "attributable_expenses_rub": expenses,
        "contribution_rub": gross - expenses if gross is not None and expenses is not None else None,
        "payments_rub": None,
    }


def product_specification_hash(product):
    import hashlib
    import json
    value = {"category": product.category, "subcategory": product.subcategory,
             "characteristics": product.characteristics, "moq_units": product.moq_units}
    # Preserve exact legacy hashes; never pretend an unknown profile was current.
    profile = getattr(product, "category_profile", None)
    if profile is not None:
        value["category_profile"] = profile
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

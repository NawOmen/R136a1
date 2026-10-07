import hashlib
import json
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    CapabilityPassport,
    CapacityEntry,
    Coalition,
    CoalitionMember,
    CompatibilityProfile,
    GroupOffer,
    MarketOpportunity,
    MatchEvent,
    Need,
    Offer,
)
from .resources import occupies, reservations

COMMON_KEYS = {
    "volume_ml",
    "body_material",
    "material",
    "inner_coating",
    "coating",
    "top_diameter_mm",
    "bottom_diameter_mm",
}
INDIVIDUAL_KEYS = {"print", "logo", "packaging"}
HARD_KEYS = {"food_contact", "tr_ts_005_2011", "mandatory_requirements"}
FLEXIBLE_KEYS = {"allowed_analogues", "volume_tolerance", "deadline_tolerance_days"}
ACTIVE_NEED_STATUSES = {
    "open_for_offers",
    "waiting_for_match",
    "coalition_candidate",
    "awaiting_approvals",
}


def need_is_current(need: Need, today: date | None = None) -> bool:
    """Срок поставки и актуальности включают указанный день."""
    today = today or date.today()
    return need.deadline_date >= today and (need.valid_until is None or need.valid_until >= today)


def order_unit(characteristics: dict | None) -> str:
    value = str((characteristics or {}).get("unit") or (characteristics or {}).get("единица измерения") or "шт").strip().lower().rstrip(".") or "шт"
    return "шт" if value in {"шт", "штука", "штуки", "штук"} else value


def offer_unit_price(offer: Offer, volume_units: int) -> float:
    price = offer.price_rub
    tiers = sorted(
        (
            item
            for item in (offer.price_tiers or [])
            if isinstance(item, dict)
            and isinstance(item.get("min_units"), int)
            and isinstance(item.get("unit_price_rub"), (int, float))
        ),
        key=lambda item: item["min_units"],
    )
    for tier in tiers:
        if volume_units >= tier["min_units"]:
            price = float(tier["unit_price_rub"])
    return price


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _need_parts(need: Need) -> tuple[dict, dict, dict, dict]:
    characteristics = need.characteristics or {}
    common = {key: order_unit(characteristics) if key == "unit" else characteristics[key] for key in sorted(characteristics)
              if key not in INDIVIDUAL_KEYS | HARD_KEYS | FLEXIBLE_KEYS}
    common.setdefault("unit", "шт")
    hard = {key: characteristics[key] for key in sorted(HARD_KEYS) if key in characteristics}
    flexible = {key: characteristics[key] for key in sorted(FLEXIBLE_KEYS) if key in characteristics}
    individual = {
        key: characteristics[key]
        for key in sorted(characteristics)
        if key in INDIVIDUAL_KEYS
    }
    return common, hard, flexible, individual


def _tokens(value: str) -> set[str]:
    return {item for item in re.findall(r"[а-яёa-z0-9]+", value.lower()) if len(item) > 2}


def _passport_matches(passport: CapabilityPassport, category: str, common: dict) -> bool:
    corpus = " ".join(
        str(item)
        for collection in (
            passport.technologies,
            passport.materials,
            passport.completed_order_types,
        )
        for item in (collection or [])
    ).lower()
    category_tokens = _tokens(category)
    material_values = " ".join(
        str(value)
        for key, value in common.items()
        if key in {"body_material", "material", "inner_coating", "coating"}
    ).lower()
    return bool(category_tokens & _tokens(corpus)) or any(
        token in corpus for token in _tokens(material_values)
    )


async def _active_needs(db: AsyncSession) -> list[Need]:
    today = date.today()
    needs = (
        await db.execute(
            select(Need)
            .where(Need.status.in_(ACTIVE_NEED_STATUSES), Need.visibility == "open_anonymized")
            .order_by(Need.created_at.desc())
        )
    ).scalars().all()
    result = []
    seen = set()
    for need in needs:
        if not need_is_current(need, today):
            need.status = "expired"
            need.no_match_reason = "Срок актуальности карточки истёк"
            continue
        signature = (
            need.company_id,
            need.category.strip().lower(),
            _canonical_json(need.characteristics or {}),
            need.volume_units, need.deadline_date, need.valid_until, need.delivery_address_id,
            need.budget_rub, need.visibility,
        )
        if signature in seen:
            continue
        seen.add(signature)
        result.append(need)
    return result


async def _has_direct_match(db: AsyncSession, need: Need) -> tuple[bool, str]:
    offers = (
        await db.execute(
            select(Offer).where(Offer.need_id == need.id, Offer.status == "sent")
        )
    ).scalars().all()
    days_left = max(0, (need.deadline_date - date.today()).days)
    for offer in offers:
        total = (
            offer_unit_price(offer, need.volume_units) * need.volume_units
            + offer.delivery_cost_rub
        )
        if (
            offer.moq_units <= need.volume_units <= offer.available_units
            and offer.lead_time_days <= days_left
            and (offer.valid_until is None or offer.valid_until >= date.today())
            and (need.budget_rub is None or total <= need.budget_rub)
        ):
            return True, ""
    if offers:
        return False, "Предложения есть, но они не соблюдают объём, MOQ, бюджет или срок"
    passports = (
        await db.execute(select(CapabilityPassport).where(CapabilityPassport.min_order_units.is_not(None)))
    ).scalars().all()
    moqs = [
        item.min_order_units
        for item in passports
        if item.min_order_units and _passport_matches(item, need.category, _need_parts(need)[0])
    ]
    if moqs and min(moqs) > need.volume_units:
        return False, f"Не достигнут минимальный объём производителя (MOQ {min(moqs):,} {order_unit(need.characteristics)})".replace(",", " ")
    return False, "Пока нет выполнимого предложения от подходящего производителя"


async def _build_coalitions(db: AsyncSession, needs: list[Need]) -> None:
    groups: dict[tuple[str, str, str], list[Need]] = defaultdict(list)
    for need in needs:
        common, hard, _, _ = _need_parts(need)
        groups[(need.category.strip().lower(), _canonical_json(common), _canonical_json(hard))].append(need)

    passports = (await db.execute(select(CapabilityPassport))).scalars().all()
    for (_, common_json, hard_json), members in groups.items():
        distinct_companies = {item.company_id for item in members}
        if len(members) < 2 or len(distinct_companies) < 2:
            continue
        members = sorted(members, key=lambda item: str(item.id))
        total_units = sum(item.volume_units for item in members)
        compatible_passports = [
            item
            for item in passports
            if _passport_matches(item, members[0].category, json.loads(common_json))
            and item.company_id not in distinct_companies
            and (item.min_order_units is None or total_units >= item.min_order_units)
            and (item.max_order_units is None or total_units <= item.max_order_units)
        ]
        if not compatible_passports:
            continue
        compatible_passports.sort(key=lambda item: (item.min_order_units or 0, str(item.company_id)))
        passport = compatible_passports[0]
        identity = {
            "need_ids": [str(item.id) for item in members],
            "producer_company_id": str(passport.company_id),
            "common": json.loads(common_json),
            "hard": json.loads(hard_json),
        }
        digest = hashlib.sha256(_canonical_json(identity).encode()).hexdigest()
        profile = (
            await db.execute(select(CompatibilityProfile).where(CompatibilityProfile.input_hash == digest))
        ).scalar_one_or_none()
        if profile is None:
            individual_parts = {
                str(item.id): _need_parts(item)[3]
                for item in members
            }
            flexible = {
                str(item.id): _need_parts(item)[2]
                for item in members
            }
            profile = CompatibilityProfile(
                category=members[0].category,
                common_base=json.loads(common_json),
                hard_constraints=json.loads(hard_json),
                flexible_parameters=flexible,
                individual_parts=individual_parts,
                input_hash=digest,
            )
            db.add(profile)
            await db.flush()
        existing = (
            await db.execute(
                select(Coalition).where(
                    Coalition.compatibility_profile_id == profile.id,
                    Coalition.status.not_in(("cancelled", "expired")),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            coalition = Coalition(
                compatibility_profile_id=profile.id,
                producer_company_id=passport.company_id,
                category=members[0].category,
                combined_volume_units=total_units,
                target_moq_units=passport.min_order_units,
                status="candidate",
                explanation=[
                    "Общая производственная основа и жёсткие ограничения совпадают",
                    f"Общий объём {total_units:,} {order_unit(members[0].characteristics)} достигает MOQ {passport.min_order_units or 0:,} {order_unit(members[0].characteristics)}".replace(",", " "),
                    "Индивидуальная печать, упаковка и логистика будут рассчитаны отдельно",
                ],
            )
            db.add(coalition)
            await db.flush()
            for need in members:
                db.add(
                    CoalitionMember(
                        coalition_id=coalition.id,
                        need_id=need.id,
                        buyer_company_id=need.company_id,
                        units=need.volume_units,
                        individual_operations=_need_parts(need)[3],
                    )
                )
                need.status = "coalition_candidate"
                need.no_match_reason = None


async def _rebuild_opportunities(db: AsyncSession, needs: list[Need]) -> None:
    passports = (await db.execute(select(CapabilityPassport))).scalars().all()
    companies = (
        await db.execute(
            text("SELECT id FROM auth.companies WHERE country = 'RU' AND verification_status = 'verified'")
        )
    ).scalars().all()
    verified = set(companies)
    grouped: dict[tuple[str, str], list[Need]] = defaultdict(list)
    for need in needs:
        unit = order_unit(need.characteristics)
        grouped[(need.category.strip().lower(), unit)].append(need)

    active_keys = set()
    for passport in passports:
        if passport.company_id not in verified:
            continue
        for (_, unit), category_needs in grouped.items():
            category = category_needs[0].category
            common = _need_parts(category_needs[0])[0]
            if not _passport_matches(passport, category, common):
                continue
            total_demand = sum(item.volume_units for item in category_needs)
            buyer_count = len({item.company_id for item in category_needs})
            offers = (
                await db.execute(
                    select(Offer).join(Need, Offer.need_id == Need.id).where(
                        Need.id.in_([item.id for item in category_needs]),
                        Offer.status == "sent",
                        (Offer.valid_until.is_(None) | (Offer.valid_until >= date.today())),
                    )
                )
            ).scalars().all()
            # Count only the actual members of a current, feasible group proposal.
            # A proposal's upper capacity is not delivered demand for unrelated buyers.
            covered_ids = set((await db.scalars(
                select(CoalitionMember.need_id)
                .join(Coalition, Coalition.id == CoalitionMember.coalition_id)
                .join(GroupOffer, GroupOffer.coalition_id == Coalition.id)
                .where(CoalitionMember.need_id.in_([item.id for item in category_needs]),
                       Coalition.status == "awaiting_approvals", GroupOffer.status == "preliminary",
                       GroupOffer.fill_deadline >= date.today(),
                       GroupOffer.min_total_units <= Coalition.combined_volume_units,
                       GroupOffer.max_total_units >= Coalition.combined_volume_units)
            )).all())
            supplied = sum(item.volume_units for item in category_needs if item.id in covered_ids)
            unmet = max(0, total_demand - supplied)
            active_keys.add((passport.company_id, category, unit))
            opportunity = (
                await db.execute(
                    select(MarketOpportunity).where(
                        MarketOpportunity.company_id == passport.company_id,
                        MarketOpportunity.category == category,
                        MarketOpportunity.unit == unit,
                    )
                )
            ).scalar_one_or_none()
            if opportunity is None:
                opportunity = MarketOpportunity(company_id=passport.company_id, category=category, unit=unit, score=0,
                    competition_level="нет", saturation_risk="низкий", unmet_volume_units=0,
                    buyers_count=0, need_ids=[], reasons=[], missing_data=[])
                db.add(opportunity)
            if unmet == 0:
                opportunity.status = "saturated"
                opportunity.score = 0
                opportunity.unmet_volume_units = 0
                opportunity.reasons = ["Действующее предложение уже покрывает подтверждённый спрос"]
                continue
            supply_ratio = min(1, supplied / total_demand) if total_demand else 1
            volume_factor = min(1, unmet / 50_000)
            share_factor = unmet / total_demand
            capacity_entries = (await db.scalars(select(CapacityEntry).where(
                CapacityEntry.company_id == passport.company_id,
                CapacityEntry.date >= date.today(),
                CapacityEntry.date <= max(item.deadline_date for item in category_needs),
                CapacityEntry.category.in_(["", category]),
                CapacityEntry.unit == unit,
            ))).all()
            held = await reservations(db, passport.company_id) if capacity_entries else []
            recorded_capacity = sum(max(0, entry.available_units - sum(row.units for row in held
                if row.capacity_entry_id == entry.id and occupies(row))) for entry in capacity_entries) if capacity_entries else None
            capacity_limit = (
                recorded_capacity
                if recorded_capacity is not None
                else passport.max_order_units
            )
            capacity_ok = (
                (passport.min_order_units is None or total_demand >= passport.min_order_units)
                and (capacity_limit is None or total_demand <= capacity_limit)
            )
            logistics_factor = 1 if passport.delivery_regions else 0.5
            factors = {
                "confirmed_unmet_volume": volume_factor,
                "share_without_feasible_offer": share_factor,
                "passport_match": 1,
                "moq_and_capacity": 1 if capacity_ok else 0.3,
                "logistics": logistics_factor,
                "competition_and_saturation": 1 - supply_ratio,
                "data_quality": 1,
            }
            weights = {
                "confirmed_unmet_volume": 0.25,
                "share_without_feasible_offer": 0.20,
                "passport_match": 0.20,
                "moq_and_capacity": 0.15,
                "logistics": 0.10,
                "competition_and_saturation": 0.05,
                "data_quality": 0.05,
            }
            opportunity.score = round(100 * sum(factors[key] * weights[key] for key in weights))
            opportunity.competition_level = "нет" if not offers else ("низкая" if len(offers) <= 2 else "высокая")
            opportunity.saturation_risk = "низкий" if supply_ratio < 0.5 else "средний"
            opportunity.unmet_volume_units = unmet
            opportunity.buyers_count = buyer_count
            opportunity.need_ids = [str(item.id) for item in category_needs]
            opportunity.reasons = [
                "Есть подтверждённый незакрытый спрос",
                "Capability Passport соответствует категории и материалам",
                "Расчёт не является гарантией продаж или прибыли",
            ]
            opportunity.missing_data = ["Себестоимость и целевая маржа производителя"]
            opportunity.status = "active"

    existing = (await db.execute(select(MarketOpportunity))).scalars().all()
    for opportunity in existing:
        if (opportunity.company_id, opportunity.category, opportunity.unit) not in active_keys:
            opportunity.status = "inactive"


async def run_market_rematch(
    db: AsyncSession,
    event_type: str,
    entity_id: uuid.UUID | None,
    payload: dict | None = None,
) -> None:
    event = MatchEvent(
        event_type=event_type,
        entity_id=entity_id,
        payload=payload or {},
        status="processing",
    )
    db.add(event)
    await db.flush()
    needs = await _active_needs(db)
    unmatched_needs = []
    for need in needs:
        matched, reason = await _has_direct_match(db, need)
        if matched:
            need.status = "open_for_offers"
            need.no_match_reason = None
        elif need.status not in {"awaiting_approvals", "matched"}:
            need.status = "waiting_for_match"
            need.no_match_reason = reason
            unmatched_needs.append(need)
        elif need.status == "awaiting_approvals":
            unmatched_needs.append(need)
    await _build_coalitions(db, unmatched_needs)
    await _rebuild_opportunities(db, unmatched_needs)
    event.status = "processed"
    event.payload = {**event.payload, "processed_at": datetime.now(timezone.utc).isoformat()}

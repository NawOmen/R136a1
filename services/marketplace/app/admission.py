"""Единая проверка категорийного допуска перед принятием обязательств.

Публикация товара, прямая сделка, групповое обязательство, резерв и замена
поставщика используют одну и ту же проверку. Черновики и предварительные
расчёты допускаются с предупреждениями; момент обязательства — нет.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .category_admission import evaluate_admission
from .models import Document, Product, CapabilityPassport
from .schemas import CategoryAdmissionOut, RequirementStatusOut

BUYER_CHECKLIST_NOTE = (
    "Чек-лист показывает, какие обязательные доказательства проверены у продавца. "
    "Он не заменяет проверку конкретной партии при приёмке и не является юридическим заключением."
)


@dataclass
class SpecificationCheck:
    """Спецификация, к которой нужно проверить документы продавца."""

    category: str
    subcategory: str | None = None
    characteristics: dict = field(default_factory=dict)
    moq_units: int = 1
    label: str = ""
    product_id: uuid.UUID | None = None
    volume_units: int | None = None
    category_profile: dict | None = None


async def company_documents(db: AsyncSession, company_id: uuid.UUID) -> list[Document]:
    result = await db.execute(
        select(Document).where(Document.company_id == company_id).order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


def _requirement_out(item) -> RequirementStatusOut:
    return RequirementStatusOut(
        code=item.code,
        title=item.title,
        legal_reference=item.legal_reference,
        blocking=item.blocking,
        state=item.state,
        state_label=item.state_label,
        seller_hint=item.seller_hint,
        buyer_note=item.buyer_note,
        document_ids=list(item.document_ids),
        scope_note=item.scope_note,
    )


async def company_admission(
    db: AsyncSession,
    company_id: uuid.UUID,
    category: str,
    subcategory: str | None,
    *,
    characteristics: dict | None = None,
    moq_units: int = 1,
) -> CategoryAdmissionOut:
    """Отчёт о допуске по документам компании."""
    documents = await company_documents(db, company_id)
    report = evaluate_admission(
        category=category,
        subcategory=subcategory,
        characteristics=characteristics or {},
        documents=documents,
        moq_units=moq_units,
    )
    return CategoryAdmissionOut(
        category=report.category,
        subcategory=report.subcategory,
        state=report.state,
        state_label=report.state_label,
        supported=report.supported,
        profile_title=report.profile_title,
        summary=report.summary,
        requirements=[_requirement_out(item) for item in report.requirements],
        advisories=report.advisories,
        blocking_open=report.blocking_open,
        blocking_message=report.blocking_message,
        blocking_reasons=report.blocking_reasons,
        checked_at=report.checked_at,
        profile_key=report.profile_key,
        rules_version=report.rules_version,
    )


def admission_audit_payload(admission: CategoryAdmissionOut, *, specification: dict | None = None) -> dict:
    """Снимок допуска для журнала: правила, спецификация и учтённые доказательства."""
    return {
        "state": admission.state,
        "profile": admission.profile_title,
        "profile_key": admission.profile_key,
        "rules_version": admission.rules_version,
        "blocking_open": admission.blocking_open,
        "checked_at": admission.checked_at.isoformat(),
        "specification": deepcopy(specification) if specification is not None else {},
        "requirements": [
            {"code": item.code, "state": item.state, "documents": [str(doc) for doc in item.document_ids]}
            for item in admission.requirements
        ],
    }


async def require_company_admission(
    db: AsyncSession,
    company_id: uuid.UUID,
    check: SpecificationCheck,
    *,
    context: str,
) -> CategoryAdmissionOut:
    """Проверить допуск компании к обязательству и остановить его при пробелах."""
    from .category_registry import resolve_category
    if check.product_id is not None:
        from .category_compatibility import compare_specifications
        from types import SimpleNamespace
        product=await db.get(Product,check.product_id)
        if product is None or product.company_id!=company_id:
            raise HTTPException(409,"Товар обязательства недоступен продавцу")
        requested=SimpleNamespace(category=check.category,subcategory=check.subcategory,characteristics=check.characteristics,
            category_profile=check.category_profile,volume_units=check.volume_units or check.moq_units)
        compatibility=compare_specifications(product,requested)
        if not compatibility.matches:raise HTTPException(409,"Товар обязательства не соответствует потребности: "+compatibility.reason)
        check=SpecificationCheck(category=product.category,subcategory=product.subcategory,characteristics=product.characteristics,
            moq_units=check.moq_units,label=check.label,product_id=product.id,volume_units=check.volume_units,category_profile=product.category_profile)
    if resolve_category(check.category,check.subcategory) is None:
        raise HTTPException(409,(context+": " if context else "")+"Выберите известную листовую категорию; исходная классификация не подтверждена")
    admission = await company_admission(
        db,
        company_id,
        check.category,
        check.subcategory,
        characteristics=check.characteristics,
        moq_units=check.moq_units,
    )
    if admission.blocking_open:
        prefix = f"{context}: " if context else ""
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{prefix}{admission.blocking_message}")
    from .category_characteristics import validate_profile_values
    errors = validate_profile_values(check.category, check.subcategory, check.characteristics or {}, require_product_fields=True)
    if errors:
        raise HTTPException(409, (context + ": " if context else "") + "; ".join(errors))
    if check.product_id is not None:
        from .trust import append_audit_event
        await append_audit_event(db,event_type="product_specification_checked",entity_type="product",entity_id=check.product_id,
            actor_company_id=company_id,source_refs=[{"type":"product","id":str(check.product_id)}],
            payload={"admission":admission_audit_payload(admission,specification={"category":check.category,"subcategory":check.subcategory,
                "characteristics":check.characteristics,"category_profile":check.category_profile,"moq_units":check.moq_units,"volume_units":check.volume_units})},
            explanation="Перед обязательством проверена полная спецификация фактического товара, а не только подмножество свойств потребности")
    if check.product_id is None:
        from .matching import _passport_matches
        passport = await db.get(CapabilityPassport,company_id)
        if passport is None or not _passport_matches(passport,check.category,check.characteristics,check.subcategory,check.volume_units):
            raise HTTPException(409,(context+": " if context else "")+"Заполните и подтвердите область возможностей производителя для этой категории, единицы и спецификации")
        from .trust import append_audit_event
        await append_audit_event(db,event_type="capability_scope_checked",entity_type="company",entity_id=company_id,
            actor_company_id=company_id,payload={"details":deepcopy(passport.details),"category":check.category,
                "subcategory":check.subcategory,"characteristics":deepcopy(check.characteristics),"quantity":check.volume_units},
            explanation="Перед обязательством проверены актуальная область возможностей и её версия; сохранён неизменяемый снимок заявления продавца")
    return admission


async def require_admission_for_specifications(
    db: AsyncSession,
    company_id: uuid.UUID,
    checks: list[SpecificationCheck],
    *,
    context: str,
) -> list[CategoryAdmissionOut]:
    """Проверить каждую спецификацию группы: обязательство требует допуска для всех."""
    if not checks:
        checks = [SpecificationCheck(category="")]
    reports: list[CategoryAdmissionOut] = []
    for check in checks:
        label = f" ({check.label})" if check.label else ""
        reports.append(
            await require_company_admission(db, company_id, check, context=f"{context}{label}")
        )
    return reports


async def publicly_available_products(db: AsyncSession, products: list[Product]) -> list[Product]:
    """Re-evaluate time-dependent admission without mutating a seller's publication choice."""
    if not products:
        return []
    company_ids = list({product.company_id for product in products})
    verified = set((await db.execute(text(
        "SELECT id FROM auth.companies WHERE id = ANY(:ids) AND verification_status = 'verified' "
        "AND EXISTS (SELECT 1 FROM auth.company_members m WHERE m.company_id = auth.companies.id AND m.can_sell = true)"
    ), {"ids": company_ids})).scalars())
    documents = (await db.scalars(select(Document).where(Document.company_id.in_(company_ids)))).all()
    by_company: dict = {}
    for document in documents:
        by_company.setdefault(document.company_id, []).append(document)
    from .category_registry import resolve_category
    from .category_characteristics import validate_profile_values
    return [product for product in products if resolve_category(product.category,product.subcategory) is not None
            and not validate_profile_values(product.category,product.subcategory,product.characteristics,require_product_fields=True)
            and product.is_published and product.company_id in verified
            and not evaluate_admission(category=product.category, subcategory=product.subcategory,
                characteristics=product.characteristics, moq_units=product.moq_units,
                documents=by_company.get(product.company_id, [])).blocking_open]

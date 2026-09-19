"""Единая проверка категорийного допуска перед принятием обязательств.

Публикация товара, прямая сделка, групповое обязательство, резерв и замена
поставщика используют одну и ту же проверку. Черновики и предварительные
расчёты допускаются с предупреждениями; момент обязательства — нет.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .category_admission import evaluate_admission
from .models import Document
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
        "specification": specification or {},
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

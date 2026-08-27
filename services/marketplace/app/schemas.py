import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------- Адреса доставки ----------

class DeliveryAddressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    address: str
    city: str
    region: str
    is_default: bool


class DeliveryAddressIn(BaseModel):
    address: str = Field(min_length=5, max_length=500)
    city: str = Field(min_length=2, max_length=120)
    region: str = Field(min_length=2, max_length=120)
    is_default: bool = False


class DeliveryAddressPatch(BaseModel):
    address: str | None = Field(default=None, min_length=5, max_length=500)
    city: str | None = Field(default=None, min_length=2, max_length=120)
    region: str | None = Field(default=None, min_length=2, max_length=120)
    is_default: bool | None = None


# ---------- Производственный профиль ----------

class ProductionProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: uuid.UUID
    production_site_address: str | None
    region: str | None
    about: str | None


class ProductionProfileIn(BaseModel):
    production_site_address: str | None = Field(default=None, max_length=500)
    region: str | None = Field(default=None, max_length=120)
    about: str | None = Field(default=None, max_length=2000)


# ---------- Товары ----------

class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    category: str
    characteristics: dict[str, Any]
    price_rub: float
    moq_units: int
    lead_time_days: int
    is_published: bool


class ProductIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    category: str = Field(min_length=2, max_length=120)
    characteristics: dict[str, Any] = Field(default_factory=dict)
    price_rub: float = Field(gt=0)
    moq_units: int = Field(gt=0)
    lead_time_days: int = Field(gt=0)


class ProductPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    category: str | None = Field(default=None, min_length=2, max_length=120)
    characteristics: dict[str, Any] | None = None
    price_rub: float | None = Field(default=None, gt=0)
    moq_units: int | None = Field(default=None, gt=0)
    lead_time_days: int | None = Field(default=None, gt=0)


class PublishIn(BaseModel):
    published: bool


# ---------- Мощности ----------

class CapacityEntryIn(BaseModel):
    date: date
    available_units: int = Field(ge=0)


class CapacityPutIn(BaseModel):
    entries: list[CapacityEntryIn]


# ---------- Документы ----------

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    document_type: str
    file_key: str
    content_type: str


# ---------- Capability Passport ----------

class CapabilityPassportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: uuid.UUID
    technologies: list[Any]
    equipment: list[Any]
    materials: list[Any]
    size_ranges: dict[str, Any]
    tolerances: str | None
    certifications: list[Any]
    min_order_units: int | None
    max_order_units: int | None
    delivery_regions: list[Any]
    completed_order_types: list[Any]


class CapabilityPassportIn(BaseModel):
    technologies: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    size_ranges: dict[str, Any] = Field(default_factory=dict)
    tolerances: str | None = Field(default=None, max_length=500)
    certifications: list[str] = Field(default_factory=list)
    min_order_units: int | None = Field(default=None, ge=0)
    max_order_units: int | None = Field(default=None, ge=0)
    delivery_regions: list[str] = Field(default_factory=list)
    completed_order_types: list[str] = Field(default_factory=list)


# ---------- Потребности ----------

class NeedFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    content_type: str


class NeedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    category: str
    characteristics: dict[str, Any]
    volume_units: int
    budget_rub: float | None
    deadline_date: date
    delivery_address_id: uuid.UUID | None
    visibility: str
    status: str
    files: list[NeedFileOut] = Field(default_factory=list)


class NeedIn(BaseModel):
    company_id: uuid.UUID
    category: str = Field(min_length=2, max_length=120)
    characteristics: dict[str, Any] = Field(default_factory=dict)
    volume_units: int = Field(gt=0)
    budget_rub: float | None = Field(default=None, gt=0)
    deadline_date: date
    delivery_address_id: uuid.UUID | None = None
    visibility: str = Field(default="open_anonymized", pattern="^(open_anonymized|selected_producers|closed)$")


# ---------- Предложения ----------

class OfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    need_id: uuid.UUID
    company_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    price_rub: float
    available_units: int
    lead_time_days: int
    status: str


class OfferIn(BaseModel):
    company_id: uuid.UUID
    price_rub: float = Field(gt=0)
    available_units: int = Field(gt=0)
    lead_time_days: int = Field(gt=0)


# ---------- Сделки ----------

class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    offer_id: uuid.UUID
    need_id: uuid.UUID
    buyer_company_id: uuid.UUID
    seller_company_id: uuid.UUID
    units: int
    total_price_rub: float
    status: str


# ---------- Уведомления ----------

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    message: str
    type: str
    is_read: bool

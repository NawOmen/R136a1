import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

LegalForm = Literal["ООО", "ИП"]
VerificationDecision = Literal["approve", "reject"]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    last_name: str
    first_name: str
    middle_name: str | None
    email: EmailStr
    phone: str | None
    account_status: str
    is_category_editor: bool = False
    is_marketplace_admin: bool


class RegisterIn(BaseModel):
    last_name: str = Field(min_length=1, max_length=120)
    first_name: str = Field(min_length=1, max_length=120)
    middle_name: str | None = Field(default=None, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    phone: str | None = Field(default=None, max_length=40)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Пароль должен занимать не более 72 байт UTF-8")
        return value


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    user: UserOut
    access_token: str
    token_type: str = "bearer"


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    can_buy: bool
    can_sell: bool
    is_admin: bool


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    display_name: str
    legal_form: str
    inn: str
    ogrn: str | None
    ogrnip: str | None
    kpp: str | None
    legal_address: str
    country: str
    verification_status: str
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class CompanyWithMembership(CompanyOut):
    membership: MembershipOut


class CompanyIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    display_name: str = Field(min_length=2, max_length=255)
    legal_form: LegalForm
    inn: str = Field(min_length=10, max_length=12)
    ogrn: str | None = Field(default=None, max_length=15)
    ogrnip: str | None = Field(default=None, max_length=15)
    kpp: str | None = Field(default=None, max_length=9)
    legal_address: str = Field(min_length=5, max_length=500)
    can_buy: bool = False
    can_sell: bool = False

    @model_validator(mode="after")
    def require_at_least_one_mode(self) -> "CompanyIn":
        if not self.can_buy and not self.can_sell:
            raise ValueError("Выберите хотя бы один режим: «Покупаю» или «Продаю»")
        return self


class CompanyPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    display_name: str | None = Field(default=None, min_length=2, max_length=255)
    legal_form: LegalForm | None = None
    inn: str | None = Field(default=None, min_length=10, max_length=12)
    ogrn: str | None = Field(default=None, max_length=15)
    ogrnip: str | None = Field(default=None, max_length=15)
    kpp: str | None = Field(default=None, max_length=9)
    legal_address: str | None = Field(default=None, min_length=5, max_length=500)


class MembershipPatch(BaseModel):
    can_buy: bool
    can_sell: bool


class MeOut(BaseModel):
    user: UserOut
    companies: list[CompanyWithMembership]


class AdminCompaniesOut(BaseModel):
    companies: list[CompanyOut]


class AdminUsersOut(BaseModel):
    users: list[UserOut]


class VerificationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    from_status: str
    to_status: str
    performed_by_user_id: uuid.UUID | None
    reason: str | None
    created_at: datetime


class AdminVerificationIn(BaseModel):
    decision: VerificationDecision
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_reason_on_reject(self) -> "AdminVerificationIn":
        if self.decision == "reject" and (self.reason is None or not self.reason.strip()):
            raise ValueError("При отклонении необходимо указать причину")
        return self


class AdminVerificationV2In(AdminVerificationIn):
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_reason(self):
        if not self.reason.strip():
            raise ValueError("Укажите причину решения")
        self.reason = self.reason.strip()
        return self


class BlockIn(BaseModel):
    blocked: bool
    reason: str | None = Field(default=None, max_length=500)

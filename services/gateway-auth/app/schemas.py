import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

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
    is_marketplace_admin: bool


class RegisterIn(BaseModel):
    last_name: str = Field(min_length=1, max_length=120)
    first_name: str = Field(min_length=1, max_length=120)
    middle_name: str | None = Field(default=None, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    phone: str | None = Field(default=None, max_length=40)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


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


class AdminVerificationIn(BaseModel):
    decision: VerificationDecision
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_reason_on_reject(self) -> "AdminVerificationIn":
        if self.decision == "reject" and (self.reason is None or not self.reason.strip()):
            raise ValueError("При отклонении необходимо указать причину")
        return self


class BlockIn(BaseModel):
    blocked: bool

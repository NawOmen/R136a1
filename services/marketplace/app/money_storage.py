"""All persisted JSON monetary values use decimal strings, independently of engine."""
from sqlalchemy.types import TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from .money import exact_json


class ExactJSONB(TypeDecorator):
    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return exact_json(value)


from sqlalchemy import Numeric
from .money import decimal


class ExactNumeric(TypeDecorator):
    impl = Numeric(24,12)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return decimal(value) if value is not None else None

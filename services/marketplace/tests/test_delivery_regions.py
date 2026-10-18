from types import SimpleNamespace
import uuid

import pytest
from app.delivery_regions import region_is_served
from app.api.needs import _region_allowed


@pytest.mark.parametrize("advertised,destination,expected", [
    (["Центральный ФО"], "г. Москва", True),
    (["ЦФО"], "город Москва", True),
    (["Центральный федеральный округ"], "Московская область", True),
    (["Центральный ФО"], "Республика Татарстан", False),
    (["Россия"], "г. Москва", True),
    (["Россия"], "Свердловская область", True),
    (["Уральский ФО"], "Свердловская область", True),
    (["Сибирский ФО"], "Новосибирская область", True),
    (["Приволжский ФО"], "Республика Татарстан", True),
    (["Северо-Западный ФО"], "Санкт-Петербург", True),
    (["Южный ФО"], "Краснодарский край", True),
    (["Северо-Кавказский ФО"], "Ставропольский край", True),
    (["Дальневосточный ФО"], "Приморский край", True),
    (["Москва"], "Московская область", False),
    (["Москва"], "г.Москва", True),
    (["Россия"], "неизвестная область", False),
    (["Россия"], "Берлин", False),
    (["Центральный ФО"], "Моск", False),
    ([""], "", False),
])
def test_advertised_region_matching(advertised, destination, expected):
    assert region_is_served(advertised, destination) is expected


async def test_feed_region_check_keeps_unrestricted_and_missing_address_behavior():
    address_id = uuid.uuid4()
    need = SimpleNamespace(delivery_address_id=address_id)
    passport = SimpleNamespace(delivery_regions=["Центральный ФО"])
    assert await _region_allowed(None, passport, need, {address_id: SimpleNamespace(region="г. Москва")})
    assert not await _region_allowed(None, passport, need, {address_id: SimpleNamespace(region="Свердловская область")})
    assert await _region_allowed(None, passport, need, {})
    assert await _region_allowed(None, passport, SimpleNamespace(delivery_address_id=None), {})
    assert await _region_allowed(None, SimpleNamespace(delivery_regions=[]), need, {})

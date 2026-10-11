"""S14: ограниченный regex-фильтр и отключённые внешние адаптеры.

Граница counters-only/opt-in проверяется на настоящем caller в test_agents.py.
"""
import pytest

from app.anonymizer import anonymize_text
from app.role_passports import ADAPTER_CONTRACT_VERSION, EXTERNAL_ADAPTERS, check_external_adapter


def test_anonymizer_strips_company_identifiers():
    text = ("ООО «Ромашка» ИНН 7712345678, ОГРН 1157746000000, "
            "директор ivan@example.com, тел. +7 (495) 123-45-67, звоните 8-800-555-35-35.")
    cleaned = anonymize_text(text)
    assert "7712345678" not in cleaned
    assert "1157746000000" not in cleaned
    assert "ivan@example.com" not in cleaned
    assert "495" not in cleaned and "555-35-35" not in cleaned
    assert "Ромашка" not in cleaned


def test_unknown_adapter_is_denied():
    with pytest.raises(ValueError, match="не зарегистрирован или отключён"):
        check_external_adapter("mcp-1c", contract_version=ADAPTER_CONTRACT_VERSION,
                               scope="catalog_read", budget=1)


def test_adapter_boundaries_are_enforced(monkeypatch):
    monkeypatch.setitem(EXTERNAL_ADAPTERS, "fixture-erp", {
        "contract_version": ADAPTER_CONTRACT_VERSION, "enabled": True,
        "scopes": frozenset({"catalog_read"}), "max_budget": 100,
    })
    assert check_external_adapter("fixture-erp", contract_version=ADAPTER_CONTRACT_VERSION,
                                  scope="catalog_read", budget=100) == "system"
    with pytest.raises(ValueError, match="не разрешено"):
        check_external_adapter("fixture-erp", contract_version=ADAPTER_CONTRACT_VERSION,
                               scope="deal_write", budget=10)
    with pytest.raises(ValueError, match="Бюджет"):
        check_external_adapter("fixture-erp", contract_version=ADAPTER_CONTRACT_VERSION,
                               scope="catalog_read", budget=101)
    with pytest.raises(ValueError, match="Бюджет"):
        check_external_adapter("fixture-erp", contract_version=ADAPTER_CONTRACT_VERSION,
                               scope="catalog_read", budget=0)
    with pytest.raises(ValueError, match="несовместим"):
        check_external_adapter("fixture-erp", contract_version="external-adapter-0",
                               scope="catalog_read", budget=10)
    monkeypatch.setitem(EXTERNAL_ADAPTERS, "fixture-erp", {
        "contract_version": ADAPTER_CONTRACT_VERSION, "enabled": False,
        "scopes": frozenset({"catalog_read"}), "max_budget": 100,
    })
    with pytest.raises(ValueError, match="отключён"):
        check_external_adapter("fixture-erp", contract_version=ADAPTER_CONTRACT_VERSION,
                               scope="catalog_read", budget=10)

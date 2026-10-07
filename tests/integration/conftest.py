"""Fail closed before mutating a separately configured synthetic Docker stack."""
import os
from urllib.parse import urlsplit

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_stack_contract():
    if os.getenv("RUN_DOCKER_INTEGRATION") != "1":
        return
    assert os.getenv("DOCKER_TEST_PROJECT") == "r136-fulltest", "Нужен явный маркер выделенного Docker-стенда"
    assert os.getenv("ENABLE_DEMO_SEED") == "true", "Нужен синтетический тестовый стенд"
    database = urlsplit(os.environ.get("DATABASE_URL", ""))
    assert database.hostname == "postgres" and database.path == "/sborka", "Запускать внутри выделенной Compose-сети"

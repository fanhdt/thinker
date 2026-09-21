from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import get_db_session
from app.main import app


@pytest.fixture(autouse=True)
def _reset_llm_provider_settings():
    """Reset konfigurasi LLM sebelum setiap test dan pulihkan setelahnya."""
    original = settings.model_dump()

    settings.llm_provider_chain = None
    settings.llm_provider_simple = None
    settings.llm_provider_simple_chain = None
    settings.llm_provider_planner = None
    settings.llm_provider_planner_chain = None

    yield

    for key, value in original.items():
        setattr(settings, key, value)


class FakeSession:
    """Sesi DB palsu untuk test API."""

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


async def _fake_db_session() -> AsyncGenerator:
    yield FakeSession()


@pytest.fixture
def client():
    """Fixture bersama untuk semua test API."""
    app.dependency_overrides[get_db_session] = _fake_db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


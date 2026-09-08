from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import app

class FakeSession:
    """Sesi DB palsu untuk test API. Route yang service-layer-nya sudah
    kita mock total tidak pernah benar-benar menyentuh session ini --
    dia cuma perlu 'ada' supaya dependency injection FastAPI tidak error
    saat mencari get_db_session.
    """
    async def commit(self) -> None:
        pass


    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass

async def _fake_db_session()->AsyncGenerator:
    yield FakeSession()

@pytest.fixture
def client():
    """Fixture bersama untuk semua test API. Pakai dengan menambahkan
    parameter `client` di signature fungsi test -- pytest otomatis
    menyuntikkannya, tidak perlu import apapun dari file ini.
    """
    app.dependency_overrides[get_db_session] = _fake_db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
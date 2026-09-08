import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import app

client = TestClient(app)


class _FakeSession:
    """Sesi DB palsu -- cukup untuk route yang service-nya kita mock total."""

    async def close(self) -> None:
        pass


async def _fake_db_session() -> AsyncGenerator:
    yield _FakeSession()


def test_list_messages_rejects_malformed_conversation_id():
    """Ini test yang seharusnya menangkap bug `conversation_id=uuid.UUID` (pakai '='
    bukan ':') di masa lalu. Tanpa type annotation yang benar, FastAPI tidak
    memvalidasi path param sama sekali dan endpoint akan meloloskan string
    sembarangan dengan status 200, bukan menolaknya dengan 422.
    """
    response = client.get("/conversations/ini-bukan-uuid-sama-sekali/messages")
    assert response.status_code == 422


def test_list_messages_passes_a_real_uuid_object_to_the_service():
    """Membuktikan bahwa conversation_id yang diteruskan ke service benar-benar
    berupa instance uuid.UUID, bukan str mentah dari URL.
    """
    app.dependency_overrides[get_db_session] = _fake_db_session
    valid_id = uuid.uuid4()

    try:
        with (
            patch(
                "app.api.conversations.conversation_service.get_conversation",
                new=AsyncMock(return_value=object()),
            ) as mock_get_conversation,
            patch(
                "app.api.conversations.conversation_service.get_messages",
                new=AsyncMock(return_value=[]),
            ),
        ):
            response = client.get(f"/conversations/{valid_id}/messages")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200

    assert mock_get_conversation.await_args is not None

    called_conversation_id = mock_get_conversation.await_args.args[1]
    assert isinstance(called_conversation_id, uuid.UUID)
    assert called_conversation_id == valid_id
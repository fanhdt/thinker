import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _fake_memory(**overrides):
    memory = MagicMock()
    memory.id = overrides.get("id", uuid.uuid4())
    memory.content = overrides.get("content", "User suka kopi tanpa gula")
    memory.created_at = overrides.get("created_at", datetime.now(UTC))
    return memory


def test_list_memories_returns_memories_for_default_user(client):
    fake_user = MagicMock(id=uuid.uuid4())
    fake_memories = [_fake_memory(content="Fakta A"), _fake_memory(content="Fakta B")]

    with (
        patch(
            "app.api.memories.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch(
            "app.api.memories.memory_service.get_all_memories",
            new=AsyncMock(return_value=fake_memories),
        ) as mock_get_memories,
    ):
        response = client.get("/memories")

    assert response.status_code == 200
    contents = [m["content"] for m in response.json()]
    assert contents == ["Fakta A", "Fakta B"]
    mock_get_memories.assert_called_once()

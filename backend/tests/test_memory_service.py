import math
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.models.memory import Memory
from app.services.memory_service import (
    apply_extraction,
    cosine_similarity,
    delete_memory,
    update_memory,
)


def test_cosine_similarity_identical_vectors_is_one():
    a = [1.0, 2.0, 3.0]
    assert math.isclose(cosine_similarity(a, a), 1.0)


def test_cosine_similarity_opposite_vectors_is_negative_one():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert math.isclose(cosine_similarity(a, b), -1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert math.isclose(cosine_similarity(a, b), 0.0)


def test_cosine_similarity_similar_direction_is_close_to_one():
    a = [1.0, 2.0, 3.0]
    b = [1.1, 2.1, 3.1]
    assert cosine_similarity(a, b) > 0.99


def test_cosine_similarity_zero_vector_returns_zero_not_crash():
    a = [0.0, 0.0, 0.0]
    b = [1.0, 2.0, 3.0]
    assert cosine_similarity(a, b) == 0.0


class FakeSession:
    """Sesi DB palsu -- cukup mencatat pemanggilan flush/delete, tidak
    benar-benar menyentuh database. Dipakai supaya test ini murni menguji
    logic mutation (bukan mengetes SQLAlchemy sendiri)."""

    def __init__(self):
        self.flush = AsyncMock()
        self.delete = AsyncMock()
        self.add = AsyncMock()


@pytest.fixture
def existing_memory():
    return Memory(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        content="User suka kopi",
        embedding=[1.0, 0.0],
        importance=3,
    )


async def test_update_memory_mutates_content_embedding_and_importance(existing_memory):
    session = FakeSession()

    result = await update_memory(session, existing_memory, "User suka teh", [0.0, 1.0], 4)

    assert result is existing_memory
    assert existing_memory.content == "User suka teh"
    assert existing_memory.embedding == [0.0, 1.0]
    assert existing_memory.importance == 4
    session.flush.assert_called_once()


async def test_delete_memory_calls_session_delete_and_flush(existing_memory):
    session = FakeSession()

    await delete_memory(session, existing_memory)

    session.delete.assert_called_once_with(existing_memory)
    session.flush.assert_called_once()


async def test_apply_extraction_create_delegates_to_store_memory_if_new():
    session = FakeSession()
    user_id = uuid.uuid4()

    with patch("app.services.memory_service.store_memory_if_new", new=AsyncMock()) as mock_store:
        await apply_extraction(
            session, user_id, "CREATE", [], "User suka kopi", [1.0, 0.0], 3, None
        )

    mock_store.assert_called_once_with(session, user_id, "User suka kopi", [1.0, 0.0], 3)


async def test_apply_extraction_update_targets_correct_existing_memory(existing_memory):
    """Ini regresi utama untuk skenario 'Sekarang aku lebih suka teh' di
    master prompt -- UPDATE harus mengganti memory lama, bukan membuat
    memory baru yang kontradiktif."""
    session = FakeSession()
    other_memory = Memory(
        id=uuid.uuid4(),
        user_id=existing_memory.user_id,
        content="lainnya",
        embedding=[0.0],
        importance=1,
    )

    result = await apply_extraction(
        session,
        existing_memory.user_id,
        "UPDATE",
        [other_memory, existing_memory],
        "User suka teh",
        [0.0, 1.0],
        4,
        1,
    )

    assert result is existing_memory
    assert existing_memory.content == "User suka teh"
    assert other_memory.content == "lainnya"


async def test_apply_extraction_delete_removes_correct_existing_memory(existing_memory):
    """Regresi untuk skenario 'Lupakan bahwa aku suka kopi'."""
    session = FakeSession()

    result = await apply_extraction(
        session, existing_memory.user_id, "DELETE", [existing_memory], None, None, 3, 0
    )

    assert result is None
    session.delete.assert_called_once_with(existing_memory)


async def test_apply_extraction_ignore_does_nothing():
    session = FakeSession()

    result = await apply_extraction(session, uuid.uuid4(), "IGNORE", [], None, None, 3, None)

    assert result is None
    session.flush.assert_not_called()
    session.delete.assert_not_called()
    session.add.assert_not_called()


async def test_retrieve_relevant_memories_logs_one_structured_event(caplog):
    """Regresi: sebelumnya tiap memory di-log satu-satu lewat `logger.info`
    plain-text (`Memori Similarity Score =...`), bukan lewat `log_event` --
    jadi tidak terstruktur dan bisa membanjiri log kalau memory-nya banyak.
    Sekarang harus jadi SATU event `memory_retrieval` yang merangkum semuanya."""
    from app.services.memory_service import retrieve_relevant_memories

    memory = Memory(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        content="User suka kopi",
        embedding=[1.0, 0.0],
        importance=3,
    )

    with (
        patch(
            "app.services.memory_service.get_all_memories",
            new=AsyncMock(return_value=[memory]),
        ),
        caplog.at_level("INFO"),
    ):
        result = await retrieve_relevant_memories(FakeSession(), memory.user_id, [1.0, 0.0])

    assert result == [memory]

    retrieval_events = [r for r in caplog.records if r.message == "memory_retrieval"]
    assert len(retrieval_events) == 1
    assert retrieval_events[0].event_data["candidates"] == 1
    assert retrieval_events[0].event_data["returned"] == 1

    assert not any("Memori Similarity Score" in r.message for r in caplog.records)

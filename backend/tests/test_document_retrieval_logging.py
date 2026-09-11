import uuid
from unittest.mock import AsyncMock, patch

from app.models.document_chunk import DocumentChunk
from app.services.document_service import retrieve_relevant_chunks


async def test_retrieve_relevant_chunks_logs_one_structured_event(caplog):
    """RAG sebelumnya tidak punya observability retrieval sama sekali
    (Bagian 21 minta ini) -- sekarang harus ada satu event `document_retrieval`
    per pemanggilan, merangkum jumlah kandidat dan yang dikembalikan."""
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=0,
        content="Isi dokumen tentang kopi.",
        embedding=[1.0, 0.0],
    )

    with (
        patch(
            "app.services.document_service.get_all_chunks",
            new=AsyncMock(return_value=[chunk]),
        ),
        caplog.at_level("INFO"),
    ):
        result = await retrieve_relevant_chunks(object(), uuid.uuid4(), [1.0, 0.0])

    assert result == [chunk]

    retrieval_events = [r for r in caplog.records if r.message == "document_retrieval"]
    assert len(retrieval_events) == 1
    assert retrieval_events[0].event_data["candidates"] == 1
    assert retrieval_events[0].event_data["returned"] == 1

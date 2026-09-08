from unittest.mock import AsyncMock, MagicMock

from app.services.embedding_service import EmbeddingService


def _build_service_with_fake_client() -> tuple[EmbeddingService, AsyncMock]:
    """Sama seperti pola di test_llm_service.py: __new__ melewati __init__ supaya
    tidak butuh gemini_api_key asli, lalu kita suntik client palsu sendiri.
    """
    service = EmbeddingService.__new__(EmbeddingService)

    fake_embedding = MagicMock()
    fake_embedding.values = [0.1, 0.2, 0.3]
    fake_response = MagicMock()
    fake_response.embeddings = [fake_embedding]

    fake_generate = AsyncMock(return_value=fake_response)
    fake_client = MagicMock()
    fake_client.aio.models.embed_content = fake_generate
    service._client = fake_client

    return service, fake_generate


async def test_embed_document_sends_retrieval_document_task_type():
    """Ini test yang seharusnya menangkap bug `task_type=str` di masa lalu.

    Sebelum fix, `task_type` di `_embed()` tidak dianotasi (defaultnya adalah
    class `str` itu sendiri, bukan instance string). Tidak menyebabkan crash
    runtime di jalur ini (karena caller selalu mengirim string eksplisit), tapi
    type checker (pyright/mypy) tidak bisa memvalidasi tipe parameter ini sama
    sekali -- persis pola yang sama dengan bug conversation_id sebelumnya.
    """
    service, fake_generate = _build_service_with_fake_client()

    result = await service.embed_document("Contoh dokumen")

    assert result == [0.1, 0.2, 0.3]
    called_config = fake_generate.call_args.kwargs["config"]
    assert called_config.task_type == "RETRIEVAL_DOCUMENT"


async def test_embed_query_sends_retrieval_query_task_type():
    service, fake_generate = _build_service_with_fake_client()

    await service.embed_query("Contoh query")

    called_config = fake_generate.call_args.kwargs["config"]
    assert called_config.task_type == "RETRIEVAL_QUERY"

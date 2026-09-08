import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.deps import get_embedding_service
from app.main import app
from app.services.llm import LLMServiceError


def _fake_document(**overrides):
    doc = MagicMock()
    doc.id = overrides.get("id", uuid.uuid4())
    doc.filename = overrides.get("filename", "catatan.txt")
    doc.created_at = overrides.get("created_at", datetime.now(UTC))
    return doc


def _override_embedder(fake_embedder) -> None:
    app.dependency_overrides[get_embedding_service] = lambda: fake_embedder


def test_upload_document_rejects_unsupported_content_type(client):
    response = client.post(
        "/documents", files={"file": ("gambar.png", b"bukan-teks", "image/png")}
    )
    assert response.status_code == 400


def test_upload_document_rejects_file_too_large(client):
    with patch("app.api.documents.MAX_FILE_SIZE_BYTES", 10):
        response = client.post(
            "/documents",
            files={"file": ("catatan.txt", b"lebih dari sepuluh byte", "text/plain")},
        )
    assert response.status_code == 400


def test_upload_document_rejects_when_no_text_extracted(client):
    with patch("app.api.documents.document_service.parse_text", return_value="   "):
        response = client.post(
            "/documents", files={"file": ("kosong.txt", b"   ", "text/plain")}
        )
    assert response.status_code == 400


def test_upload_document_returns_503_when_embedding_fails(client):
    fake_embedder = MagicMock()
    fake_embedder.embed_document = AsyncMock(side_effect=LLMServiceError("gagal embed"))
    _override_embedder(fake_embedder)

    with (
        patch("app.api.documents.document_service.parse_text", return_value="Isi dokumen"),
        patch("app.api.documents.document_service.chunk_text", return_value=["Isi dokumen"]),
    ):
        response = client.post(
            "/documents", files={"file": ("catatan.txt", b"Isi dokumen", "text/plain")}
        )

    assert response.status_code == 503


def test_upload_document_returns_created_document(client):
    fake_embedder = MagicMock()
    fake_embedder.embed_document = AsyncMock(return_value=[0.1, 0.2, 0.3])
    _override_embedder(fake_embedder)

    fake_user = MagicMock(id=uuid.uuid4())
    fake_document = _fake_document(filename="catatan.txt")

    with (
        patch("app.api.documents.document_service.parse_text", return_value="Isi dokumen"),
        patch("app.api.documents.document_service.chunk_text", return_value=["Isi dokumen"]),
        patch(
            "app.api.documents.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch(
            "app.api.documents.document_service.create_document_with_chunks",
            new=AsyncMock(return_value=fake_document),
        ) as mock_create,
    ):
        response = client.post(
            "/documents", files={"file": ("catatan.txt", b"Isi dokumen", "text/plain")}
        )

    assert response.status_code == 200
    assert response.json()["filename"] == "catatan.txt"
    mock_create.assert_called_once()


def test_list_documents_returns_documents_for_default_user(client):
    fake_user = MagicMock(id=uuid.uuid4())
    fake_documents = [_fake_document(filename="a.txt"), _fake_document(filename="b.txt")]

    with (
        patch(
            "app.api.documents.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch(
            "app.api.documents.document_service.get_all_documents",
            new=AsyncMock(return_value=fake_documents),
        ),
    ):
        response = client.get("/documents")

    assert response.status_code == 200
    filenames = [d["filename"] for d in response.json()]
    assert filenames == ["a.txt", "b.txt"]
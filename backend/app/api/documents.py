import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_embedding_service
from app.db.session import get_db_session
from app.schemas.document import DocumentOut
from app.services import conversation_service, document_service
from app.services.embedding_service import EmbeddingService
from app.services.llm import LLMServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_CONTENT_TYPES = {"application/pdf", "text/plain"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


@router.post("", response_model=DocumentOut)
async def upload_document(
    file: UploadFile,
    session: AsyncSession = Depends(get_db_session),
    embedder: EmbeddingService = Depends(get_embedding_service),
) -> DocumentOut:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipe file tidak didukung:{file.content_type}.Gunakan PDF atau txt polos(.txt)",
        )
    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File terlalu besar (maks 10 MB).")

    text = document_service.parse_text(raw_bytes, file.content_type)
    if not text.strip():
        raise HTTPException(
            status_code=400, detail="Tidak ada teks yang bisa diekstrak dari file ini."
        )
    chunks = document_service.chunk_text(text)

    try:
        embeddings = [await embedder.embed_document(chunk) for chunk in chunks]
    except LLMServiceError as exc:
        logger.error("Gagal membuat embedding dokumen : %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    user = await conversation_service.get_or_create_default_user(session)
    document = await document_service.create_document_with_chunks(
        session, user.id, file.filename or "untitled", chunks, embeddings
    )
    await session.commit()

    return DocumentOut.model_validate(document)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentOut]:
    user = await conversation_service.get_or_create_default_user(session)
    await session.commit()

    documents = await document_service.get_all_documents(session, user.id)
    return [DocumentOut.model_validate(d) for d in documents]

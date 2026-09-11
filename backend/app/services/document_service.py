import io
import logging
import uuid

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging_config import log_event
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.similarity import cosine_similarity

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

RETRIEVAL_THRESHOLD = 0.5
MAX_RETRIEVED_CHUNKS = 5

logger = logging.getLogger(__name__)


def parse_text(raw_bytes: bytes, content_type: str) -> str:
    if content_type == "application/pdf":
        reader = PdfReader(io.BytesIO(raw_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)

    return raw_bytes.decode("utf-8", errors="replace")


def chunk_text(
    text: str, *, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    step = chunk_size - overlap

    while start < len(text):
        chunk = text[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


async def create_document_with_chunks(
    session: AsyncSession,
    user_id: uuid.UUID,
    filename: str,
    chunk_contents: list[str],
    chunk_embeddings: list[list[float]],
) -> Document:
    document = Document(user_id=user_id, filename=filename)
    session.add(document)
    await session.flush()

    pairs = zip(chunk_contents, chunk_embeddings, strict=True)
    for index, (content, embedding) in enumerate(pairs):
        chunk = DocumentChunk(
            document_id=document.id, chunk_index=index, content=content, embedding=embedding
        )
        session.add(chunk)
    await session.flush()
    return document


async def get_all_documents(session: AsyncSession, user_id: uuid.UUID) -> list[Document]:
    result = await session.execute(select(Document).where(Document.user_id == user_id))
    return list(result.scalars().all())


async def get_all_chunks(session: AsyncSession, user_id: uuid.UUID) -> list[DocumentChunk]:
    result = await session.execute(
        select(DocumentChunk)
        .join(Document)
        .where(Document.user_id == user_id)
        .options(selectinload(DocumentChunk.document))
    )
    return list(result.scalars().all())


async def retrieve_relevant_chunks(
    session: AsyncSession, user_id: uuid.UUID, query_embedding: list[float]
) -> list[DocumentChunk]:
    chunks = await get_all_chunks(session, user_id)

    scored = [(cosine_similarity(c.embedding, query_embedding), c) for c in chunks]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    relevant = [(score, c) for score, c in scored if score >= RETRIEVAL_THRESHOLD]
    result = [c for _, c in relevant[:MAX_RETRIEVED_CHUNKS]]

    log_event(
        logger,
        "document_retrieval",
        candidates=len(chunks),
        threshold=RETRIEVAL_THRESHOLD,
        returned=len(result),
        top_scores=[round(score, 4) for score, _ in scored[:MAX_RETRIEVED_CHUNKS]],
    )

    return result

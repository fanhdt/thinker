import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_embedding_service, get_llm_service
from app.db.session import get_db_session
from app.models.memory import Memory
from app.schemas.conversation import (
    ConversationCreate,
    ConversationOut,
    MessageOut,
    SendMessageRequest,
    SendMessageResponse,
)
from app.services import conversation_service, memory_service
from app.services.embedding_service import EmbeddingService
from app.services.llm import LLMService, LLMServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationOut)
async def create_conversation(
    payload: ConversationCreate,
    session: AsyncSession = Depends(get_db_session),
) -> ConversationOut:
    user = await conversation_service.get_or_create_default_user(session)
    conversation = await conversation_service.create_conversation(session, user.id, payload.title)
    await session.commit()
    return ConversationOut.model_validate(conversation)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id=uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> list[MessageOut]:
    conversation = await conversation_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation tidak ditemukan")

    messages = await conversation_service.get_messages(session, conversation_id)
    return [MessageOut.model_validate(m) for m in messages]


def _build_memory_instruction(memories: list[Memory]) -> str | None:
    if not memories:
        return None

    facts = "\n".join(f"-{m.content}" for m in memories)
    return (
        "Berikut fakta yang kamu ingat tentang user dari percakapan "
        "sebelumnya:\n"
        f"{facts}\n"
        "Gunakan informasi ini kalau relevan dengan pertanyaan user. "
        "Tidak perlu menyebutkan eksplisit bahwa ini berasal dari "
        "'memori' kecuali user bertanya soal itu."
    )


@router.post("/{conversation_id}/messages", response_model=SendMessageResponse)
async def send_message(
    conversation_id: uuid.UUID,
    payload: SendMessageRequest,
    session: AsyncSession = Depends(get_db_session),
    llm: LLMService = Depends(get_llm_service),
    embedder: EmbeddingService = Depends(get_embedding_service),
) -> SendMessageResponse:
    conversation = await conversation_service.get_conversation(
        session,
        conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation tidak ditemukan")

    await conversation_service.add_message(session, conversation_id, "user", payload.message)

    system_instruction = None
    try:
        query_embedding = await embedder.embed_query(payload.message)
        relevant_memories = await memory_service.retrieve_relevant_memories(
            session, conversation.user_id, query_embedding
        )
        system_instruction = _build_memory_instruction(relevant_memories)
    except LLMServiceError as exc:
        logger.warning("Gagal retrieval memori (non-fatal):%s", exc)

    history = await conversation_service.get_messages(session, conversation_id)
    history_payload = [{"role": m.role, "content": m.content} for m in history]

    try:
        reply = await llm.chat_with_history(history_payload, system_instruction=system_instruction)
    except LLMServiceError as exc:
        await session.rollback()
        logger.error("Chat request failed %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await conversation_service.add_message(session, conversation_id, "assistant", reply)

    try:
        fact = await llm.extract_fact(payload.message)
        if fact:
            fact_embedding = await embedder.embed_document(fact)
            await memory_service.store_memory_if_new(
                session, conversation.user_id, fact, fact_embedding
            )
    except LLMServiceError as exc:
        logger.warning("gagal ekstraksi memori (non fatal):%s", exc)
    await session.commit()

    return SendMessageResponse(reply=reply, model=llm.model, conversation_id=conversation_id)

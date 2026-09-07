import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_embedding_service, get_llm_service
from app.db.session import get_db_session
from app.models.document_chunk import DocumentChunk
from app.models.goal import Goal
from app.models.memory import Memory
from app.schemas.conversation import (
    ConversationCreate,
    ConversationOut,
    MessageOut,
    SendMessageRequest,
    SendMessageResponse,
)
from app.schemas.planner import TaskResultOut
from app.services import (
    conversation_service,
    document_service,
    goal_service,
    memory_service,
    orchestrator_service,
    personalization_service,
)
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


def _build_context_instruction(
    memories: list[Memory],
    chunks: list[DocumentChunk],
    goals: list[Goal],
    preferences: dict,
) -> str | None:
    if not memories and not chunks and not goals and not preferences:
        return None

    parts = []

    personalization_text = personalization_service.build_personalization_context(goals, preferences)
    if personalization_text:
        parts.append(personalization_text)

    if memories:
        facts = "\n".join(f"- {m.content}" for m in memories)
        parts.append(f"Fakta yang kamu ingat tentang user :\n{facts}")

    if chunks:
        excerpts = "\n\n".join(
            f"[Dari dokumen : {c.document.filename}]\n{c.content}" for c in chunks
        )
        parts.append(f"Potongan dokumen yang relevan dengan pertanyaan user:\n{excerpts}")

    context = "\n\n".join(parts)
    return (
        f"{context}\n\n"
        "Gunakan informasi di atas kalau relevan untuk menjawab. -- termasuk"
        "menyesuaikan gaya jawabanmu dengan preferensi user, dan "
        "mempertimbangkan tujuan jangka panjangnya kalau relevan. Kalau"
        "menjawab berdasarkan isi dokumen, sebutkan sumbernya. Kalau"
        "tidak relevan, abaikan saja dan jawab seperti biasa"
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

    context_text = None
    try:
        query_embedding = await embedder.embed_query(payload.message)
        relevant_memories = await memory_service.retrieve_relevant_memories(
            session, conversation.user_id, query_embedding
        )
        relevant_chunks = await document_service.retrieve_relevant_chunks(
            session, conversation.user_id, query_embedding
        )
        active_goals = await goal_service.get_goals(session, conversation.user_id, status="active")
        user = await conversation_service.get_or_create_default_user(session)
        context_text = _build_context_instruction(
            relevant_memories, relevant_chunks, active_goals, user.preferences
        )
    except LLMServiceError as exc:
        logger.warning("Gagal retrieval memori (non-fatal):%s", exc)

    history = await conversation_service.get_messages(session, conversation_id)
    history_payload = [{"role": m.role, "content": m.content} for m in history]

    try:
        orchestrated = await orchestrator_service.handle_message(
            llm, payload.message, history_payload, context_text
        )
    except LLMServiceError as exc:
        await session.rollback()
        logger.error("Chat request failed %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await conversation_service.add_message(
        session, conversation_id, "assistant", orchestrated.reply
    )

    try:
        extraction = await llm.extract_fact(payload.message)
        if extraction is not None:
            fact_embedding = await embedder.embed_document(extraction.fact)
            await memory_service.store_memory_if_new(
                session,
                conversation.user_id,
                extraction.fact,
                fact_embedding,
                importance=extraction.importance,
            )
    except LLMServiceError as exc:
        logger.warning("gagal ekstraksi memori (non fatal):%s", exc)
    await session.commit()

    tasks_out = None
    if orchestrated.used_planner and orchestrated.plan_result is not None:
        tasks_out = [
            TaskResultOut(
                description=e.description,
                result=e.result,
                passed_evaluation=e.passed_evaluation,
                attempts=e.attempts,
            )
            for e in orchestrated.plan_result.executions
        ]

    return SendMessageResponse(
        reply=orchestrated.reply,
        model=llm.model,
        conversation_id=conversation_id,
        used_planner=orchestrated.used_planner,
        tasks=tasks_out,
    )

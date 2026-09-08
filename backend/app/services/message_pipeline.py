import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.document_chunk import DocumentChunk
from app.models.goal import Goal
from app.models.memory import Memory
from app.services import (
    conversation_service,
    document_service,
    goal_service,
    memory_service,
    orchestrator_service,
    personalization_service,
)
from app.services.embedding_service import EmbeddingService
from app.services.llm import LLMServiceError
from app.services.llm_provider import MessagePipelineLLM
from app.services.planner_service import PlanExecutionResult

logger = logging.getLogger(__name__)


@dataclass
class MessagePipelineResult:
    reply: str
    model: str
    used_planner: bool
    plan_result: PlanExecutionResult | None = None


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
        facts = "\n".join({f"-{m.content}" for m in memories})
        parts.append(f"Fakta yang kamu ingat tentang user :\n{facts}")

    if chunks:
        excerpts = "\n\n".join(
            f"[Dari dokumen : {c.document.filename}]\n{c.content}" for c in chunks
        )
        parts.append(f"Potongan dokumen yang relean dengan pertanyaan user:\n{excerpts}")

        context = "\n\n".join(parts)
        return (
            f"{context}\n\n"
            "Gunakan informasi di atas kalau relevan untuk menjawab. -- termasuk"
            "menyesuaikan gaya jawabanmu dengan preferensi user, dan "
            "mempertimbangkan tujuan jangka panjangnya kalau relevan. Kalau"
            "menjawab berdasarkan isi dokumen, sebutkan sumbernya. Kalau"
            "tidak relevan, abaikan saja dan jawab seperti biasa"
        )


async def process_incoming_message(
    session: AsyncSession,
    llm: MessagePipelineLLM,
    embedder: EmbeddingService,
    conversation: Conversation,
    message_text: str,
) -> MessagePipelineResult:
    """Proses satu satu pesan masuk dari user, ujung ke ujung : simpan pesan user,
    ambil konteks (memori/RAG/goals), panggil orchestrator, simpan balasan,
    lalu ekstraksi memori baru kalau ada.
    Dipakai baik oleh endpoint HTTP (`send_message` di conversations.py)
    maupun integrasi lain (mis. Telegram) -- logikanya sama persis, cuma
    cara triggernya beda. Fungsi ini TIDAK tahu apa apa soal HTTP -- kalau
    orchestrator galal, dia memberikan `LLMServiceError`
    menjalar ke pemanggil (setelah rollback),
    bukan melempar HTTPException, Tiap pemanggil
    (HTTP route, Telegram bot ) yang
    menerjemahkannya jadi bahasa masing masing
    (503 untu HTTP, pesan error untuk telegram, dst)."""

    await conversation_service.add_message(
        session, 
        conversation.id, 
        "user", 
        message_text
    )

    context_text = None
    try:
        query_embedding = await embedder.embed_query(message_text)
        relevant_memories = await memory_service.retrieve_relevant_memories(
            session, conversation.user_id, query_embedding
        )
        relevant_chunks = await document_service.retrieve_relevant_chunks(
            session,
            conversation.user_id,
            query_embedding,
        )
        active_goals = await goal_service.get_goals(
            session,
            conversation.user_id,
            status="active",
        )
        user = await conversation_service.get_or_create_default_user(session)
        context_text = _build_context_instruction(
            relevant_memories, relevant_chunks, active_goals, user.preferences
        )
    except LLMServiceError as exc:
        logger.warning("Gagal retrieval memori (non-fatal): %s", exc)

    history = await conversation_service.get_messages(session, conversation.id)
    history_payload = [{"role": m.role, "content": m.content} for m in history]

    try:
        orchestrated = await orchestrator_service.handle_message(
            llm, message_text, history_payload, context_text
        )
    except LLMServiceError as exc:
        await session.rollback()
        logger.error("Pemrosesan pesan gagal : %s", exc)
        raise

    await conversation_service.add_message(
        session, conversation.id, "assistant", orchestrated.reply
    )

    try:
        extraction = await llm.extract_fact(message_text)
        if extraction is not None and extraction.fact is not None:
            fact_embedding = await embedder.embed_document(extraction.fact)

            await memory_service.store_memory_if_new(
                    session,
                    conversation.user_id,
                    extraction.fact,
                    fact_embedding,
                    importance=extraction.importance,
            )
    except LLMServiceError as exc:
        logger.warning("gagal ekstraksi memori (non-fatal): %s", exc)

    await session.commit()

    return MessagePipelineResult(
        reply=orchestrated.reply,
        model=llm.model,
        used_planner=orchestrated.used_planner,
        plan_result=orchestrated.plan_result,
    )

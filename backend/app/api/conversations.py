import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_embedding_service, get_llm_service
from app.db.session import get_db_session
from app.schemas.conversation import (
    ConversationCreate,
    ConversationOut,
    MessageOut,
    SendMessageRequest,
    SendMessageResponse,
)
from app.schemas.planner import TaskResultOut
from app.services import conversation_service, message_pipeline
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
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> list[MessageOut]:
    conversation = await conversation_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation tidak ditemukan")

    messages = await conversation_service.get_messages(session, conversation_id)
    return [MessageOut.model_validate(m) for m in messages]


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

    try:
        result = await message_pipeline.process_incoming_message(
            session, llm, embedder, conversation, payload.message
        )
    except LLMServiceError as exc:
        logger.error("Chat request failed %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    tasks_out = None
    if result.used_planner and result.plan_result is not None:
        tasks_out = [
            TaskResultOut(
                description=e.description,
                result=e.result,
                passed_evaluation=e.passed_evaluation,
                attempts=e.attempts,
            )
            for e in result.plan_result.executions
        ]

    return SendMessageResponse(
        reply=result.reply,
        model=result.model,
        conversation_id=conversation_id,
        used_planner=result.used_planner,
        tasks=tasks_out,
    )

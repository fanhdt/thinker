import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_llm_service
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.llm import LLMService, LLMServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def send_chat_message(
    request: ChatRequest,
    service: LLMService = Depends(get_llm_service),
) -> ChatResponse:
    try:
        reply = await service.chat(request.message)
    except LLMServiceError as exc:
        logger.error("Chat request failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ChatResponse(reply=reply, model=service.model)

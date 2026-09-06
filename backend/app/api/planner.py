import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_service
from app.db.session import get_db_session
from app.schemas.planner import PlanRequest, PlanResponse, TaskResultOut
from app.services import conversation_service, planner_service
from app.services.llm import LLMService, LLMServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["planner"])


@router.post("/{conversation_id}/plan", response_model=PlanResponse)
async def create_and_execute_plan(
    conversation_id: uuid.UUID,
    payload: PlanRequest,
    session: AsyncSession = Depends(get_db_session),
    llm: LLMService = Depends(get_llm_service),
) -> PlanResponse:
    conversation = await conversation_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation tidak ditemukan")

    await conversation_service.add_message(session, conversation_id, "user", payload.goal)

    try:
        execution_result = await planner_service.run_plan(llm,payload.goal)
    except LLMServiceError as exc:
        await session.rollback()
        logger.error("Plan execution failed:%s", exc)

    summary = planner_service.build_summary_text(execution_result)
    await conversation_service.add_message(session, conversation_id, "assistant", summary)
    await session.commit()

    return PlanResponse(
        goal=execution_result.goal,
        tasks=[
            TaskResultOut(description=e.description, result=e.result)
            for e in execution_result.executions
        ],
        summary=summary,
        conversation_id=conversation_id,
    )

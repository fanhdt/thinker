import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.goal import GoalCreate, GoalOut, GoalUpdate
from app.services import conversation_service, goal_service

router = APIRouter(prefix="/goals", tags=["goals"])


@router.post("", response_model=GoalOut)
async def create_goal(
    payload: GoalCreate,
    session: AsyncSession = Depends(get_db_session),
) -> GoalOut:
    user = await conversation_service.get_or_create_default_user(session)
    goal = await goal_service.create_goal(session, user.id, payload.description)
    await session.commit()
    return GoalOut.model_validate(goal)


@router.get("", response_model=list[GoalOut])
async def list_goals(
    status: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[GoalOut]:
    user = await conversation_service.get_or_create_default_user(session)
    await session.commit()

    goals = await goal_service.get_goals(session, user.id, status=status)
    return [GoalOut.model_validate(g) for g in goals]


@router.patch("/{goal_id}", response_model=GoalOut)
async def update_goal(
    goal_id: uuid.UUID,
    payload: GoalUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> GoalOut:
    goal = await goal_service.get_goal(session, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal tidak ditemukan")
    goal = await goal_service.update_goal_status(session, goal, payload.status)
    await session.commit()
    return GoalOut.model_validate(goal)

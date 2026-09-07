import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goal import Goal


async def create_goal(session: AsyncSession, user_id: uuid.UUID, description: str) -> Goal:
    goal = Goal(user_id=user_id, description=description)
    session.add(goal)
    await session.flush()
    return goal


async def get_goals(
    session: AsyncSession, user_id: uuid.UUID, *, status: str | None = None
) -> list[Goal]:
    query = select(Goal).where(Goal.user_id == user_id)
    if status is not None:
        query = query.where(Goal.status == status)
    result = await session.execute(query.order_by(Goal.created_at))
    return list(result.scalars().all())


async def get_goal(session: AsyncSession, goal_id: uuid.UUID) -> Goal | None:
    result = await session.execute(select(Goal).where(Goal.id == goal_id))
    return result.scalar_one_or_none()


async def update_goal_status(session: AsyncSession, goal: Goal, status: str) -> Goal:
    goal.status = status
    await session.flush()
    return goal

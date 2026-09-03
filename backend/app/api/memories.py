from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.memory import MemoryOut
from app.services import conversation_service, memory_service

router = APIRouter(prefix="/memories", tags=["memories"])


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    session: AsyncSession = Depends(get_db_session),
) -> list[MemoryOut]:
    user = await conversation_service.get_or_create_default_user(session)
    await session.commit()

    memories = await memory_service.get_all_memories(session, user.id)
    return [MemoryOut.model_validate(m) for m in memories]

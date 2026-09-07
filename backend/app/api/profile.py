from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.profile import ProfileOut, ProfileUpdate
from app.services import conversation_service, profile_service

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileOut)
async def get_profile(session: AsyncSession = Depends(get_db_session)) -> ProfileOut:
    user = await conversation_service.get_or_create_default_user(session)
    await session.commit()
    return ProfileOut.model_validate(user)


@router.patch("", response_model=ProfileOut)
async def update_profile(
    payload: ProfileUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> ProfileOut:
    user = await conversation_service.get_or_create_default_user(session)

    if payload.name is not None:
        user.name = payload.name
    if payload.preferences is not None:
        profile_service.merge_preferences(user, payload.preferences)

    await session.commit()
    return ProfileOut.model_validate(user)

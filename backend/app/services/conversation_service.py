import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message, User

DEFAULT_USER_NAME = "Anda"


async def get_or_create_default_user(session: AsyncSession) -> User:
    result = await session.execute(select(User).limit(1))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(name=DEFAULT_USER_NAME)
        session.add(user)
        await session.flush()
    return user


async def create_conversation(
    session: AsyncSession, user_id: uuid.UUID, title: str
) -> Conversation:
    conversation = Conversation(user_id=user_id, title=title)
    session.add(conversation)
    await session.flush()
    return conversation


async def get_conversation(
    session: AsyncSession, conversation_id: uuid.UUID
) -> Conversation | None:
    result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
    return result.scalar_one_or_none()


async def get_messages(session: AsyncSession, conversation_id: uuid.UUID) -> list[Message] | None:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )

    return list(result.scalars().all())


async def add_message(
    session: AsyncSession, conversation_id: uuid.UUID, role: str, content: str
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
    )
    session.add(message)
    await session.flush()
    return message

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message, User

DEFAULT_USER_NAME = "Anda"

# Jumlah pesan terakhir yang dikirim sebagai konteks ke LLM (`chat_with_history`).
# `get_messages` (dipakai API buat nampilin riwayat ke user) TIDAK dibatasi --
# ini cuma soal apa yang dikirim ke Gemini, bukan apa yang disimpan/ditampilkan.
# Tanpa batas ini, prompt_tokens membesar linear seiring panjang percakapan
# dan akhirnya bisa melebihi context window model.
MAX_HISTORY_MESSAGES_FOR_LLM = 20


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


async def get_or_create_conversation_for_telegram_chat(
    session: AsyncSession, user_id: uuid.UUID, telegram_chat_id: int
) -> Conversation:
    """
    Satu chat Telegram yang dipetakan ke satu Conversation. kalau chat_id ini
    belum pernah tercatat, buat conversation baru untuknya.
    """
    result = await session.execute(
        select(Conversation).where(Conversation.telegram_chat_id == telegram_chat_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is not None:
        return conversation

    conversation = Conversation(
        user_id=user_id, title="Telegram", telegram_chat_id=telegram_chat_id
    )

    session.add(conversation)
    await session.flush()
    return conversation


async def get_messages(session: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )

    return list(result.scalars().all())


async def get_recent_messages_for_llm(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    limit: int = MAX_HISTORY_MESSAGES_FOR_LLM,
) -> list[Message]:
    """Ambil `limit` pesan TERAKHIR dari conversation, urut kronologis (lama -> baru).

    Khusus buat dikirim sebagai history ke `chat_with_history` -- supaya
    prompt_tokens tidak membesar tanpa batas seiring panjangnya percakapan.
    Riwayat lengkap tetap tersimpan utuh di database dan tetap bisa diambil
    lewat `get_messages` (mis. buat API yang nampilin riwayat ke user).
    """
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    recent = list(result.scalars().all())
    recent.reverse()
    return recent


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

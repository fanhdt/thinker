import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory
from app.services.similarity import cosine_similarity

DEDUP_THRESHOLD = 0.92
RETRIEVAL_THRESHOLD = 0.5
MAX_RETRIEVED_MEMORIES = 5

logger = logging.getLogger(__name__)


async def get_all_memories(session: AsyncSession, user_id: uuid.UUID) -> list[Memory]:
    result = await session.execute(select(Memory).where(Memory.user_id == user_id))

    return list(result.scalars().all())


async def store_memory_if_new(
    session: AsyncSession, user_id: uuid.UUID, content: str, embedding: list[float]
) -> Memory | None:
    existing_memories = await get_all_memories(session, user_id)

    for memory in existing_memories:
        if cosine_similarity(memory.embedding, embedding) >= DEDUP_THRESHOLD:
            return None

    memory = Memory(user_id=user_id, content=content, embedding=embedding)
    session.add(memory)
    await session.flush()
    return memory


async def retrieve_relevant_memories(
    session: AsyncSession, user_id: uuid.UUID, query_embedding: list[float]
) -> list[Memory]:
    memories = await get_all_memories(session, user_id)

    scored = [(cosine_similarity(m.embedding, query_embedding), m) for m in memories]

    for score, m in scored:
        logger.info("Memori Similarity Score =%.4f content=%r", score, m.content)

    relevant = [(score, m) for score, m in scored if score >= RETRIEVAL_THRESHOLD]
    relevant.sort(key=lambda pair: pair[0], reverse=True)

    return [m for _, m in relevant[:MAX_RETRIEVED_MEMORIES]]

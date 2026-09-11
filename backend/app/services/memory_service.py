import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import log_event
from app.models.memory import Memory
from app.services.similarity import cosine_similarity

DEDUP_THRESHOLD = 0.92
RETRIEVAL_THRESHOLD = 0.5
MAX_RETRIEVED_MEMORIES = 5

SIMILARITY_WEIGHT = 0.7
IMPORTANCE_WEIGHT = 0.4
MAX_IMPORTANCE = 5

logger = logging.getLogger(__name__)


def _compute_final_score(similarity: float, importance: int) -> float:
    normalized_importance = importance / MAX_IMPORTANCE
    return (SIMILARITY_WEIGHT * similarity) + (IMPORTANCE_WEIGHT * normalized_importance)


async def get_all_memories(session: AsyncSession, user_id: uuid.UUID) -> list[Memory]:
    result = await session.execute(select(Memory).where(Memory.user_id == user_id))

    return list(result.scalars().all())


async def store_memory_if_new(
    session: AsyncSession,
    user_id: uuid.UUID,
    content: str,
    embedding: list[float],
    importance: int = 3,
) -> Memory | None:
    """CREATE memory baru, dengan dedup sebagai jaring pengaman terakhir.

    Dedup di sini murni untuk menangani kasus fakta yang secara redaksi mirip
    tapi lolos sebagai CREATE (bukan UPDATE) dari LLM -- keputusan utama
    CREATE vs UPDATE vs DELETE tetap datang dari `MemoryExtraction.operation`,
    bukan dari threshold similarity ini.
    """
    existing_memories = await get_all_memories(session, user_id)

    for memory in existing_memories:
        if cosine_similarity(memory.embedding, embedding) >= DEDUP_THRESHOLD:
            return None

    memory = Memory(user_id=user_id, content=content, embedding=embedding, importance=importance)
    session.add(memory)
    await session.flush()
    return memory


async def update_memory(
    session: AsyncSession,
    memory: Memory,
    content: str,
    embedding: list[float],
    importance: int = 3,
) -> Memory:
    """UPDATE memory yang sudah ada (mis. preferensi yang berubah)."""
    memory.content = content
    memory.embedding = embedding
    memory.importance = importance
    await session.flush()
    return memory


async def delete_memory(session: AsyncSession, memory: Memory) -> None:
    """DELETE memory (mis. user secara eksplisit minta dilupakan)."""
    await session.delete(memory)
    await session.flush()


async def apply_extraction(
    session: AsyncSession,
    user_id: uuid.UUID,
    operation: str,
    existing_memories: list[Memory],
    content: str | None,
    embedding: list[float] | None,
    importance: int,
    target_index: int | None,
) -> Memory | None:
    """Terapkan satu `MemoryExtraction` ke storage: CREATE/UPDATE/DELETE/IGNORE.

    `existing_memories` dan `target_index` harus konsisten dengan daftar yang
    sama persis yang dikirim ke `llm.extract_fact` -- fungsi ini tidak
    memvalidasi ulang index (itu sudah dilakukan di `llm.extract_fact`),
    hanya mengeksekusinya.
    """
    if operation == "CREATE":
        assert content is not None and embedding is not None
        return await store_memory_if_new(session, user_id, content, embedding, importance)

    if operation == "UPDATE":
        assert content is not None and embedding is not None and target_index is not None
        target = existing_memories[target_index]
        return await update_memory(session, target, content, embedding, importance)

    if operation == "DELETE":
        assert target_index is not None
        target = existing_memories[target_index]
        await delete_memory(session, target)
        return None

    return None


async def retrieve_relevant_memories(
    session: AsyncSession,
    user_id: uuid.UUID,
    query_embedding: list[float],
) -> list[Memory]:
    memories = await get_all_memories(session, user_id)

    scored = [(cosine_similarity(m.embedding, query_embedding), m) for m in memories]

    relevant = [(score, m) for score, m in scored if score >= RETRIEVAL_THRESHOLD]

    relevant.sort(key=lambda pair: pair[0], reverse=True)

    selected = relevant[:MAX_RETRIEVED_MEMORIES]

    log_event(
        logger,
        "memory_retrieval",
        user_id=str(user_id),
        total_memories=len(memories),
        candidates=len(scored),
        relevant_memories=len(relevant),
        returned=len(selected),
    )

    return [m for _, m in selected]

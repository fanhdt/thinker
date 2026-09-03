from app.services.embedding_service import EmbeddingService, embedding_service
from app.services.llm import LLMService, llm_service


def get_llm_service() -> LLMService:
    return llm_service


def get_embedding_service() -> EmbeddingService:
    return embedding_service

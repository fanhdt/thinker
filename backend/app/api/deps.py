from app.services.llm import LLMService, llm_service


def get_llm_service() -> LLMService:
    return llm_service

from fastapi.testclient import TestClient

from app.api.chat import get_llm_service
from app.main import app
from app.services.llm import LLMServiceError


class FakeLLMService:
    model = "fake-model"

    async def chat(self, message: str) -> str:
        return f"echo: {message}"


class FailingLLMService:
    model = "fake-model"

    async def chat(self, message: str) -> str:
        raise LLMServiceError("Simulasi kegagalan gemini")


client = TestClient(app)


def test_chat_returns_reply_from_service():
    app.dependency_overrides[get_llm_service] = lambda: FakeLLMService()
    response = client.post("/chat", json={"message": "halo"})
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "echo: halo"
    assert body["model"] == "fake-model"
    app.dependency_overrides.clear()


def test_Chat_rejects_empty_message():
    response = client.post("/chat", json={"message": ""})
    assert response.status_code == 422


def test_chat_returns_503_when_llm_service_fails():
    app.dependency_overrides[get_llm_service] = lambda: FailingLLMService()
    response = client.post("/chat", json={"message": "halo"})
    assert response.status_code == 503
    app.dependency_overrides.clear()

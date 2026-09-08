import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from app.api.deps import get_embedding_service, get_llm_service
from app.main import app
from app.services.llm import LLMServiceError
from app.services.orchestrator_service import OrchestratedResponse
from app.services.planner_service import PlanExecutionResult, TaskExecution


def _fake_conversation(**overrides):
    conv = MagicMock()
    conv.id = overrides.get("id", uuid.uuid4())
    conv.user_id = overrides.get("user_id", uuid.uuid4())
    conv.title = overrides.get("title", "Percakapan Baru")
    conv.created_at = overrides.get("created_at", datetime.now(UTC))
    return conv


def _override_llm() -> MagicMock:
    fake_llm = MagicMock()
    fake_llm.model = "fake-model"
    fake_llm.extract_fact = AsyncMock(return_value=None)
    app.dependency_overrides[get_llm_service] = lambda: fake_llm
    return fake_llm


def _override_embedder() -> MagicMock:
    fake_embedder = MagicMock()
    fake_embedder.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])
    fake_embedder.embed_document = AsyncMock(return_value=[0.1, 0.2, 0.3])
    app.dependency_overrides[get_embedding_service] = lambda: fake_embedder
    return fake_embedder


def _enter_send_message_happy_path_deps(stack: ExitStack, fake_conversation, fake_user) -> None:
    """Pasang semua patch dasar yang dibutuhkan supaya jalur send_message
    berhasil sampai ke orchestrator, tanpa peduli hasil orchestrator itu sendiri.
    """
    stack.enter_context(
        patch(
            "app.api.conversations.conversation_service.get_conversation",
            new=AsyncMock(return_value=fake_conversation),
        )
    )
    stack.enter_context(
        patch("app.api.conversations.conversation_service.add_message", new=AsyncMock())
    )
    stack.enter_context(
        patch(
            "app.api.conversations.memory_service.retrieve_relevant_memories",
            new=AsyncMock(return_value=[]),
        )
    )
    stack.enter_context(
        patch(
            "app.api.conversations.document_service.retrieve_relevant_chunks",
            new=AsyncMock(return_value=[]),
        )
    )
    stack.enter_context(
        patch("app.api.conversations.goal_service.get_goals", new=AsyncMock(return_value=[]))
    )
    stack.enter_context(
        patch(
            "app.api.conversations.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        )
    )
    stack.enter_context(
        patch("app.api.conversations.conversation_service.get_messages", new=AsyncMock(return_value=[]))
    )


# ---------- POST /conversations ----------


def test_create_conversation_returns_created_conversation(client):
    fake_user = MagicMock(id=uuid.uuid4())
    fake_conversation = _fake_conversation(title="Diskusi Karir")

    with (
        patch(
            "app.api.conversations.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch(
            "app.api.conversations.conversation_service.create_conversation",
            new=AsyncMock(return_value=fake_conversation),
        ) as mock_create,
    ):
        response = client.post("/conversations", json={"title": "Diskusi Karir"})

    assert response.status_code == 200
    assert response.json()["title"] == "Diskusi Karir"
    mock_create.assert_called_once_with(ANY, fake_user.id, "Diskusi Karir")


def test_create_conversation_uses_default_title_when_omitted(client):
    fake_user = MagicMock(id=uuid.uuid4())
    fake_conversation = _fake_conversation(title="Percakapan Baru")

    with (
        patch(
            "app.api.conversations.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch(
            "app.api.conversations.conversation_service.create_conversation",
            new=AsyncMock(return_value=fake_conversation),
        ) as mock_create,
    ):
        response = client.post("/conversations", json={})

    assert response.status_code == 200
    mock_create.assert_called_once_with(ANY, fake_user.id, "Percakapan Baru")


# ---------- GET /conversations/{id}/messages ----------


def test_list_messages_rejects_malformed_conversation_id(client):
    """Regresi bug lama: `conversation_id=uuid.UUID` (pakai '=' bukan ':') membuat
    FastAPI tidak memvalidasi path param sama sekali, meloloskan string
    sembarangan dengan status 200 alih-alih 422.
    """
    response = client.get("/conversations/ini-bukan-uuid-sama-sekali/messages")
    assert response.status_code == 422


def test_list_messages_passes_a_real_uuid_object_to_the_service(client):
    valid_id = uuid.uuid4()

    with (
        patch(
            "app.api.conversations.conversation_service.get_conversation",
            new=AsyncMock(return_value=object()),
        ) as mock_get_conversation,
        patch(
            "app.api.conversations.conversation_service.get_messages",
            new=AsyncMock(return_value=[]),
        ),
    ):
        response = client.get(f"/conversations/{valid_id}/messages")

    assert response.status_code == 200
    assert mock_get_conversation.await_args is not None
    called_conversation_id = mock_get_conversation.await_args.args[1]
    assert isinstance(called_conversation_id, uuid.UUID)
    assert called_conversation_id == valid_id


# ---------- POST /conversations/{id}/messages ----------


def test_send_message_returns_404_when_conversation_not_found(client):
    _override_llm()
    _override_embedder()
    conversation_id = uuid.uuid4()

    with patch(
        "app.api.conversations.conversation_service.get_conversation",
        new=AsyncMock(return_value=None),
    ):
        response = client.post(f"/conversations/{conversation_id}/messages", json={"message": "Halo"})

    assert response.status_code == 404


def test_send_message_rejects_empty_message(client):
    _override_llm()
    _override_embedder()
    conversation_id = uuid.uuid4()

    response = client.post(f"/conversations/{conversation_id}/messages", json={"message": ""})
    assert response.status_code == 422


def test_send_message_returns_503_when_orchestrator_fails(client):
    _override_llm()
    _override_embedder()
    conversation_id = uuid.uuid4()
    fake_conversation = _fake_conversation(id=conversation_id)
    fake_user = MagicMock(preferences={})

    with ExitStack() as stack:
        _enter_send_message_happy_path_deps(stack, fake_conversation, fake_user)
        stack.enter_context(
            patch(
                "app.api.conversations.orchestrator_service.handle_message",
                new=AsyncMock(side_effect=LLMServiceError("gagal chat")),
            )
        )
        response = client.post(f"/conversations/{conversation_id}/messages", json={"message": "Halo"})

    assert response.status_code == 503


def test_send_message_returns_reply_on_success(client):
    _override_llm()
    _override_embedder()
    conversation_id = uuid.uuid4()
    fake_conversation = _fake_conversation(id=conversation_id)
    fake_user = MagicMock(preferences={})

    with ExitStack() as stack:
        _enter_send_message_happy_path_deps(stack, fake_conversation, fake_user)
        stack.enter_context(
            patch(
                "app.api.conversations.orchestrator_service.handle_message",
                new=AsyncMock(return_value=OrchestratedResponse(reply="Halo juga!", used_planner=False)),
            )
        )
        response = client.post(f"/conversations/{conversation_id}/messages", json={"message": "Halo"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Halo juga!"
    assert body["used_planner"] is False
    assert body["tasks"] is None


def test_send_message_continues_when_memory_retrieval_fails_non_fatally(client):
    """embed_query gagal (mis. Gemini down) TIDAK BOLEH menggagalkan seluruh
    chat -- ini jalur graceful-degradation yang eksplisit di kode
    (except LLMServiceError -> log warning, lanjut tanpa context_text).
    """
    _override_llm()
    fake_embedder = _override_embedder()
    fake_embedder.embed_query = AsyncMock(side_effect=LLMServiceError("gemini down"))

    conversation_id = uuid.uuid4()
    fake_conversation = _fake_conversation(id=conversation_id)
    fake_user = MagicMock(preferences={})

    with ExitStack() as stack:
        _enter_send_message_happy_path_deps(stack, fake_conversation, fake_user)
        stack.enter_context(
            patch(
                "app.api.conversations.orchestrator_service.handle_message",
                new=AsyncMock(return_value=OrchestratedResponse(reply="Tetap jawab", used_planner=False)),
            )
        )
        response = client.post(f"/conversations/{conversation_id}/messages", json={"message": "Halo"})

    assert response.status_code == 200
    assert response.json()["reply"] == "Tetap jawab"


def test_send_message_stores_memory_when_fact_extracted(client):
    fake_llm = _override_llm()
    fake_llm.extract_fact = AsyncMock(
        return_value=MagicMock(fact="User suka kopi tanpa gula", importance=3, has_memory=True)
    )
    fake_embedder = _override_embedder()

    conversation_id = uuid.uuid4()
    fake_conversation = _fake_conversation(id=conversation_id)
    fake_user = MagicMock(preferences={})

    with ExitStack() as stack:
        _enter_send_message_happy_path_deps(stack, fake_conversation, fake_user)
        stack.enter_context(
            patch(
                "app.api.conversations.orchestrator_service.handle_message",
                new=AsyncMock(return_value=OrchestratedResponse(reply="Dicatat!", used_planner=False)),
            )
        )
        mock_store = stack.enter_context(
            patch("app.api.conversations.memory_service.store_memory_if_new", new=AsyncMock())
        )
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"message": "Aku suka kopi tanpa gula"},
        )

    assert response.status_code == 200
    fake_embedder.embed_document.assert_called_once_with("User suka kopi tanpa gula")
    mock_store.assert_called_once_with(
        ANY, fake_conversation.user_id, "User suka kopi tanpa gula", ANY, importance=3
    )


def test_send_message_skips_memory_storage_when_no_fact_extracted(client):
    fake_llm = _override_llm()
    fake_llm.extract_fact = AsyncMock(return_value=None)
    _override_embedder()

    conversation_id = uuid.uuid4()
    fake_conversation = _fake_conversation(id=conversation_id)
    fake_user = MagicMock(preferences={})

    with ExitStack() as stack:
        _enter_send_message_happy_path_deps(stack, fake_conversation, fake_user)
        stack.enter_context(
            patch(
                "app.api.conversations.orchestrator_service.handle_message",
                new=AsyncMock(return_value=OrchestratedResponse(reply="Oke", used_planner=False)),
            )
        )
        mock_store = stack.enter_context(
            patch("app.api.conversations.memory_service.store_memory_if_new", new=AsyncMock())
        )
        response = client.post(f"/conversations/{conversation_id}/messages", json={"message": "Apa kabar?"})

    assert response.status_code == 200
    mock_store.assert_not_called()


def test_send_message_includes_tasks_when_planner_used(client):
    _override_llm()
    _override_embedder()
    conversation_id = uuid.uuid4()
    fake_conversation = _fake_conversation(id=conversation_id)
    fake_user = MagicMock(preferences={})

    plan_result = PlanExecutionResult(
        goal="Rencanakan olahraga",
        executions=[
            TaskExecution(description="Jogging", result="Selesai", passed_evaluation=True, attempts=1)
        ],
    )

    with ExitStack() as stack:
        _enter_send_message_happy_path_deps(stack, fake_conversation, fake_user)
        stack.enter_context(
            patch(
                "app.api.conversations.orchestrator_service.handle_message",
                new=AsyncMock(
                    return_value=OrchestratedResponse(
                        reply="Ini rencananya", used_planner=True, plan_result=plan_result
                    )
                ),
            )
        )
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"message": "Rencanakan olahraga ringan"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["used_planner"] is True
    assert body["tasks"][0]["description"] == "Jogging"
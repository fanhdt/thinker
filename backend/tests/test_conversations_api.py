import uuid
from datetime import UTC, datetime
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from app.services.llm import LLMServiceError
from app.services.message_pipeline import MessagePipelineResult
from app.services.planner_service import PlanExecutionResult, TaskExecution


def _fake_conversation(**overrides):
    conv = MagicMock()
    conv.id = overrides.get("id", uuid.uuid4())
    conv.user_id = overrides.get("user_id", uuid.uuid4())
    conv.title = overrides.get("title", "Percakapan Baru")
    conv.created_at = overrides.get("created_at", datetime.now(UTC))
    return conv


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
#
# Logika inti (retrieval memori/RAG, orchestrator, ekstraksi memori) sudah
# dipindah ke message_pipeline.process_incoming_message dan diuji detail di
# test_message_pipeline.py. Di sini kita cuma perlu menguji tanggung jawab
# route itu sendiri: pemetaan 404/422/503, dan pembentukan response.


def test_send_message_returns_404_when_conversation_not_found(client):
    conversation_id = uuid.uuid4()

    with patch(
        "app.api.conversations.conversation_service.get_conversation",
        new=AsyncMock(return_value=None),
    ):
        response = client.post(
            f"/conversations/{conversation_id}/messages", json={"message": "Halo"}
        )

    assert response.status_code == 404


def test_send_message_rejects_empty_message(client):
    conversation_id = uuid.uuid4()
    response = client.post(f"/conversations/{conversation_id}/messages", json={"message": ""})
    assert response.status_code == 422


def test_send_message_returns_503_when_pipeline_fails(client):
    conversation_id = uuid.uuid4()
    fake_conversation = _fake_conversation(id=conversation_id)

    with (
        patch(
            "app.api.conversations.conversation_service.get_conversation",
            new=AsyncMock(return_value=fake_conversation),
        ),
        patch(
            "app.api.conversations.message_pipeline.process_incoming_message",
            new=AsyncMock(side_effect=LLMServiceError("gagal chat")),
        ),
    ):
        response = client.post(
            f"/conversations/{conversation_id}/messages", json={"message": "Halo"}
        )

    assert response.status_code == 503


def test_send_message_returns_reply_on_success(client):
    conversation_id = uuid.uuid4()
    fake_conversation = _fake_conversation(id=conversation_id)
    pipeline_result = MessagePipelineResult(
        reply="Halo juga!", model="fake-model", used_planner=False
    )

    with (
        patch(
            "app.api.conversations.conversation_service.get_conversation",
            new=AsyncMock(return_value=fake_conversation),
        ),
        patch(
            "app.api.conversations.message_pipeline.process_incoming_message",
            new=AsyncMock(return_value=pipeline_result),
        ),
    ):
        response = client.post(
            f"/conversations/{conversation_id}/messages", json={"message": "Halo"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Halo juga!"
    assert body["model"] == "fake-model"
    assert body["used_planner"] is False
    assert body["tasks"] is None


def test_send_message_includes_tasks_when_planner_used(client):
    conversation_id = uuid.uuid4()
    fake_conversation = _fake_conversation(id=conversation_id)
    plan_result = PlanExecutionResult(
        goal="Rencanakan olahraga",
        executions=[
            TaskExecution(
                description="Jogging", result="Selesai", passed_evaluation=True, attempts=1
            )
        ],
    )
    pipeline_result = MessagePipelineResult(
        reply="Ini rencananya", model="fake-model", used_planner=True, plan_result=plan_result
    )

    with (
        patch(
            "app.api.conversations.conversation_service.get_conversation",
            new=AsyncMock(return_value=fake_conversation),
        ),
        patch(
            "app.api.conversations.message_pipeline.process_incoming_message",
            new=AsyncMock(return_value=pipeline_result),
        ),
    ):
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"message": "Rencanakan olahraga ringan"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["used_planner"] is True
    assert body["tasks"][0]["description"] == "Jogging"

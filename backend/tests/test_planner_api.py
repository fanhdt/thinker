import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.deps import get_llm_service
from app.main import app
from app.services.llm import LLMServiceError
from app.services.planner_service import PlanExecutionResult, TaskExecution


def _override_llm() -> MagicMock:
    fake_llm = MagicMock()
    app.dependency_overrides[get_llm_service] = lambda: fake_llm
    return fake_llm


def test_create_and_execute_plan_returns_404_when_conversation_not_found(client):
    _override_llm()
    conversation_id = uuid.uuid4()

    with patch(
        "app.api.planner.conversation_service.get_conversation",
        new=AsyncMock(return_value=None),
    ):
        response = client.post(f"/conversations/{conversation_id}/plan", json={"goal": "Belajar Rust"})

    assert response.status_code == 404


def test_create_and_execute_plan_returns_503_when_llm_fails(client):
    _override_llm()
    conversation_id = uuid.uuid4()
    fake_conversation = MagicMock()
    fake_user = MagicMock(id=uuid.uuid4(), preferences={})

    with (
        patch(
            "app.api.planner.conversation_service.get_conversation",
            new=AsyncMock(return_value=fake_conversation),
        ),
        patch("app.api.planner.conversation_service.add_message", new=AsyncMock()),
        patch(
            "app.api.planner.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch("app.api.planner.goal_service.get_goals", new=AsyncMock(return_value=[])),
        patch(
            "app.api.planner.planner_service.run_plan",
            new=AsyncMock(side_effect=LLMServiceError("gagal membuat plan")),
        ),
    ):
        response = client.post(f"/conversations/{conversation_id}/plan", json={"goal": "Belajar Rust"})

    assert response.status_code == 503


def test_create_and_execute_plan_returns_completed_plan(client):
    _override_llm()
    conversation_id = uuid.uuid4()
    fake_conversation = MagicMock()
    fake_user = MagicMock(id=uuid.uuid4(), preferences={})

    fake_result = PlanExecutionResult(
        goal="Belajar Rust",
        executions=[
            TaskExecution(
                description="Install Rust", result="Rust terinstall", passed_evaluation=True, attempts=1
            )
        ],
    )

    with (
        patch(
            "app.api.planner.conversation_service.get_conversation",
            new=AsyncMock(return_value=fake_conversation),
        ),
        patch("app.api.planner.conversation_service.add_message", new=AsyncMock()),
        patch(
            "app.api.planner.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch("app.api.planner.goal_service.get_goals", new=AsyncMock(return_value=[])),
        patch(
            "app.api.planner.planner_service.run_plan",
            new=AsyncMock(return_value=fake_result),
        ),
        patch(
            "app.api.planner.planner_service.build_summary_text",
            return_value="Ringkasan: goal tercapai",
        ),
    ):
        response = client.post(f"/conversations/{conversation_id}/plan", json={"goal": "Belajar Rust"})

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "Ringkasan: goal tercapai"
    assert body["tasks"][0]["description"] == "Install Rust"
    assert body["tasks"][0]["passed_evaluation"] is True


def test_create_and_execute_plan_rejects_empty_goal(client):
    _override_llm()
    conversation_id = uuid.uuid4()
    response = client.post(f"/conversations/{conversation_id}/plan", json={"goal": ""})
    assert response.status_code == 422
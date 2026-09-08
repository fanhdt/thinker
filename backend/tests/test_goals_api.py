import uuid
from datetime import UTC, datetime
from unittest.mock import ANY, AsyncMock, MagicMock, patch


def _fake_goal(**overrides):
    goal = MagicMock()
    goal.id = overrides.get("id", uuid.uuid4())
    goal.description = overrides.get("description", "Olahraga 3x seminggu")
    goal.status = overrides.get("status", "active")
    goal.created_at = overrides.get("created_at", datetime.now(UTC))
    return goal


def test_create_goal_returns_created_goal(client):
    fake_user = MagicMock(id=uuid.uuid4())
    fake_goal = _fake_goal(description="Belajar Python")

    with (
        patch(
            "app.api.goals.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch(
            "app.api.goals.goal_service.create_goal",
            new=AsyncMock(return_value=fake_goal),
        ) as mock_create,
    ):
        response = client.post("/goals", json={"description": "Belajar Python"})

    assert response.status_code == 200
    assert response.json()["description"] == "Belajar Python"
    mock_create.assert_called_once_with(ANY, fake_user.id, "Belajar Python")


def test_create_goal_rejects_empty_description(client):
    """Skema GoalCreate mensyaratkan min_length=1 -- pastikan itu benar-benar
    ditegakkan di level HTTP, bukan cuma tertulis di schema."""
    response = client.post("/goals", json={"description": ""})
    assert response.status_code == 422


def test_list_goals_returns_goals_for_default_user(client):
    fake_user = MagicMock(id=uuid.uuid4())
    fake_goals = [_fake_goal(description="Goal A"), _fake_goal(description="Goal B")]

    with (
        patch(
            "app.api.goals.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch(
            "app.api.goals.goal_service.get_goals",
            new=AsyncMock(return_value=fake_goals),
        ),
    ):
        response = client.get("/goals")

    assert response.status_code == 200
    descriptions = [g["description"] for g in response.json()]
    assert descriptions == ["Goal A", "Goal B"]


def test_list_goals_passes_status_query_param_through(client):
    fake_user = MagicMock(id=uuid.uuid4())

    with (
        patch(
            "app.api.goals.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch(
            "app.api.goals.goal_service.get_goals",
            new=AsyncMock(return_value=[]),
        ) as mock_get_goals,
    ):
        response = client.get("/goals?status=completed")

    assert response.status_code == 200
    assert mock_get_goals.call_args.kwargs["status"] == "completed"


def test_update_goal_changes_status(client):
    goal_id = uuid.uuid4()
    fake_goal = _fake_goal(id=goal_id, status="active")
    updated_goal = _fake_goal(id=goal_id, status="completed")

    with (
        patch(
            "app.api.goals.goal_service.get_goal",
            new=AsyncMock(return_value=fake_goal),
        ),
        patch(
            "app.api.goals.goal_service.update_goal_status",
            new=AsyncMock(return_value=updated_goal),
        ) as mock_update,
    ):
        response = client.patch(f"/goals/{goal_id}", json={"status": "completed"})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    mock_update.assert_called_once_with(ANY, fake_goal, "completed")


def test_update_goal_returns_404_when_not_found(client):
    goal_id = uuid.uuid4()

    with patch(
        "app.api.goals.goal_service.get_goal",
        new=AsyncMock(return_value=None),
    ):
        response = client.patch(f"/goals/{goal_id}", json={"status": "completed"})

    assert response.status_code == 404


def test_update_goal_rejects_invalid_status_value(client):
    """GoalUpdate.status punya pattern '^(active|completed)$' -- pastikan
    status sembarangan ditolak sebelum sempat menyentuh service layer."""
    goal_id = uuid.uuid4()
    response = client.patch(f"/goals/{goal_id}", json={"status": "bukan-status-valid"})
    assert response.status_code == 422

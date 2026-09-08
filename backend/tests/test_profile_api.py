import uuid
from unittest.mock import AsyncMock, MagicMock, patch


def _fake_user(**overrides):
    user = MagicMock()
    user.id = overrides.get("id", uuid.uuid4())
    user.name = overrides.get("name", "Budi")
    user.preferences = overrides.get("preferences", {})
    return user


def test_get_profile_returns_default_user(client):
    fake_user = _fake_user(name="Budi")

    with patch(
        "app.api.profile.conversation_service.get_or_create_default_user",
        new=AsyncMock(return_value=fake_user),
    ):
        response = client.get("/profile")

    assert response.status_code == 200
    assert response.json()["name"] == "Budi"


def test_update_profile_changes_name(client):
    fake_user = _fake_user(name="Nama Lama")

    with patch(
        "app.api.profile.conversation_service.get_or_create_default_user",
        new=AsyncMock(return_value=fake_user),
    ):
        response = client.patch("/profile", json={"name": "Nama Baru"})

    assert response.status_code == 200
    assert fake_user.name == "Nama Baru"


def test_update_profile_merges_preferences(client):
    fake_user = _fake_user(preferences={"tone": "formal"})

    with (
        patch(
            "app.api.profile.conversation_service.get_or_create_default_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch("app.api.profile.profile_service.merge_preferences") as mock_merge,
    ):
        response = client.patch("/profile", json={"preferences": {"topic": "olahraga"}})

    assert response.status_code == 200
    mock_merge.assert_called_once_with(fake_user, {"topic": "olahraga"})


def test_update_profile_rejects_invalid_body(client):
    response = client.patch("/profile", json={"preferences": "bukan-dict"})
    assert response.status_code == 422

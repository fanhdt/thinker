from app.models.user import User
from app.services.profile_service import merge_preferences


def test_merge_preferences_adds_new_keys():
    user = User(preferences={})
    merge_preferences(user, {"tone": "santai"})
    assert user.preferences == {"tone": "santai"}


def test_merge_preferences_keeps_existing_keys_not_overriden():
    user = User(preferences={"tone": "santai", "language": "id"})
    merge_preferences(user, {"response_length": "singkat"})
    assert user.preferences == {
        "tone": "santai",
        "language": "id",
        "response_length": "singkat",
    }


def test_merge_preferences_overrides_only_specified_keys():
    user = User(preferences={"tone": "formal", "language": "id"})
    merge_preferences(user, {"tone": "santai"})
    assert user.preferences == {"tone": "santai", "language": "id"}

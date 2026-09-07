from app.models.user import User


def merge_preferences(user: User, new_preferences: dict) -> User:
    user.preferences = {**(user.preferences or {}), **new_preferences}
    return user

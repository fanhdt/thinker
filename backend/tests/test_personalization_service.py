from app.models.goal import Goal
from app.services.personalization_service import build_personalization_context


def test_empty_goals_and_preferences_returns_empty_string():
    assert build_personalization_context([], {}) == ""


def test_preferences_only():
    text = build_personalization_context([], {"tone": "santai"})
    assert "tone" in text
    assert "santai" in text


def test_goals_only():
    goal = Goal(description="Belajar main gitar")
    text = build_personalization_context([goal], {})
    assert "Belajar main gitar" in text


def test_both_goals_and_preferences_included():
    goal = Goal(description="Belajar main gitar")
    text = build_personalization_context([goal], {"tone": "santai"})
    assert "Belajar main gitar" in text
    assert "santai" in text

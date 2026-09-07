from app.services.memory_service import _compute_final_score


def test_higher_similarity_scores_higher_with_same_importance():
    score_low_sim = _compute_final_score(similarity=0.5, importance=3)
    score_high_sim = _compute_final_score(similarity=0.8, importance=3)
    assert score_high_sim > score_low_sim


def test_higher_importance_score_higher_with_same_similarity():
    score_low_importance = _compute_final_score(similarity=0.6, importance=1)
    score_high_importance = _compute_final_score(similarity=0.6, importance=5)
    assert score_high_importance > score_low_importance


def test_high_importance_can_outrank_slightly_higher_similarity():
    score_a = _compute_final_score(similarity=0.65, importance=1)
    score_b = _compute_final_score(similarity=0.55, importance=5)
    assert score_b > score_a


def test_importance_does_not_dominate_similarity_completely():
    score_very_low_sim_high_importance = _compute_final_score(similarity=0.1, importance=5)
    score_high_sim_low_importance = _compute_final_score(similarity=0.9, importance=1)
    assert score_high_sim_low_importance > score_very_low_sim_high_importance

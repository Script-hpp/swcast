import numpy as np

from swcast.metrics import (
    best_true_skill_statistic,
    block_bootstrap_ci,
    brier_score,
    brier_skill_score,
    reliability_diagram,
    true_skill_statistic,
)


def test_brier_score_hand_example():
    y_true = [1, 0, 1, 0]
    y_prob = [0.8, 0.2, 0.6, 0.4]
    # ((0.8-1)^2 + (0.2-0)^2 + (0.6-1)^2 + (0.4-0)^2) / 4 = 0.4 / 4
    assert brier_score(y_true, y_prob) == 0.1


def test_brier_score_perfect_forecast_is_zero():
    assert brier_score([1, 0, 1], [1.0, 0.0, 1.0]) == 0.0


def test_brier_skill_score_hand_example():
    y_true = [1, 0, 1, 0]
    y_prob = [0.8, 0.2, 0.6, 0.4]
    y_prob_ref = [0.5, 0.5, 0.5, 0.5]
    # BS = 0.1, BS_ref = 0.25 -> BSS = 1 - 0.1/0.25 = 0.6
    assert brier_skill_score(y_true, y_prob, y_prob_ref) == 0.6


def test_brier_skill_score_matching_reference_is_zero():
    y_true = [1, 0, 1, 0]
    y_prob = [0.8, 0.2, 0.6, 0.4]
    assert brier_skill_score(y_true, y_prob, y_prob) == 0.0


def test_true_skill_statistic_perfect_forecast():
    y_true = [1, 0, 1, 0]
    y_prob = [0.8, 0.2, 0.6, 0.4]
    assert true_skill_statistic(y_true, y_prob, threshold=0.5) == 1.0


def test_true_skill_statistic_always_negative_forecast():
    # Forecast never fires: sensitivity = 0, specificity = 1 -> TSS = 0 - 0 = 0.
    y_true = [1, 0, 1, 0]
    y_prob = [0.1, 0.1, 0.1, 0.1]
    assert true_skill_statistic(y_true, y_prob, threshold=0.5) == 0.0


def test_best_true_skill_statistic_finds_perfect_threshold():
    y_true = [1, 0, 1, 0]
    y_prob = [0.8, 0.2, 0.6, 0.4]
    best_tss, threshold = best_true_skill_statistic(y_true, y_prob)
    assert best_tss == 1.0
    assert 0.4 < threshold <= 0.6


def test_best_true_skill_statistic_no_positive_events_returns_nan_not_crash():
    # All-zero y_true -> sensitivity is 0/0 (NaN) at every threshold. Must
    # return NaN gracefully, not raise (this is a real, common case: a rare
    # class with zero events in a short window).
    y_true = [0, 0, 0, 0]
    y_prob = [0.1, 0.4, 0.6, 0.9]
    best_tss, threshold = best_true_skill_statistic(y_true, y_prob)
    assert np.isnan(best_tss)
    assert np.isnan(threshold)


def test_reliability_diagram_two_bins_hand_example():
    y_true = [0, 0, 1, 1]
    y_prob = [0.2, 0.4, 0.6, 0.8]
    diag = reliability_diagram(y_true, y_prob, n_bins=2)
    assert list(diag["count"]) == [2, 2]
    assert np.allclose(diag["mean_forecast"], [0.3, 0.7])
    assert np.allclose(diag["observed_frequency"], [0.0, 1.0])


def test_reliability_diagram_skips_empty_bins():
    y_true = [1, 1]
    y_prob = [0.91, 0.95]
    diag = reliability_diagram(y_true, y_prob, n_bins=10)
    assert len(diag["count"]) == 1
    assert diag["count"][0] == 2


def test_block_bootstrap_ci_point_estimate_matches_direct_computation():
    rng = np.random.default_rng(0)
    n_days = 60
    day_index = np.repeat(np.arange(n_days), 3)
    y_true = rng.integers(0, 2, size=n_days * 3).astype(float)
    y_prob = rng.uniform(size=n_days * 3)
    values = np.column_stack([y_true, y_prob])

    def stat_fn(v):
        return brier_score(v[:, 0], v[:, 1])

    point, low, high = block_bootstrap_ci(
        values, day_index, stat_fn, block_length_days=10, n_iterations=200, seed=0
    )
    assert point == brier_score(y_true, y_prob)
    assert low <= point + 1e-9
    assert high >= point - 1e-9
    assert low <= high


def test_block_bootstrap_ci_falls_back_when_fewer_days_than_block_length():
    day_index = np.array([0, 0, 1, 1, 2, 2])
    values = np.array([[1, 0.9], [0, 0.1], [1, 0.8], [0, 0.2], [1, 0.7], [0, 0.3]])

    def stat_fn(v):
        return brier_score(v[:, 0], v[:, 1])

    point, low, high = block_bootstrap_ci(
        values, day_index, stat_fn, block_length_days=27, n_iterations=100, seed=1
    )
    assert point == stat_fn(values)
    assert low <= high

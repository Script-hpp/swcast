"""Verification metrics for probabilistic flare/Kp forecasts (PRD.md FR-0.5/FR-0.6).

All functions take 1D arrays of true binary outcomes (`y_true`, 0/1) and
forecast probabilities (`y_prob`, 0-1) for a single class and take the
model/window alignment as already done by the caller (labels.py).
"""

from __future__ import annotations

import numpy as np


def brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    return float(np.mean((y_prob - y_true) ** 2))


def brier_skill_score(
    y_true: np.ndarray, y_prob: np.ndarray, y_prob_ref: np.ndarray
) -> float:
    """BSS = 1 - BS(forecast) / BS(reference). Reference is typically climatology."""
    bs = brier_score(y_true, y_prob)
    bs_ref = brier_score(y_true, y_prob_ref)
    if bs_ref == 0:
        return float("nan")
    return 1.0 - bs / bs_ref


def true_skill_statistic(y_true: np.ndarray, y_prob: np.ndarray, threshold: float) -> float:
    """TSS = sensitivity - (1 - specificity) = TP/(TP+FN) - FP/(FP+TN), at a fixed threshold."""
    y_true = np.asarray(y_true, dtype=bool)
    forecast = np.asarray(y_prob) >= threshold

    tp = int(np.sum(forecast & y_true))
    fn = int(np.sum(~forecast & y_true))
    fp = int(np.sum(forecast & ~y_true))
    tn = int(np.sum(~forecast & ~y_true))

    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    specificity = tn / (tn + fp) if (tn + fp) > 0 else float("nan")
    return sensitivity - (1.0 - specificity)


def best_true_skill_statistic(
    y_true: np.ndarray, y_prob: np.ndarray
) -> tuple[float, float]:
    """Search all distinct forecast probabilities as candidate thresholds and
    return (max_tss, threshold_at_max). Ties keep the first (lowest) threshold.
    """
    y_prob = np.asarray(y_prob, dtype=float)
    candidates = np.unique(y_prob)
    scores = [true_skill_statistic(y_true, y_prob, t) for t in candidates]
    best_idx = int(np.nanargmax(scores))
    return scores[best_idx], float(candidates[best_idx])


def reliability_diagram(
    y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10
) -> dict[str, np.ndarray]:
    """Bin forecasts into `n_bins` equal-width bins over [0, 1].

    Returns arrays (one entry per non-empty bin): `bin_center`,
    `mean_forecast` (mean y_prob in bin), `observed_frequency` (mean y_true
    in bin), `count`.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.clip(np.digitize(y_prob, edges[1:-1], right=True), 0, n_bins - 1)

    bin_centers, mean_forecast, observed_frequency, counts = [], [], [], []
    for b in range(n_bins):
        mask = bin_idx == b
        count = int(np.sum(mask))
        if count == 0:
            continue
        bin_centers.append((edges[b] + edges[b + 1]) / 2.0)
        mean_forecast.append(float(np.mean(y_prob[mask])))
        observed_frequency.append(float(np.mean(y_true[mask])))
        counts.append(count)

    return {
        "bin_center": np.array(bin_centers),
        "mean_forecast": np.array(mean_forecast),
        "observed_frequency": np.array(observed_frequency),
        "count": np.array(counts),
    }


def block_bootstrap_ci(
    values: np.ndarray,
    day_index: np.ndarray,
    statistic_fn,
    block_length_days: int = 27,
    n_iterations: int = 1000,
    ci: float = 0.95,
    seed: int | None = None,
) -> tuple[float, float, float]:
    """Block bootstrap over days (PRD.md FR-0.6): resample contiguous blocks
    of `block_length_days` distinct days (with replacement) until the
    resampled series covers at least as many days as the original, then
    apply `statistic_fn` to the rows for those days.

    `values` is any array `statistic_fn` understands (e.g. a 2-column array
    of (y_true, y_prob) pairs); `day_index` assigns each row in `values` to
    an integer day, aligned 1:1 by position. `statistic_fn` takes a filtered
    `values` array and returns a scalar.

    Returns (point_estimate, ci_low, ci_high).
    """
    rng = np.random.default_rng(seed)
    unique_days = np.unique(day_index)
    n_days = len(unique_days)
    day_to_rows = {d: np.where(day_index == d)[0] for d in unique_days}

    point_estimate = statistic_fn(values)

    n_blocks_needed = int(np.ceil(n_days / block_length_days))
    max_start = n_days - block_length_days
    boot_stats = []
    for _ in range(n_iterations):
        if max_start < 0:
            sampled_days = rng.choice(unique_days, size=n_days, replace=True)
        else:
            block_starts = rng.integers(0, max_start + 1, size=n_blocks_needed)
            sampled_days = np.concatenate(
                [unique_days[s : s + block_length_days] for s in block_starts]
            )[:n_days]
        row_idx = np.concatenate([day_to_rows[d] for d in sampled_days])
        boot_stats.append(statistic_fn(values[row_idx]))

    alpha = (1.0 - ci) / 2.0
    ci_low, ci_high = np.quantile(boot_stats, [alpha, 1.0 - alpha])
    return float(point_estimate), float(ci_low), float(ci_high)

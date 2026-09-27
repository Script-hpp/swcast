"""Reference baselines for flare-window forecasts (PRD.md FR-0.4).

All baselines operate on the output of `labels.label_windows` (one row per
canonical 24h window, one 0/1 column per class), sorted by `window_start`
ascending, and return values aligned 1:1 with the input rows. Baselines only
ever use windows STRICTLY BEFORE the target window (`closed="left"` on the
rolling window) -- no lookahead. The first window(s) in a series have no
prior history and get NaN.
"""

from __future__ import annotations

import pandas as pd


def _trailing_rate(labeled_windows: pd.DataFrame, class_name: str, days: int) -> pd.core.window.rolling.Rolling:
    series = pd.Series(
        labeled_windows[class_name].to_numpy(dtype=float),
        index=pd.DatetimeIndex(labeled_windows["window_start"]),
    )
    return series.rolling(f"{days}D", closed="left")


def climatology_baseline(
    labeled_windows: pd.DataFrame, class_name: str, lookback_days: int = 365
) -> pd.DataFrame:
    """Trailing event rate over the `lookback_days` before each window's start.

    Returns a DataFrame (same row order/index as `labeled_windows`) with
    columns `probability` (NaN if no prior window exists) and
    `n_history_windows` (count of prior windows actually used -- fewer than
    a full `lookback_days` worth near the start of the series is the
    "shortened lookback" case, not an error; callers should report it).
    """
    rolling = _trailing_rate(labeled_windows, class_name, lookback_days)
    # rolling.count() returns NaN (not 0) for a fully empty window -- normalize
    # so n_history_windows is always a meaningful integer count.
    n_history = rolling.count().fillna(0).to_numpy()
    return pd.DataFrame(
        {
            "probability": rolling.mean().to_numpy(),
            "n_history_windows": n_history,
        },
        index=labeled_windows.index,
    )


def persistence_baseline(
    labeled_windows: pd.DataFrame,
    class_name: str,
    p_if_positive: float = 0.8,
    p_if_negative: float = 0.2,
) -> pd.Series:
    """Smoothed persistence: p_if_positive if the PREVIOUS window was
    positive for `class_name`, else p_if_negative. NaN for the first window
    (no previous window to persist from).
    """
    prev = labeled_windows[class_name].shift(1)
    return prev.map({1: p_if_positive, 0: p_if_negative})


def rolling_rate_baseline(
    labeled_windows: pd.DataFrame, class_name: str, window_days: int = 27
) -> pd.Series:
    """Trailing event rate over the `window_days` before each window's start."""
    return _trailing_rate(labeled_windows, class_name, window_days).mean()

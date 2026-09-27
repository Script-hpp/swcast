import numpy as np
import pandas as pd

from swcast.baselines import (
    climatology_baseline,
    persistence_baseline,
    rolling_rate_baseline,
)


def _daily_windows(values: list[int]) -> pd.DataFrame:
    starts = pd.date_range("2026-01-01", periods=len(values), freq="24h")
    return pd.DataFrame(
        {
            "window_start": starts,
            "window_end": starts + pd.Timedelta(hours=24),
            "C+": values,
        }
    )


def test_climatology_baseline_hand_example():
    # values at day0..day4 = [1, 0, 1, 0, 1]; lookback_days=3 means the
    # trailing 3 calendar days before each window's start (see module
    # docstring: closed="left" -> [t - lookback, t)).
    labeled = _daily_windows([1, 0, 1, 0, 1])
    result = climatology_baseline(labeled, "C+", lookback_days=3)

    assert np.isnan(result["probability"].iloc[0])
    assert result["n_history_windows"].iloc[0] == 0

    assert result["probability"].iloc[1] == 1.0  # day0 only: [1]
    assert result["n_history_windows"].iloc[1] == 1

    assert result["probability"].iloc[2] == 0.5  # day0,day1: [1,0]
    assert result["n_history_windows"].iloc[2] == 2

    assert abs(result["probability"].iloc[3] - 2 / 3) < 1e-9  # day0,1,2: [1,0,1]
    assert result["n_history_windows"].iloc[3] == 3

    assert abs(result["probability"].iloc[4] - 1 / 3) < 1e-9  # day1,2,3: [0,1,0]
    assert result["n_history_windows"].iloc[4] == 3


def test_climatology_baseline_shortened_lookback_reported():
    # Only 2 days of history exist, but lookback_days=365 is requested --
    # n_history_windows must reflect what was actually available, not 365.
    labeled = _daily_windows([1, 0])
    result = climatology_baseline(labeled, "C+", lookback_days=365)
    assert result["n_history_windows"].iloc[1] == 1
    assert result["probability"].iloc[1] == 1.0


def test_persistence_baseline_hand_example():
    labeled = _daily_windows([1, 0, 1, 0])
    result = persistence_baseline(labeled, "C+", p_if_positive=0.8, p_if_negative=0.2)
    assert np.isnan(result.iloc[0])
    assert result.iloc[1] == 0.8  # previous (day0) was positive
    assert result.iloc[2] == 0.2  # previous (day1) was negative
    assert result.iloc[3] == 0.8  # previous (day2) was positive


def test_rolling_rate_baseline_matches_climatology_math():
    labeled = _daily_windows([1, 0, 1, 0, 1])
    result = rolling_rate_baseline(labeled, "C+", window_days=3)
    assert np.isnan(result.iloc[0])
    assert result.iloc[1] == 1.0
    assert result.iloc[2] == 0.5
    assert abs(result.iloc[3] - 2 / 3) < 1e-9
    assert abs(result.iloc[4] - 1 / 3) < 1e-9

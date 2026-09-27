"""Cross-model window alignment and lead time (PRD.md FR-0.3, FR-0.6).

Scoreboard models issue forecasts for windows that are not necessarily
identical to swcast's own canonical UTC-midnight-aligned 24h windows
(`labels.make_windows`). Before models can be compared to each other or to
GOES labels, each model's forecast rows must be matched to a canonical
window within a stated tolerance, and unmatched rows must be counted and
reported, not silently dropped (PRD.md FR-0.3 "mark, don't drop" -- applied
here to window matching, not just GOES gaps).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_START_TOLERANCE_HOURS = 3.0
DEFAULT_LENGTH_TOLERANCE_HOURS = 3.0


def add_lead_time(df: pd.DataFrame) -> pd.DataFrame:
    """Add `lead_time_hours` = window_start - issue_time, in hours."""
    df = df.copy()
    df["lead_time_hours"] = (df["window_start"] - df["issue_time"]) / pd.Timedelta(hours=1)
    return df


def bucket_lead_time_days(df: pd.DataFrame) -> pd.DataFrame:
    """Add `lead_time_hours` and `lead_day` (nearest-24h bucket, e.g. NOAA's
    day1/day2/day3 forecasts land at lead_day 1/2/3 respectively, even
    though the actual lead time is rarely exactly 24/48/72h).
    """
    df = add_lead_time(df)
    df["lead_day"] = np.round(df["lead_time_hours"] / 24.0).astype(int)
    return df


def match_canonical_windows(
    df: pd.DataFrame,
    canonical_windows: pd.DataFrame,
    start_tolerance_hours: float = DEFAULT_START_TOLERANCE_HOURS,
    length_tolerance_hours: float = DEFAULT_LENGTH_TOLERANCE_HOURS,
) -> pd.DataFrame:
    """Match each row's own (window_start, window_end) to the nearest
    canonical window (`labels.make_windows` output).

    A row is `matched` if its window_start is within `start_tolerance_hours`
    of some canonical window_start AND its own window length is within
    `length_tolerance_hours` of 24h. Unmatched rows are KEPT with
    `matched=False` and NaT canonical_window_start/end -- callers must count
    and report these, not drop them silently (PRD.md FR-0.3).
    """
    df = df.sort_values("window_start").reset_index(drop=True)
    canon = (
        canonical_windows[["window_start", "window_end"]]
        .sort_values("window_start")
        .rename(columns={"window_start": "canonical_window_start", "window_end": "canonical_window_end"})
    )
    merged = pd.merge_asof(
        df,
        canon,
        left_on="window_start",
        right_on="canonical_window_start",
        tolerance=pd.Timedelta(hours=start_tolerance_hours),
        direction="nearest",
    )
    row_length_hours = (merged["window_end"] - merged["window_start"]) / pd.Timedelta(hours=1)
    merged["matched"] = merged["canonical_window_start"].notna() & (
        (row_length_hours - 24.0).abs() <= length_tolerance_hours
    )
    return merged


def subsample_by_reference_issue_time(
    candidate_df: pd.DataFrame,
    reference_df: pd.DataFrame,
    window_keys: tuple[str, str] = ("canonical_window_start", "canonical_window_end"),
) -> pd.DataFrame:
    """For each (window, class) in `candidate_df`, keep only the row with the
    latest `issue_time` that is <= the matching `reference_df` row's
    `issue_time` for the same window (e.g. NOAA_1 day-1's issue time, so
    ASSA_1's hourly series is subsampled to "the most recent ASSA forecast
    available no later than when NOAA issued its own"). `reference_df` must
    have one issue_time per window (duplicates are collapsed by taking the
    first).

    Windows in `candidate_df` with no candidate row satisfying
    issue_time <= reference_issue_time are dropped from the result -- the
    caller should compare row counts before/after to report how many
    windows were excluded this way (PRD.md FR-0.3).
    """
    keys = list(window_keys)
    ref = (
        reference_df[keys + ["issue_time"]]
        .drop_duplicates(subset=keys)
        .rename(columns={"issue_time": "reference_issue_time"})
    )
    merged = candidate_df.merge(ref, on=keys, how="inner")
    merged = merged[merged["issue_time"] <= merged["reference_issue_time"]]
    if merged.empty:
        return merged.drop(columns=["reference_issue_time"])
    idx = merged.groupby(keys + ["class"])["issue_time"].idxmax()
    return merged.loc[idx].drop(columns=["reference_issue_time"]).reset_index(drop=True)

import pandas as pd

from swcast.align import (
    add_lead_time,
    bucket_lead_time_days,
    match_canonical_windows,
    subsample_by_reference_issue_time,
)


def test_add_lead_time_hand_example():
    df = pd.DataFrame(
        {
            "issue_time": pd.to_datetime(["2026-01-01T00:00:00"]),
            "window_start": pd.to_datetime(["2026-01-02T00:00:00"]),
        }
    )
    result = add_lead_time(df)
    assert result["lead_time_hours"].iloc[0] == 24.0


def test_bucket_lead_time_days_rounds_to_nearest_day():
    df = pd.DataFrame(
        {
            "issue_time": pd.to_datetime(["2026-01-01T00:00:00"] * 3),
            # 24h -> day 1; 47h -> rounds to day 2; 72h -> exactly day 3.
            "window_start": pd.to_datetime(
                ["2026-01-02T00:00:00", "2026-01-02T23:00:00", "2026-01-04T00:00:00"]
            ),
        }
    )
    result = bucket_lead_time_days(df)
    assert list(result["lead_day"]) == [1, 2, 3]


def test_match_canonical_windows_within_tolerance():
    canonical = pd.DataFrame(
        {
            "window_start": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "window_end": pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04"]),
        }
    )
    df = pd.DataFrame(
        {
            "window_start": pd.to_datetime(
                [
                    "2026-01-02T01:00:00",  # 1h off, 24h long -> matched
                    "2026-01-02T05:00:00",  # 5h off (> 3h tolerance) -> unmatched
                    "2026-01-03T00:30:00",  # 0.5h off but only a 6h window -> unmatched (length)
                ]
            ),
            "window_end": pd.to_datetime(
                [
                    "2026-01-03T01:00:00",
                    "2026-01-03T05:00:00",
                    "2026-01-03T06:30:00",
                ]
            ),
        }
    )
    result = match_canonical_windows(df, canonical)
    assert list(result["matched"]) == [True, False, False]
    assert result.loc[0, "canonical_window_start"] == pd.Timestamp("2026-01-02")
    # Unmatched rows are kept, not dropped.
    assert len(result) == 3


def test_subsample_by_reference_issue_time_picks_latest_not_later_than_reference():
    reference = pd.DataFrame(
        {
            "canonical_window_start": pd.to_datetime(["2026-01-03"]),
            "canonical_window_end": pd.to_datetime(["2026-01-04"]),
            "issue_time": pd.to_datetime(["2026-01-02T22:00:00"]),
        }
    )
    candidate = pd.DataFrame(
        {
            "canonical_window_start": pd.to_datetime(["2026-01-03"] * 3),
            "canonical_window_end": pd.to_datetime(["2026-01-04"] * 3),
            "issue_time": pd.to_datetime(
                ["2026-01-02T20:00:00", "2026-01-02T21:00:00", "2026-01-02T23:00:00"]
            ),
            "class": ["M+", "M+", "M+"],
            "probability": [0.1, 0.2, 0.3],
        }
    )
    result = subsample_by_reference_issue_time(candidate, reference)
    assert len(result) == 1
    assert result.iloc[0]["issue_time"] == pd.Timestamp("2026-01-02T21:00:00")
    assert result.iloc[0]["probability"] == 0.2


def test_subsample_by_reference_issue_time_excludes_window_with_no_valid_candidate():
    reference = pd.DataFrame(
        {
            "canonical_window_start": pd.to_datetime(["2026-01-03"]),
            "canonical_window_end": pd.to_datetime(["2026-01-04"]),
            "issue_time": pd.to_datetime(["2026-01-02T22:00:00"]),
        }
    )
    # Only candidate issue_time is AFTER the reference issue_time -> excluded.
    candidate = pd.DataFrame(
        {
            "canonical_window_start": pd.to_datetime(["2026-01-03"]),
            "canonical_window_end": pd.to_datetime(["2026-01-04"]),
            "issue_time": pd.to_datetime(["2026-01-02T23:00:00"]),
            "class": ["M+"],
            "probability": [0.3],
        }
    )
    result = subsample_by_reference_issue_time(candidate, reference)
    assert len(result) == 0

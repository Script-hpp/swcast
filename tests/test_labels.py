import pandas as pd

from swcast.labels import label_windows, make_windows


def test_make_windows_covers_range_without_overlap():
    windows = make_windows("2026-01-01", "2026-01-03")
    assert len(windows) == 2
    assert windows.iloc[0]["window_start"] == pd.Timestamp("2026-01-01")
    assert windows.iloc[0]["window_end"] == pd.Timestamp("2026-01-02")
    assert windows.iloc[1]["window_start"] == pd.Timestamp("2026-01-02")
    assert windows.iloc[1]["window_end"] == pd.Timestamp("2026-01-03")


def test_label_windows_hand_example():
    windows = make_windows("2026-01-01", "2026-01-03")
    flares = pd.DataFrame(
        {
            # day 1: one C-class flare (below M+) -> C+ = 1, M+ = 0
            # day 2: one M-class flare -> C+ = 1, M+ = 1, X = 0
            "peak_time": pd.to_datetime(
                ["2026-01-01T05:00:00", "2026-01-02T12:00:00"]
            ),
            "peak_flux_wm2": [2e-6, 3e-5],
        }
    )
    labeled = label_windows(windows, flares)

    day1, day2 = labeled.iloc[0], labeled.iloc[1]
    assert (day1["C+"], day1["M+"], day1["X"]) == (1, 0, 0)
    assert (day2["C+"], day2["M+"], day2["X"]) == (1, 1, 0)
    assert not labeled["is_gap"].any()


def test_label_windows_no_flares_in_window():
    windows = make_windows("2026-01-01", "2026-01-02")
    flares = pd.DataFrame({"peak_time": pd.to_datetime([]), "peak_flux_wm2": []})
    labeled = label_windows(windows, flares)
    assert (labeled.iloc[0][["C+", "M+", "X"]] == 0).all()


def test_flare_at_window_boundary_assigned_to_start_window():
    # A flare peaking exactly at window_end belongs to the NEXT window (half-open [start, end)).
    windows = make_windows("2026-01-01", "2026-01-03")
    flares = pd.DataFrame(
        {
            "peak_time": pd.to_datetime(["2026-01-02T00:00:00"]),
            "peak_flux_wm2": [2e-6],
        }
    )
    labeled = label_windows(windows, flares)
    assert labeled.iloc[0]["C+"] == 0
    assert labeled.iloc[1]["C+"] == 1


def test_overlapping_flares_in_same_window_do_not_double_count():
    # Two overlapping flares peak in the same window; only one reaches M+.
    # The window should be a single positive M+ label, not two separate
    # events -- there is nothing to deduplicate at the window-label level.
    windows = make_windows("2026-01-01", "2026-01-02")
    flares = pd.DataFrame(
        {
            "peak_time": pd.to_datetime(
                ["2026-01-01T10:00:00", "2026-01-01T10:05:00"]
            ),
            "peak_flux_wm2": [2e-6, 3e-5],
        }
    )
    labeled = label_windows(windows, flares)
    assert (labeled.iloc[0]["C+"], labeled.iloc[0]["M+"], labeled.iloc[0]["X"]) == (
        1,
        1,
        0,
    )

def test_label_windows_with_gaps():
    windows = pd.DataFrame({
        "window_start": pd.to_datetime(["2024-01-01", "2024-01-02"]),
        "window_end": pd.to_datetime(["2024-01-02", "2024-01-03"]),
    })
    flares = pd.DataFrame({"peak_time": pd.to_datetime([]), "peak_flux_wm2": []})
    
    # 2024-01-01 has 144 minutes missing (exactly 10%) -> is_gap = False
    # 2024-01-02 has 150 minutes missing (10.4%) -> is_gap = True
    times = pd.date_range("2024-01-01", "2024-01-03", freq="1min", inclusive="left")
    gaps_series = pd.Series(False, index=times)
    
    # Set 144 minutes on day 1
    gaps_series.loc["2024-01-01 00:00":"2024-01-01 02:23"] = True
    
    # Set 150 minutes on day 2
    gaps_series.loc["2024-01-02 00:00":"2024-01-02 02:29"] = True
    
    labeled = label_windows(windows, flares, gaps=gaps_series, max_gap_fraction=0.1)
    assert list(labeled["is_gap"]) == [False, True]

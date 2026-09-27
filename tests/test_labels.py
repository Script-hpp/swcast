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
            "start_time": pd.to_datetime(
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
    flares = pd.DataFrame({"start_time": pd.to_datetime([]), "peak_flux_wm2": []})
    labeled = label_windows(windows, flares)
    assert (labeled.iloc[0][["C+", "M+", "X"]] == 0).all()


def test_flare_at_window_boundary_assigned_to_start_window():
    # A flare exactly at window_end belongs to the NEXT window (half-open [start, end)).
    windows = make_windows("2026-01-01", "2026-01-03")
    flares = pd.DataFrame(
        {
            "start_time": pd.to_datetime(["2026-01-02T00:00:00"]),
            "peak_flux_wm2": [2e-6],
        }
    )
    labeled = label_windows(windows, flares)
    assert labeled.iloc[0]["C+"] == 0
    assert labeled.iloc[1]["C+"] == 1

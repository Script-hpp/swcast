"""Turn the GOES flare list (fetch/goes.py) into per-window binary labels.

Window-assignment rule (frozen 2026-09-27, still pending copy into
PREREGISTRATION.md before the first real forecast per PRD.md Abschnitt 3):
a window is positive for a class if any flare whose PEAK time
(`peak_time`, fetch/goes.py) falls inside the window reaches that class's
threshold. Peak time was chosen over onset (`start_time`) because the peak
flux -- which determines the class -- is physically tied to the peak, not the
onset; a flare that starts in one window can peak in the next.

Windows are half-open [window_start, window_end): a flare peaking exactly on
a boundary belongs to the window that STARTS at that instant, not the one
ending there (see test_flare_at_window_boundary_assigned_to_start_window).

Overlapping flares: no special handling is needed or done. A window's label
is `any(peak_flux >= threshold for flares peaking in the window)` -- an OR
over all flares in the window, so multiple or overlapping flares (a new
flare starting before a previous one ends) naturally roll into the same
window-level threshold check without double counting or requiring
deduplication.

Data-gap marking (FR-0.3): this flare list has no continuous background/
coverage column, so a genuine "no flare" window cannot yet be distinguished
here from a window with missing GOES telemetry. `is_gap` is a placeholder
(always False) -- this is a KNOWN, DOCUMENTED LIMITATION of the M0 benchmark,
not a resolved design decision. Real gap detection (1-minute XRS irradiance
averages; a rule for which missing/flagged minutes exclude a window) is a
hard gate before PREREGISTRATION.md is frozen and before any M1 live scoring
(PRD.md Abschnitt 10). Once implemented, M0 must be re-run with gap-excluded
windows and a short sensitivity comparison (does the leaderboard ranking
change?) added to the report.
"""

from __future__ import annotations

import pandas as pd

CLASS_THRESHOLDS_WM2 = {
    "C+": 1e-6,
    "M+": 1e-5,
    "X": 1e-4,
}


def make_windows(
    start_date: str, end_date: str, window_hours: int = 24
) -> pd.DataFrame:
    """24h windows [window_start, window_end) covering [start_date, end_date)."""
    starts = pd.date_range(start=start_date, end=end_date, freq=f"{window_hours}h", inclusive="left")
    return pd.DataFrame(
        {
            "window_start": starts,
            "window_end": starts + pd.Timedelta(hours=window_hours),
        }
    )


def label_windows(
    windows: pd.DataFrame,
    flares: pd.DataFrame,
    classes: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Add one 0/1 column per class in `classes` to `windows`, plus `is_gap`.

    `flares` must have `peak_time` and `peak_flux_wm2` columns (see
    fetch/goes.py). `windows` must have `window_start`/`window_end` columns
    (see make_windows). See module docstring for the peak-time assignment
    rule and the boundary/overlap conventions.
    """
    classes = classes or CLASS_THRESHOLDS_WM2
    result = windows.copy()
    peak_times = flares["peak_time"].to_numpy()
    fluxes = flares["peak_flux_wm2"].to_numpy()

    for class_name, threshold in classes.items():
        above = fluxes >= threshold
        labels = []
        for w_start, w_end in zip(result["window_start"], result["window_end"]):
            in_window = (peak_times >= w_start.to_datetime64()) & (peak_times < w_end.to_datetime64())
            labels.append(int(bool((in_window & above).any())))
        result[class_name] = labels

    result["is_gap"] = False  # placeholder -- see module docstring.
    return result

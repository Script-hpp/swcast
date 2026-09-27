"""Turn the GOES flare list (fetch/goes.py) into per-window binary labels.

A flare is assigned to the 24h window that contains its `start_time` (onset),
not its peak or end time. This is a modeling choice, not yet in PREREGISTRATION.md
(PRD.md Abschnitt 3 says definitions must be frozen before the first real
forecast) -- treat it as provisional until frozen.

Class thresholds (PRD.md Abschnitt 3, peak flux in the 1-8 A / 0.1-0.8 nm channel):
  C+ >= 1e-6 W/m^2, M+ >= 1e-5 W/m^2, X (no upper bound) >= 1e-4 W/m^2.

Data-gap marking (FR-0.3): this flare list has no continuous background/coverage
column, so a genuine "no flare" window cannot yet be distinguished here from a
window with missing GOES telemetry. `is_gap` is a placeholder (always False)
until that is resolved (PRD.md Abschnitt 10, offene Frage) -- do not treat it as
a real gap detector.
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

    `flares` must have `start_time` and `peak_flux_wm2` columns (see
    fetch/goes.py). `windows` must have `window_start`/`window_end` columns
    (see make_windows).
    """
    classes = classes or CLASS_THRESHOLDS_WM2
    result = windows.copy()
    starts = flares["start_time"].to_numpy()
    fluxes = flares["peak_flux_wm2"].to_numpy()

    for class_name, threshold in classes.items():
        above = fluxes >= threshold
        labels = []
        for w_start, w_end in zip(result["window_start"], result["window_end"]):
            in_window = (starts >= w_start.to_datetime64()) & (starts < w_end.to_datetime64())
            labels.append(int(bool((in_window & above).any())))
        result[class_name] = labels

    result["is_gap"] = False  # placeholder -- see module docstring.
    return result

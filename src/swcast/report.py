"""M0 benchmark report (PRD.md FR-0.1..FR-0.7).

Fetches GOES-16+ flare labels and CCMC scoreboard forecasts (NOAA_1,
SIDC_v2, ASSA_1) for a benchmark period and scores each model against GOES
labels.

Critical finding from live data (2026-09-27), not assumed by the PRD:
models do NOT share one window definition.
  - NOAA_1: 24h windows, UTC-midnight aligned -- matches swcast's own
    canonical grid (`labels.make_windows`) exactly.
  - SIDC_v2: 24h windows, but phase-shifted to a ~12:30 UTC issuance cycle
    (window_start ~12:30, not 00:00).
  - ASSA_1: 12h windows (e.g. 00:00-12:00), issued hourly on a rolling
    basis -- HALF the length of NOAA/SIDC's "Full Disk 24h" forecasts.
Because of this, SIDC_v2 and ASSA_1 forecasts cannot be matched to swcast's
canonical UTC-midnight 24h windows within any reasonable tolerance -- this
was verified empirically (0/42 and 0/831 rows matched at a 3h/3h
start/length tolerance) before concluding it's a real windowing difference,
not a bug. Each model is therefore scored against GOES labels built on ITS
OWN native window definition (`labels.label_windows` supports arbitrary
window sets, not just 24h UTC-midnight ones). A true same-window, multi-
model FR-0.6 "common windows" comparison is only possible among models
that share NOAA's convention -- currently just NOAA_1 itself (across its
own day-1/day-2/day-3 lead times). This is flagged in PRD.md Abschnitt 10
as a new open question requiring a methodology decision, analogous to the
existing gap-detection hard gate.

GOES data-gap detection is implemented. Windows with >10% missing or bad
telemetry are excluded from scoring. The gap mask intelligently combines 
data from both GOES-18 and GOES-19, meaning a minute is only flagged as a gap 
if BOTH satellites are missing data or are in eclipse.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from swcast.align import bucket_lead_time_days, match_canonical_windows
from swcast.baselines import (
    climatology_baseline,
    persistence_baseline,
    rolling_rate_baseline,
)
from swcast.config import load_config
from swcast.fetch.goes import fetch_goes_1m_gaps, fetch_goes_flares
from swcast.fetch.scoreboard import fetch_scoreboard_model
from swcast.labels import label_windows, make_windows
from swcast.metrics import (
    best_true_skill_statistic,
    block_bootstrap_ci,
    brier_score,
    brier_skill_score,
    reliability_diagram,
    true_skill_statistic,
)

REPORT_START = "2026-03-28"
REPORT_END = "2026-10-01"
CLIMATOLOGY_LOOKBACK_DAYS = 365
ROLLING_RATE_DAYS = 27
BOOTSTRAP_BLOCK_DAYS = 27
BOOTSTRAP_ITERATIONS = 500
CLASSES = ["C+", "M+", "X"]
MODELS = ["NOAA_1", "SIDC_v2", "ASSA_1"]
# NOAA_1 does not forecast full-disk C+ at all (PRD.md Abschnitt 4) -- must
# be treated as "not forecast", not silently scored as an all-zero series.
MODEL_CLASSES = {
    "NOAA_1": ["M+", "X"],
    "SIDC_v2": ["C+", "M+", "X"],
    "ASSA_1": ["C+", "M+", "X"],
}
LOW_POSITIVE_COUNT_WARNING = 10
# Buffer past REPORT_END so flares are available for the tail of the widest
# native window (SIDC/NOAA 24h) even when its window_start == REPORT_END.
FLARE_FETCH_END_BUFFER_DAYS = 2


def build_flares_and_canonical_labels(
    data_dir: Path, history_start: str, flare_fetch_end: str, gaps_series: pd.Series | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (flares, labels_all, report_labels) on swcast's own canonical
    UTC-midnight 24h grid. `labels_all` extends CLIMATOLOGY_LOOKBACK_DAYS
    before REPORT_START so baselines have history at the first report window.
    """
    flares = fetch_goes_flares(data_dir, history_start, flare_fetch_end, min_satellite=16)
    canonical_all = make_windows(history_start, REPORT_END)
    labels_all = label_windows(canonical_all, flares, gaps=gaps_series)
    report_labels = labels_all[
        labels_all["window_start"] >= pd.Timestamp(REPORT_START)
    ].reset_index(drop=True)
    return flares, labels_all, report_labels


def build_baselines(labels_all: pd.DataFrame, report_start: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Per class, on the canonical grid: window_start + climatology/
    persistence/rolling27d probability columns, filtered to the report period.
    """
    result = {}
    for class_name in CLASSES:
        clim = climatology_baseline(labels_all, class_name, CLIMATOLOGY_LOOKBACK_DAYS)
        pers = persistence_baseline(labels_all, class_name)
        roll = rolling_rate_baseline(labels_all, class_name, ROLLING_RATE_DAYS)
        df = pd.DataFrame(
            {
                "window_start": labels_all["window_start"].to_numpy(),
                "climatology": clim["probability"].to_numpy(),
                "climatology_n_history": clim["n_history_windows"].to_numpy(),
                "persistence": pers.to_numpy(),
                "rolling27d": roll.to_numpy(),
            }
        )
        result[class_name] = df[df["window_start"] >= report_start].reset_index(drop=True)
    return result


def native_window_labels(
    scoreboard_df: pd.DataFrame, flares: pd.DataFrame, gaps_series: pd.Series | None = None
) -> pd.DataFrame:
    """Label a model's OWN reported windows (whatever length/phase they are)
    against GOES flares, using the same peak-time rule as the canonical grid
    (labels.label_windows is window-definition-agnostic).
    """
    windows = (
        scoreboard_df[["window_start", "window_end"]]
        .drop_duplicates()
        .sort_values("window_start")
        .reset_index(drop=True)
    )
    return label_windows(windows, flares, gaps=gaps_series)


def prepare_series(
    probability_df: pd.DataFrame,
    class_name: str,
    truth_labels: pd.DataFrame,
    climatology_ref: pd.DataFrame,
) -> pd.DataFrame:
    """`probability_df` must have `window_start` + `probability` (one class,
    one series). `truth_labels` must have `window_start` + `class_name` + `is_gap`.
    `climatology_ref` must have `window_start` + `climatology` (used only as
    the BSS reference; must be on the SAME window grid as `truth_labels`).
    """
    valid_truth = truth_labels[~truth_labels["is_gap"]].copy()
    truth = valid_truth[["window_start", class_name]].rename(columns={class_name: "y_true"})
    merged = probability_df.merge(truth, on="window_start", how="inner")
    merged = merged.merge(
        climatology_ref[["window_start", "climatology"]], on="window_start", how="left"
    )
    return merged.dropna(subset=["probability", "y_true"]).reset_index(drop=True)


def compute_metrics(df: pd.DataFrame) -> dict | None:
    if df.empty:
        return None
    y_true = df["y_true"].to_numpy(dtype=float)
    y_prob = df["probability"].to_numpy(dtype=float)
    y_ref = df["climatology"].to_numpy(dtype=float)
    ref_valid = ~np.isnan(y_ref)

    bss = (
        brier_skill_score(y_true[ref_valid], y_prob[ref_valid], y_ref[ref_valid])
        if ref_valid.any()
        else float("nan")
    )
    tss_opt, thr_opt = best_true_skill_statistic(y_true, y_prob)

    window_start = pd.to_datetime(df["window_start"])
    day_index = (window_start - window_start.min()).dt.days.to_numpy()
    values = np.column_stack([y_true, y_prob])
    _, ci_low, ci_high = block_bootstrap_ci(
        values,
        day_index,
        lambda v: brier_score(v[:, 0], v[:, 1]),
        block_length_days=BOOTSTRAP_BLOCK_DAYS,
        n_iterations=BOOTSTRAP_ITERATIONS,
        seed=0,
    )
    return dict(
        n=len(df),
        n_positive=int(y_true.sum()),
        brier=brier_score(y_true, y_prob),
        brier_ci_low=ci_low,
        brier_ci_high=ci_high,
        bss=bss,
        tss_opt=tss_opt,
        thr_opt=thr_opt,
        tss_50=true_skill_statistic(y_true, y_prob, 0.5),
        reliability=reliability_diagram(y_true, y_prob, n_bins=5),
    )


def _fmt(x: float, digits: int = 3) -> str:
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{digits}f}"


def _metrics_row(name: str, m: dict | None) -> str:
    if m is None:
        return f"| {name} | 0 | - | - | - | - | - |"
    return (
        f"| {name} | {m['n']} | {m['n_positive']} | {_fmt(m['brier'])} "
        f"[{_fmt(m['brier_ci_low'])}, {_fmt(m['brier_ci_high'])}] | {_fmt(m['bss'])} | "
        f"{_fmt(m['tss_opt'])} (@{_fmt(m['thr_opt'], 2)}) | {_fmt(m['tss_50'])} |"
    )


def _reliability_table(name: str, m: dict | None) -> str:
    if m is None or m["reliability"]["count"].size == 0:
        return f"_{name}: no data for a reliability table._\n"
    r = m["reliability"]
    lines = [f"**{name}**", "", "| bin center | mean forecast | observed freq | n |", "| --- | --- | --- | --- |"]
    for bc, mf, of, n in zip(r["bin_center"], r["mean_forecast"], r["observed_frequency"], r["count"]):
        lines.append(f"| {bc:.2f} | {mf:.3f} | {of:.3f} | {int(n)} |")
    return "\n".join(lines) + "\n"


def select_daily_by_reference_issue_time(
    candidate_df: pd.DataFrame, reference_issue_times: pd.Series
) -> pd.DataFrame:
    """For each reference issue_time (one per NOAA_1 day-1 forecast), pick
    the single most recent `candidate_df` issuance at or before it,
    regardless of which window that issuance targets (used for ASSA_1,
    whose 12h windows don't align to NOAA's 24h windows -- see module
    docstring). Returns all class rows for each picked issuance.
    Days with no candidate issuance before the reference are dropped, not
    zero-filled -- report how many separately.
    """
    ref = pd.DataFrame({"reference_issue_time": reference_issue_times.sort_values().to_numpy()})
    candidate_issue_times = candidate_df[["issue_time"]].drop_duplicates().sort_values("issue_time")
    matched = pd.merge_asof(
        ref,
        candidate_issue_times,
        left_on="reference_issue_time",
        right_on="issue_time",
        direction="backward",
    ).dropna(subset=["issue_time"])
    picked_issue_times = matched["issue_time"].drop_duplicates()
    return candidate_df.merge(picked_issue_times, on="issue_time", how="inner")


def main() -> None:
    cfg = load_config()
    data_dir = Path(cfg["data_dir"])

    history_start = (
        pd.Timestamp(REPORT_START) - pd.Timedelta(days=CLIMATOLOGY_LOOKBACK_DAYS)
    ).strftime("%Y-%m-%d")
    flare_fetch_end = (
        pd.Timestamp(REPORT_END) + pd.Timedelta(days=FLARE_FETCH_END_BUFFER_DAYS)
    ).strftime("%Y-%m-%d")

    print("Fetching GOES 1-minute averages to build gap masks...")
    gaps_series = fetch_goes_1m_gaps(data_dir, history_start, flare_fetch_end)

    print("Fetching GOES flares + building canonical labels...")
    flares, labels_all, report_labels = build_flares_and_canonical_labels(
        data_dir, history_start, flare_fetch_end, gaps_series=gaps_series
    )
    
    # Calculate actual data end from coverage
    gaps_valid = gaps_series[~gaps_series]
    gaps_end = (gaps_valid.index.max() + pd.Timedelta(minutes=1)) if len(gaps_valid) else pd.Timestamp(REPORT_END, tz="UTC")
    flares_end = flares.attrs.get("coverage_end")
    if flares_end is None:
        flares_end = pd.Timestamp(REPORT_END, tz="UTC")
    actual_end_naive = min(pd.Timestamp(REPORT_END, tz="UTC"), gaps_end.tz_localize("UTC"), flares_end).tz_localize(None)

    # Filter all canonical labels and windows to actual data end BEFORE leaderboard calculation
    labels_all = labels_all[labels_all["window_end"] <= actual_end_naive]
    report_labels = report_labels[report_labels["window_end"] <= actual_end_naive]
    
    n_gap_canonical = int(report_labels["is_gap"].sum())
    print(f"Gap detection excluded {n_gap_canonical} canonical windows.")

    baselines = build_baselines(labels_all, pd.Timestamp(REPORT_START))
    canonical_report_windows = make_windows(REPORT_START, actual_end_naive.strftime("%Y-%m-%d"))

    print("Fetching scoreboard forecasts (this hits the live CCMC archive)...")
    raw = {model: fetch_scoreboard_model(model, REPORT_START, REPORT_END, data_dir) for model in MODELS}

    # NOAA_1 matches swcast's canonical grid exactly (verified: 24h, UTC
    # midnight aligned) -- keep using canonical matching + lead-time split.
    noaa = bucket_lead_time_days(match_canonical_windows(raw["NOAA_1"], canonical_report_windows))
    noaa_total, noaa_matched_n = len(noaa), int(noaa["matched"].sum())
    noaa_matched = noaa[noaa["matched"]].copy()
    noaa_by_day = {d: noaa_matched[noaa_matched["lead_day"] == d].copy() for d in (1, 2, 3)}
    noaa_lead_hours = {
        d: (noaa_by_day[d]["lead_time_hours"].median() if len(noaa_by_day[d]) else float("nan"))
        for d in (1, 2, 3)
    }

    # SIDC_v2 and ASSA_1 do NOT share NOAA's window convention (see module
    # docstring) -- score each on its own native window grid.
    sidc_native_labels = native_window_labels(raw["SIDC_v2"], flares, gaps_series)
    sidc_lead_hours = (
        (raw["SIDC_v2"]["window_start"] - raw["SIDC_v2"]["issue_time"]).dt.total_seconds().median() / 3600.0
        if len(raw["SIDC_v2"])
        else float("nan")
    )

    assa_native_labels = native_window_labels(raw["ASSA_1"], flares, gaps_series)
    assa_hourly_lead_hours = (
        (raw["ASSA_1"]["window_start"] - raw["ASSA_1"]["issue_time"]).dt.total_seconds().median() / 3600.0
        if len(raw["ASSA_1"])
        else float("nan")
    )

    assa_daily = select_daily_by_reference_issue_time(raw["ASSA_1"], noaa_by_day[1]["issue_time"])
    n_noaa_day1_issuances = noaa_by_day[1]["issue_time"].nunique()
    n_assa_daily_matched = assa_daily["issue_time"].nunique()
    assa_daily_lead_hours = (
        (assa_daily["window_start"] - assa_daily["issue_time"]).dt.total_seconds().median() / 3600.0
        if len(assa_daily)
        else float("nan")
    )

    def canonical_prob_df(matched_df: pd.DataFrame, class_name: str) -> pd.DataFrame:
        sub = matched_df[matched_df["class"] == class_name][["canonical_window_start", "probability"]]
        return sub.rename(columns={"canonical_window_start": "window_start"})

    def native_prob_df(scoreboard_df: pd.DataFrame, class_name: str) -> pd.DataFrame:
        return scoreboard_df[scoreboard_df["class"] == class_name][["window_start", "probability"]]

    def baseline_prob_df(class_name: str, column: str) -> pd.DataFrame:
        base = baselines[class_name][["window_start", column]].rename(columns={column: "probability"})
        return base.dropna(subset=["probability"])

    report_sections: dict[str, dict] = {}

    for class_name in CLASSES:
        canonical_clim = baselines[class_name]
        sidc_clim = climatology_baseline(sidc_native_labels, class_name, CLIMATOLOGY_LOOKBACK_DAYS)
        sidc_clim_ref = pd.DataFrame(
            {"window_start": sidc_native_labels["window_start"], "climatology": sidc_clim["probability"]}
        )
        assa_clim = climatology_baseline(assa_native_labels, class_name, CLIMATOLOGY_LOOKBACK_DAYS)
        assa_clim_ref = pd.DataFrame(
            {"window_start": assa_native_labels["window_start"], "climatology": assa_clim["probability"]}
        )

        n_events_canonical = int(report_labels[class_name].sum())

        prepared: dict[str, pd.DataFrame] = {}
        if class_name in MODEL_CLASSES["NOAA_1"]:
            prepared["NOAA_1 (day-1, canonical grid)"] = prepare_series(
                canonical_prob_df(noaa_by_day[1], class_name), class_name, report_labels, canonical_clim
            )
            prepared["NOAA_1 (day-2, canonical grid)"] = prepare_series(
                canonical_prob_df(noaa_by_day[2], class_name), class_name, report_labels, canonical_clim
            )
            prepared["NOAA_1 (day-3, canonical grid)"] = prepare_series(
                canonical_prob_df(noaa_by_day[3], class_name), class_name, report_labels, canonical_clim
            )
        prepared["SIDC_v2 (own 24h grid, ~12:30 UTC phase)"] = prepare_series(
            native_prob_df(raw["SIDC_v2"], class_name), class_name, sidc_native_labels, sidc_clim_ref
        )
        prepared["ASSA_1 (own 12h grid, full hourly)"] = prepare_series(
            native_prob_df(raw["ASSA_1"], class_name), class_name, assa_native_labels, assa_clim_ref
        )
        prepared["ASSA_1 (own 12h grid, ~1/day near NOAA issue time)"] = prepare_series(
            native_prob_df(assa_daily, class_name), class_name, assa_native_labels, assa_clim_ref
        )
        prepared["Climatology (canonical grid)"] = prepare_series(
            baseline_prob_df(class_name, "climatology"), class_name, report_labels, canonical_clim
        )
        prepared["Persistence (canonical grid)"] = prepare_series(
            baseline_prob_df(class_name, "persistence"), class_name, report_labels, canonical_clim
        )
        prepared["Rolling 27d rate (canonical grid)"] = prepare_series(
            baseline_prob_df(class_name, "rolling27d"), class_name, report_labels, canonical_clim
        )

        own_metrics = {name: compute_metrics(df) for name, df in prepared.items()}

        # FR-0.6 "common windows": only NOAA_1's own lead times share a window
        # grid (its canonical one). day-1/day-2/day-3 use different, mostly
        # non-overlapping issue dates over a fixed period, so day-1's own
        # window set already IS day-1's "common windows" case; report the
        # size for transparency rather than pretending a broader intersection
        # exists (see module docstring on why SIDC/ASSA can't join it).
        common_metrics = {
            "NOAA_1 (day-1, canonical grid)": own_metrics.get("NOAA_1 (day-1, canonical grid)"),
            "Climatology (canonical grid)": own_metrics.get("Climatology (canonical grid)"),
            "Persistence (canonical grid)": own_metrics.get("Persistence (canonical grid)"),
            "Rolling 27d rate (canonical grid)": own_metrics.get("Rolling 27d rate (canonical grid)"),
        }

        report_sections[class_name] = dict(
            n_events_canonical=n_events_canonical,
            own_metrics=own_metrics,
            common_metrics=common_metrics,
        )

    lines: list[str] = []
    lines.append("# swcast M0 Benchmark Report")
    lines.append("")
    lines.append(f"Period: {REPORT_START} to {REPORT_END} (UTC). Generated by `src/swcast/report.py`.")
    lines.append("")
    lines.append("## Critical finding: models do not share a window definition")
    lines.append("")
    lines.append(
        "Verified against live data (2026-09-27): **NOAA_1** issues 24h, UTC-midnight-aligned "
        "forecasts, matching swcast's own canonical grid exactly. **SIDC_v2** also issues 24h "
        "forecasts, but on a ~12:30 UTC issuance cycle -- its windows are offset by roughly half a "
        "day from NOAA's. **ASSA_1** issues 12h windows (e.g. 00:00-12:00), hourly, on a rolling "
        "basis -- HALF the length of a 'Full Disk 24h' forecast. Attempting to match SIDC_v2/ASSA_1 "
        "to the canonical grid at a 3h start / 3h length tolerance matched **0 of 42** and **0 of "
        "831** rows respectively -- this was verified as a real windowing difference, not a bug, "
        "before adapting the methodology below."
    )
    lines.append("")
    lines.append(
        "**Consequence for PRD.md FR-0.6 (common-window comparison):** a true same-window, "
        "multi-model comparison is only possible among models sharing one window convention -- "
        "currently that means NOAA_1 alone (across its own day-1/day-2/day-3 lead times). SIDC_v2 "
        "and ASSA_1 are instead scored against GOES labels built on THEIR OWN native window "
        "definitions (`labels.label_windows` works for any window set, not just 24h UTC-midnight "
        "ones), with their own climatology baseline computed on that same native grid for a fair "
        "BSS reference. This is a new open question for PRD.md Abschnitt 10, not resolved here: "
        "should swcast define 'common windows' more loosely (e.g. same calendar day, ignoring exact "
        "phase), or accept that cross-model comparison is only fair among same-convention models?"
    )
    lines.append("")
    # Dynamically compute gap fractions to justify the threshold
    gap_fractions = []
    for w_start, w_end in zip(canonical_report_windows["window_start"], canonical_report_windows["window_end"]):
        if gaps_series is None:
            gap_fractions.append(0.0)
            continue
        window_gaps = gaps_series.loc[w_start:w_end - pd.Timedelta(minutes=1)]
        expected = int((w_end - w_start).total_seconds() / 60)
        if expected == 0:
            gap_fractions.append(0.0)
            continue
        missing = window_gaps.sum() + expected - len(window_gaps)
        gap_fractions.append(missing / expected)
    
    canonical_report_windows["gap_fraction"] = gap_fractions
    windows_above_5 = canonical_report_windows[(canonical_report_windows["gap_fraction"] > 0.05) & (canonical_report_windows["gap_fraction"] <= 0.10)]
    n_above_5 = len(windows_above_5)
    n_above_10 = (canonical_report_windows["gap_fraction"] > 0.10).sum()
    
    lines.append("## GOES data-gap detection")
    lines.append("")
    lines.append(
        "A 24h window (or 12h for ASSA) is excluded from scoring if more than 10% of its 1-minute "
        "XRS measurements are missing or flagged as bad (`(xrsb_flag & 2) != 0`) across ALL available satellites (G18 and G19 combined). "
        "**Important:** Eclipse (bit 1) IS counted as a gap because the Earth blocks the satellite's view of the sun, "
        "causing flares to be missed. Interpolated data (bit 4) does *not* count as a gap because it represents valid patched data. "
        "A minute is only marked as a gap if BOTH G18 and G19 lack valid observations."
    )
    lines.append("")
    
    n_gap_canonical = int(report_labels["is_gap"].sum())
    
    lines.append(
        f"**Why 10%?** A dynamic analysis of the {len(canonical_report_windows)} canonical windows (up to the data end) shows that "
        f"{n_above_5} windows had between 5% and 10% missing telemetry, and {n_above_10} windows had >10%."
    )
    if n_above_5 > 0:
        lines.append(f" Windows with 5-10% missing: {', '.join(w.strftime('%Y-%m-%d') for w in windows_above_5['window_start'])}.")
    
    lines.append(
        " Short telemetry drops occasionally span 5-9% of a day, which still leaves enough continuous data to catch major flares. "
        "Dropping more than 10% risks missing short-lived events, so the threshold is set at 10% to retain mostly-valid days."
    )
    lines.append("")
    
    lines.append(f"In the current benchmark period, there are **{n_gap_canonical} true telemetry gaps >10%**.")
    lines.append("")

    lines.append("### Sensitivity: With vs. Without Gap Filtering")
    lines.append("")
    if n_gap_canonical == 0 and n_above_5 == 0:
        lines.append("Because there were 0 true telemetry gaps >10% and 0 between 5-10% in this period, the leaderboard ranking is identical to a gap-ignorant run.")
    else:
        lines.append("Comparison of NOAA_1 (day-1) metrics on the canonical grid across different gap thresholds:")
        lines.append("")
        lines.append("| Class | Metric | 10% Filter (Actual) | 5% Filter (Strict) | No Filter (Gap-Ignorant) |")
        lines.append("| --- | --- | --- | --- | --- |")
        
        for class_name in CLASSES:
            if class_name not in MODEL_CLASSES["NOAA_1"]:
                continue
            
            # Filtered (10%)
            filtered_metrics = report_sections[class_name]["common_metrics"]["NOAA_1 (day-1, canonical grid)"]
            
            # Compute unfiltered (gap-ignorant)
            unfiltered_labels = report_labels.copy()
            unfiltered_labels["is_gap"] = False
            unfiltered_df = prepare_series(
                canonical_prob_df(noaa_by_day[1], class_name), class_name, unfiltered_labels, baselines[class_name]
            )
            unfiltered_metrics = compute_metrics(unfiltered_df)
            
            # Compute 5% strict filter
            strict_labels = report_labels.copy()
            strict_labels["is_gap"] = canonical_report_windows["gap_fraction"].values > 0.05
            strict_df = prepare_series(
                canonical_prob_df(noaa_by_day[1], class_name), class_name, strict_labels, baselines[class_name]
            )
            strict_metrics = compute_metrics(strict_df)
            
            if filtered_metrics and unfiltered_metrics and strict_metrics:
                lines.append(f"| {class_name} | n | {filtered_metrics['n']} | {strict_metrics['n']} | {unfiltered_metrics['n']} |")
                lines.append(f"| {class_name} | Brier | {_fmt(filtered_metrics['brier'])} | {_fmt(strict_metrics['brier'])} | {_fmt(unfiltered_metrics['brier'])} |")
                lines.append(f"| {class_name} | BSS | {_fmt(filtered_metrics['bss'])} | {_fmt(strict_metrics['bss'])} | {_fmt(unfiltered_metrics['bss'])} |")
        
    lines.append("")
    lines.append("## Window conventions and lead time")
    lines.append("")
    lines.append("| Model | Window length | Phase | Rows fetched | Own-grid windows used |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append(f"| NOAA_1 | 24h | UTC midnight (canonical) | {noaa_total} | {noaa_matched_n} matched to canonical |")
    lines.append(
        f"| SIDC_v2 | 24h | ~12:30 UTC (own grid) | {len(raw['SIDC_v2'])} | "
        f"{sidc_native_labels.shape[0]} native windows |"
    )
    lines.append(
        f"| ASSA_1 | 12h | hourly rolling (own grid) | {len(raw['ASSA_1'])} | "
        f"{assa_native_labels.shape[0]} native windows |"
    )
    lines.append("")
    lines.append("Lead time (window_start minus issue_time), median where applicable:")
    lines.append("")
    lines.append("| Series | Median lead time (h) | How derived |")
    lines.append("| --- | --- | --- |")
    lines.append(f"| NOAA_1 day-1 | {_fmt(noaa_lead_hours[1], 1)} | lead_time_hours rounded to nearest 24h bucket = 1 |")
    lines.append(f"| NOAA_1 day-2 | {_fmt(noaa_lead_hours[2], 1)} | bucket = 2 |")
    lines.append(f"| NOAA_1 day-3 | {_fmt(noaa_lead_hours[3], 1)} | bucket = 3 |")
    lines.append(f"| SIDC_v2 | {_fmt(sidc_lead_hours, 1)} | median over all rows, own grid |")
    lines.append(f"| ASSA_1 full hourly | {_fmt(assa_hourly_lead_hours, 1)} | median over all rows, own grid |")
    lines.append(
        f"| ASSA_1 ~1/day (near NOAA issue time) | {_fmt(assa_daily_lead_hours, 1)} | one issuance per "
        "NOAA_1 day-1 reference: latest ASSA issue_time <= that reference time (own 12h window truth, "
        "NOT the same target as NOAA's 24h window -- see finding above) |"
    )
    lines.append("")
    lines.append(
        f"ASSA_1 ~daily selection matched {n_assa_daily_matched} of {n_noaa_day1_issuances} NOAA_1 "
        "day-1 issuances (issuances with no ASSA forecast available before the reference time are "
        "excluded, not zero-filled)."
    )
    lines.append("")
    if abs(sidc_lead_hours) < 1.0 and abs(assa_hourly_lead_hours) < 1.0:
        lines.append(
            "**Caveat:** SIDC_v2's and ASSA_1's `issue_time` in this archive equals their own "
            "`window_start` exactly (lead time ~0h), unlike NOAA_1's real ~26h day-ahead lead. In this "
            "archive's metadata they read as near-real-time/nowcast-style updates issued exactly when "
            "their window begins, not day-ahead forecasts -- if true, their Brier scores are not directly "
            "comparable in difficulty to NOAA_1's, since predicting the present is easier than predicting "
            "24h ahead. This should be verified against each model's own documentation before using "
            "these numbers for a headline cross-model ranking; it is reported here rather than assumed away."
        )
        lines.append("")

    metric_header = "| Series | n | n positive | Brier [95% CI] | BSS vs climatology | TSS (optimal thr) | TSS @0.5 |"
    metric_sep = "| --- | --- | --- | --- | --- | --- | --- |"

    for class_name in CLASSES:
        sec = report_sections[class_name]
        lines.append(f"## Class {class_name}")
        lines.append("")
        lines.append(
            f"Events on canonical grid in report period: {sec['n_events_canonical']} of "
            f"{len(report_labels)} windows. (SIDC_v2/ASSA_1 event counts differ -- see their own "
            "rows below, computed on their own native grids.)"
        )
        if sec["n_events_canonical"] < LOW_POSITIVE_COUNT_WARNING:
            lines.append(
                f"**Caveat:** few positive events on the canonical grid ({sec['n_events_canonical']}) "
                "-- TSS and reliability are statistically unstable at this sample size for canonical-grid "
                "series; treat this class's ranking as indicative only."
            )
        lines.append("")
        lines.append(
            f"### {class_name}: NOAA_1 + swcast baselines (canonical grid, PRD.md FR-0.6 'common windows' "
            "-- see finding above on why SIDC_v2/ASSA_1 cannot join this table)"
        )
        lines.append("")
        lines.append(metric_header)
        lines.append(metric_sep)
        for name, m in sec["common_metrics"].items():
            lines.append(_metrics_row(name, m))
        lines.append("")
        lines.append(f"### {class_name}: all series, each on its own full available/native window set")
        lines.append("")
        lines.append(metric_header)
        lines.append(metric_sep)
        for name, m in sec["own_metrics"].items():
            lines.append(_metrics_row(name, m))
        lines.append("")
        lines.append("### Reliability (own/native window set)")
        lines.append("")
        for name, m in sec["own_metrics"].items():
            lines.append(_reliability_table(name, m))
        lines.append("")

    lines.append("## Baseline climatology lookback caveat")
    lines.append("")
    min_history = int(baselines["C+"]["climatology_n_history"].min())
    lines.append(
        f"Canonical-grid climatology uses a {CLIMATOLOGY_LOOKBACK_DAYS}-day trailing lookback. The "
        f"earliest report window had {min_history} prior labeled windows available -- fewer than the "
        "full lookback would give near the very start of the GOES history fetched here; this is "
        "expected and documented, not an error. SIDC_v2/ASSA_1's own native-grid climatology "
        "baselines use the same lookback logic applied to their own window definitions."
    )
    lines.append("")

    out_path = Path("reports/m0_benchmark.md")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

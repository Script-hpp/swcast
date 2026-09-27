"""Tests for swcast.evaluate – all files synthetic under tmp_path, issue_time/
GFZ/SWPC mocked or hand-built. No network access."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from swcast.evaluate import (
    build_evaluation_rows,
    build_run_day_universe,
    climatology_rate,
    compute_input_drift,
    compute_k_stats,
    maybe_write_start_md,
    rows_since_start,
    select_swcast_forecasts,
    write_live_evaluation_csv,
    write_live_status_md,
)

MODEL_NAME = "swcast-kp-baseline-v0"


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_forecast(dir_path: Path, run_start: datetime, model_variant="main", features=None) -> Path:
    d = run_start.date()
    targets = [
        {"date": (d + timedelta(days=k)).isoformat(), "kp_max": 3.0 + k, "p_storm": 0.1 * k}
        for k in (1, 2, 3)
    ]
    payload = {
        "model": MODEL_NAME,
        "model_variant": model_variant,
        "run_start": _iso_z(run_start),
        "inputs_last_data_time": _iso_z(run_start),
        "l1_valid": model_variant == "main",
        "l1_fallback_reason": None,
        "l1_source": "SOLAR1" if model_variant == "main" else None,
        "l1_density_2h_mean": 4.0 if model_variant == "main" else None,
        "l1_speed_2h_mean": 400.0 if model_variant == "main" else None,
        "artifacts_sha256": "deadbeef",
        "issue_time": "note",
        "targets": targets,
    }
    if features is not None:
        payload["features"] = features
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{MODEL_NAME}.{run_start.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload))
    return path


def _write_missed(dir_path: Path, run_start: datetime, error_type="ConnectionError") -> Path:
    payload = {
        "model": MODEL_NAME,
        "run_start": _iso_z(run_start),
        "error_type": error_type,
        "reason": "down",
    }
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"MISSED.{run_start.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload))
    return path


def _daypre_text(run_day: date, minor=(5, 10, 1), major=(2, 1, 0)) -> str:
    issued = run_day.strftime("%Y %b %d") + " 2200 UTC"
    d1, d2, d3 = (run_day + timedelta(days=i) for i in (1, 2, 3))
    dates_line = " ".join(d.strftime("%Y %b %d") for d in (d1, d2, d3))
    return f"""
:Product: 3-day Space Weather Predictions daypre.txt
:Issued: {issued}

:Prediction_dates:   {dates_line}

:Prob_Mid:
Mid/Active               10             5            10
Mid/Minor_Storm           {minor[0]}            {minor[1]}            {minor[2]}
Mid/Major-Severe_Storm    {major[0]}             {major[1]}            {major[2]}
"""


def _artifacts(use_calib=False) -> dict:
    return {
        "swpc_recalibration": {
            str(k): {"use_calib": use_calib, "coef": 1.0, "intercept": 0.0, "bss_raw": 0.1, "bss_calib": 0.1}
            for k in (1, 2, 3)
        }
    }


DRIFT_FEATURE_NAMES = [
    "persistence", "recurrence", "climatology",
    "l1_bz_gsm", "l1_by_gsm", "l1_speed", "l1_dyn_pressure", "l1_newell",
]


def _artifacts_with_models() -> dict:
    art = _artifacts()
    art["models"] = {
        str(k): {"p_storm_main": {
            "features": DRIFT_FEATURE_NAMES,
            "scaler_mean": [4.0, 3.0, 0.1, -5.0, 1.0, 400.0, 2.0, 3000.0],
            "scaler_scale": [2.0, 2.0, 0.05, 5.0, 2.0, 100.0, 1.0, 1000.0],
        }}
        for k in (1, 2, 3)
    }
    return art


# ---------------------------------------------------------------------------
# Selection rule (PREREGISTRATION §6): earliest attempt wins, later reruns
# of the same day are ignored outright, sub-22:00 UTC attempts don't count.
# ---------------------------------------------------------------------------

def test_select_picks_earliest_attempt_and_ignores_later_rerun_same_day(tmp_path):
    d = date(2026, 3, 1)
    early = _write_forecast(tmp_path / str(d + timedelta(days=1)), datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc))
    later = _write_forecast(tmp_path / str(d + timedelta(days=1)), datetime(2026, 3, 1, 23, 30, tzinfo=timezone.utc))

    def fake_issue_time(path):
        # both "would" be valid TSA-wise, to prove the LATER one is ignored
        # purely because it's a rerun, not because it fails verification.
        return datetime(2026, 3, 1, 23, 0, tzinfo=timezone.utc) if path == early else datetime(2026, 3, 1, 23, 59, tzinfo=timezone.utc)

    selected = select_swcast_forecasts([early, later], issue_time_fn=fake_issue_time)

    assert selected[d]["path"] == early
    assert selected[d]["run_start"] == datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc)


def test_select_ignores_attempts_before_22_utc(tmp_path):
    d = date(2026, 3, 1)
    stray = _write_forecast(tmp_path / "x", datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc))

    selected = select_swcast_forecasts([stray], issue_time_fn=lambda p: datetime(2026, 3, 1, 11, 0, tzinfo=timezone.utc))

    assert d not in selected


def test_select_excludes_days_with_only_a_missed_file(tmp_path):
    """A MISSED file is not a candidate at all — it must not appear in `selected`."""
    d = date(2026, 3, 1)
    missed = _write_missed(tmp_path / "x", datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc))

    def must_not_be_called(path):
        raise AssertionError("issue_time must not be checked for a MISSED file")

    selected = select_swcast_forecasts([missed], issue_time_fn=must_not_be_called)

    assert d not in selected


def test_select_a_missed_attempt_does_not_block_a_later_successful_rerun_same_day(tmp_path):
    """
    PREREGISTRATION §6: a failed first attempt (MISSED) does not consume the
    day. If a retry the same day succeeds, that successful forecast counts —
    there's no forecast after a failure to have "chosen" between.
    """
    d = date(2026, 3, 1)
    missed = _write_missed(tmp_path / "a", datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc))
    success = _write_forecast(tmp_path / "b", datetime(2026, 3, 1, 23, 15, tzinfo=timezone.utc))

    selected = select_swcast_forecasts(
        [missed, success], issue_time_fn=lambda p: datetime(2026, 3, 1, 23, 20, tzinfo=timezone.utc)
    )

    assert selected[d]["path"] == success
    assert selected[d]["run_start"] == datetime(2026, 3, 1, 23, 15, tzinfo=timezone.utc)


def test_select_ignores_second_success_after_first_success_even_with_earlier_missed(tmp_path):
    """
    Failure order: MISSED (22:00), success #1 (22:30), success #2 (23:15).
    Success #1 must win — no cherry-picking a later, possibly "better" rerun
    once there IS a successful attempt.
    """
    d = date(2026, 3, 1)
    missed = _write_missed(tmp_path / "a", datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc))
    success1 = _write_forecast(tmp_path / "b", datetime(2026, 3, 1, 22, 30, tzinfo=timezone.utc))
    success2 = _write_forecast(tmp_path / "c", datetime(2026, 3, 1, 23, 15, tzinfo=timezone.utc))

    selected = select_swcast_forecasts(
        [missed, success1, success2], issue_time_fn=lambda p: datetime(2026, 3, 1, 23, 59, tzinfo=timezone.utc)
    )

    assert selected[d]["path"] == success1


# ---------------------------------------------------------------------------
# build_evaluation_rows: deadline check per k, SWPC missing, label gap,
# climatology substitution on miss.
# ---------------------------------------------------------------------------

def test_row_too_late_for_k1_but_ok_for_k2_k3(tmp_path):
    run_day = date(2026, 3, 1)
    path = _write_forecast(tmp_path, datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc))
    payload = json.loads(path.read_text())

    # issue_time after 00:00 UTC of D+1 (too late for k=1) but before 00:00 of D+2/D+3
    entry = {
        "path": path,
        "run_start": datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc),
        "payload": payload,
        "issue_time": datetime(2026, 3, 2, 1, 0, tzinfo=timezone.utc),
    }
    selected = {run_day: entry}
    daily_dict = {run_day + timedelta(days=k): {"storm_label": False} for k in (1, 2, 3)}
    for i in range(1, 366):
        daily_dict.setdefault(run_day - timedelta(days=i), {"storm_label": False})

    rows = build_evaluation_rows(selected, {run_day}, [], daily_dict, _artifacts())
    by_k = {r["k"]: r for r in rows}

    assert by_k[1]["verpasst"] is True
    assert by_k[1]["model_variant"] is None
    assert by_k[1]["p_swcast"] == pytest.approx(by_k[1]["Klimatologie"])  # substituted

    assert by_k[2]["verpasst"] is False
    assert by_k[2]["model_variant"] == "main"
    assert by_k[2]["p_swcast"] == pytest.approx(0.2)  # payload targets[1]["p_storm"]

    assert by_k[3]["verpasst"] is False
    assert by_k[3]["p_swcast"] == pytest.approx(0.3)


def test_swpc_missing_sets_nan_and_exclusion_reason(tmp_path):
    run_day = date(2026, 3, 1)
    daily_dict = {run_day + timedelta(days=k): {"storm_label": False} for k in (1, 2, 3)}
    for i in range(1, 366):
        daily_dict.setdefault(run_day - timedelta(days=i), {"storm_label": False})

    rows = build_evaluation_rows({}, {run_day}, [], daily_dict, _artifacts())

    for r in rows:
        assert math.isnan(r["p_swpc"])
        assert "swpc_fehlt" in r["Ausschlussgrund"]
        assert r["verpasst"] is True  # no forecast attempt at all


def test_swpc_present_sets_p_swpc_and_no_exclusion(tmp_path):
    run_day = date(2026, 3, 1)
    daypre_path = tmp_path / f"20260301T220000Z_3-day-solar-geomag-predictions.txt"
    daypre_path.write_text(_daypre_text(run_day, minor=(5, 10, 1), major=(2, 1, 0)))

    daily_dict = {run_day + timedelta(days=k): {"storm_label": False} for k in (1, 2, 3)}
    for i in range(1, 366):
        daily_dict.setdefault(run_day - timedelta(days=i), {"storm_label": False})

    rows = build_evaluation_rows({}, {run_day}, [daypre_path], daily_dict, _artifacts(use_calib=False))
    by_k = {r["k"]: r for r in rows}

    assert by_k[1]["p_swpc"] == pytest.approx(0.07)  # 5% + 2%
    assert "swpc_fehlt" not in by_k[1]["Ausschlussgrund"]


def test_label_gap_sets_nan_and_exclusion_reason(tmp_path):
    run_day = date(2026, 3, 1)
    daily_dict = {run_day + timedelta(days=k): {"storm_label": False} for k in (2, 3)}
    daily_dict[run_day + timedelta(days=1)] = {"storm_label": float("nan")}  # gap
    for i in range(1, 366):
        daily_dict.setdefault(run_day - timedelta(days=i), {"storm_label": False})

    rows = build_evaluation_rows({}, {run_day}, [], daily_dict, _artifacts())
    by_k = {r["k"]: r for r in rows}

    assert math.isnan(by_k[1]["Label"])
    assert "gfz_luecke" in by_k[1]["Ausschlussgrund"]
    assert by_k[2]["Ausschlussgrund"].count("gfz_luecke") == 0


def test_climatology_rate_matches_manual_fraction():
    run_day = date(2026, 3, 1)
    daily_dict = {}
    for i in range(1, 366):
        d = run_day - timedelta(days=i)
        daily_dict[d] = {"storm_label": (i % 10 == 0)}  # 36 storm days / 365
    rate = climatology_rate(daily_dict, run_day)
    assert rate == pytest.approx(36 / 365)


def test_climatology_rate_nan_with_no_data():
    assert math.isnan(climatology_rate({}, date(2026, 3, 1)))


# ---------------------------------------------------------------------------
# Stats + reports
# ---------------------------------------------------------------------------

def test_compute_k_stats_excludes_non_paired_rows_from_n():
    rows = [
        {"Datum": "2026-03-02", "k": 1, "p_swcast": 0.1, "verpasst": False, "model_variant": "main",
         "p_swpc": 0.2, "Label": 0.0, "Klimatologie": 0.15, "Ausschlussgrund": ""},
        {"Datum": "2026-03-03", "k": 1, "p_swcast": 0.9, "verpasst": False, "model_variant": "main",
         "p_swpc": float("nan"), "Label": 1.0, "Klimatologie": 0.15, "Ausschlussgrund": "swpc_fehlt"},
        {"Datum": "2026-03-04", "k": 1, "p_swcast": 0.15, "verpasst": True, "model_variant": None,
         "p_swpc": 0.1, "Label": float("nan"), "Klimatologie": 0.15, "Ausschlussgrund": "gfz_luecke"},
    ]
    stats = compute_k_stats(rows)
    assert stats["n"] == 1
    assert stats["n_swpc_missing"] == 1
    assert stats["n_label_gap"] == 1
    assert not math.isnan(stats["bss_swcast"])


def test_compute_k_stats_empty_paired_set_returns_nan_without_crashing():
    rows = [
        {"Datum": "2026-03-02", "k": 1, "p_swcast": 0.1, "verpasst": False, "model_variant": "main",
         "p_swpc": float("nan"), "Label": 0.0, "Klimatologie": 0.15, "Ausschlussgrund": "swpc_fehlt"},
    ]
    stats = compute_k_stats(rows)
    assert stats["n"] == 0
    assert math.isnan(stats["bss_swcast"])
    assert stats["classification"] == "zu wenig Daten"


def test_write_live_evaluation_csv_has_expected_columns(tmp_path):
    rows = [{
        "Datum": "2026-03-02", "k": 1, "p_swcast": 0.1, "verpasst": False, "model_variant": "main",
        "p_swpc": 0.2, "Label": 0.0, "Klimatologie": 0.15, "Ausschlussgrund": "",
    }]
    path = write_live_evaluation_csv(rows, tmp_path / "reports" / "live_evaluation.csv")
    df = pd.read_csv(path)
    assert list(df.columns) == [
        "Datum", "k", "p_swcast", "verpasst", "model_variant", "p_swpc",
        "Label", "Klimatologie", "Ausschlussgrund",
    ]
    assert len(df) == 1


def test_maybe_write_start_md_uses_earliest_valid_k1_target_date(tmp_path):
    rows = [
        {"Datum": "2026-03-05", "k": 1, "verpasst": False},
        {"Datum": "2026-03-03", "k": 1, "verpasst": False},
        {"Datum": "2026-03-01", "k": 1, "verpasst": True},  # missed -> not eligible
        {"Datum": "2026-03-04", "k": 2, "verpasst": False},  # wrong k -> ignored
    ]
    path = maybe_write_start_md(rows, tmp_path)
    assert path is not None
    assert path.read_text().splitlines()[0] == "2026-03-03"


def test_maybe_write_start_md_does_not_overwrite_existing(tmp_path):
    start_path = tmp_path / "START.md"
    start_path.write_text("2020-01-01\n")
    rows = [{"Datum": "2026-03-03", "k": 1, "verpasst": False}]

    result = maybe_write_start_md(rows, tmp_path)

    assert result == start_path
    assert start_path.read_text() == "2020-01-01\n"


def test_maybe_write_start_md_returns_none_without_any_valid_k1_row(tmp_path):
    rows = [{"Datum": "2026-03-01", "k": 1, "verpasst": True}]
    assert maybe_write_start_md(rows, tmp_path) is None
    assert not (tmp_path / "START.md").exists()


# ---------------------------------------------------------------------------
# A completely silent run-day (no forecast, no MISSED file at all — e.g. the
# cron didn't run) must still show up as missed with climatology, not vanish.
# ---------------------------------------------------------------------------

def test_no_attempt_at_all_gets_kein_lauf_reason_but_stays_paired():
    run_day = date(2026, 3, 1)
    daily_dict = {run_day + timedelta(days=k): {"storm_label": False} for k in (1, 2, 3)}
    for i in range(1, 366):
        daily_dict.setdefault(run_day - timedelta(days=i), {"storm_label": False})

    rows = build_evaluation_rows({}, {run_day}, [], daily_dict, _artifacts())
    row = rows[0]

    assert row["verpasst"] is True
    assert "kein_lauf" in row["Ausschlussgrund"].split(",")
    # kein_lauf alone (SWPC missing here too in this fixture, since no daypre
    # was provided) — check the reason-tagging logic in isolation instead:
    # a kein_lauf-only row (SWPC present, label present) must NOT be treated
    # as excluded by compute_k_stats.
    stats = compute_k_stats([{**row, "Ausschlussgrund": "kein_lauf", "p_swpc": 0.1}])
    assert stats["n"] == 1


def test_build_run_day_universe_fills_gap_between_run_days_after_start(tmp_path):
    forecasts_dir = tmp_path / "forecasts"
    forecasts_dir.mkdir()
    # Start = target_date 2026-03-02 -> run_day_start = 2026-03-01
    (forecasts_dir / "START.md").write_text("2026-03-02\n\nnote\n")

    file_run_days = {date(2026, 3, 1), date(2026, 3, 3)}  # 2026-03-02 is silently missing
    universe = build_run_day_universe(forecasts_dir, file_run_days, today=date(2026, 3, 5))

    assert date(2026, 3, 2) in universe
    assert universe == {date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)}


def test_build_run_day_universe_without_start_md_uses_only_file_days(tmp_path):
    file_run_days = {date(2026, 3, 1), date(2026, 3, 5)}
    universe = build_run_day_universe(tmp_path, file_run_days, today=date(2026, 3, 10))
    assert universe == file_run_days


def test_compute_k_stats_kein_lauf_alone_does_not_exclude_from_paired_set():
    rows = [
        {"Datum": "2026-03-02", "k": 1, "p_swcast": 0.15, "verpasst": True, "model_variant": None,
         "p_swpc": 0.2, "Label": 0.0, "Klimatologie": 0.15, "Ausschlussgrund": "kein_lauf"},
    ]
    stats = compute_k_stats(rows)
    assert stats["n"] == 1


def test_end_to_end_gap_day_between_two_run_days_shows_up_as_missed(tmp_path):
    """
    forecasts/START.md says the run started on run-day 2026-03-01. Runs
    exist (files on disk) for 2026-03-01 and 2026-03-03, but 2026-03-02 has
    NO file at all (the cron silently didn't run). It must still appear in
    the evaluation as a missed day with climatology substituted, not vanish.
    """
    forecasts_dir = tmp_path / "forecasts"
    forecasts_dir.mkdir()
    (forecasts_dir / "START.md").write_text("2026-03-02\n")  # target_date +1 of 2026-03-01's run

    day1 = date(2026, 3, 1)
    day3 = date(2026, 3, 3)
    path1 = _write_forecast(forecasts_dir / "2026-03-02", datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc))
    path3 = _write_forecast(forecasts_dir / "2026-03-04", datetime(2026, 3, 3, 22, 0, tzinfo=timezone.utc))

    def fake_issue_time(path):
        return datetime.fromisoformat(json.loads(path.read_text())["run_start"].replace("Z", "+00:00")) + timedelta(minutes=5)

    forecast_paths = [path1, path3]
    selected = select_swcast_forecasts(forecast_paths, issue_time_fn=fake_issue_time)
    file_run_days = {day1, day3}
    run_days = build_run_day_universe(forecasts_dir, file_run_days, today=date(2026, 3, 5))

    assert date(2026, 3, 2) in run_days  # the gap day is in the universe

    daily_dict = {}
    for d in (day1, day3, date(2026, 3, 2)):
        for k in (1, 2, 3):
            daily_dict[d + timedelta(days=k)] = {"storm_label": False}
    for i in range(1, 366):
        daily_dict.setdefault(day1 - timedelta(days=i), {"storm_label": False})

    rows = build_evaluation_rows(selected, run_days, [], daily_dict, _artifacts())
    gap_rows = [r for r in rows if r["Datum"] == (date(2026, 3, 2) + timedelta(days=1)).isoformat() and r["k"] == 1]

    assert len(gap_rows) == 1
    assert gap_rows[0]["verpasst"] is True
    assert "kein_lauf" in gap_rows[0]["Ausschlussgrund"].split(",")
    assert gap_rows[0]["p_swcast"] == pytest.approx(gap_rows[0]["Klimatologie"])


# ---------------------------------------------------------------------------
# compute_input_drift: descriptive z-score of live feature means vs. the
# frozen training scaler; never touches v0 itself.
# ---------------------------------------------------------------------------

def test_compute_input_drift_computes_z_score_from_live_runs(tmp_path):
    artifacts = _artifacts_with_models()
    run_start = datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc)
    features_by_k = {
        str(k): {
            "persistence": 6.0, "recurrence": 3.0, "climatology": 0.1,
            "l1_bz_gsm": -5.0, "l1_by_gsm": 1.0, "l1_speed": 400.0,
            "l1_dyn_pressure": 2.0, "l1_newell": 3000.0,
        }
        for k in (1, 2, 3)
    }
    path = _write_forecast(tmp_path, run_start, model_variant="main", features=features_by_k)

    drift = compute_input_drift([path], artifacts, k=1)

    # persistence: mean_live=6.0, scaler_mean=4.0, scaler_scale=2.0 -> z=+1.0
    assert drift["persistence"]["n"] == 1
    assert drift["persistence"]["mean_live"] == pytest.approx(6.0)
    assert drift["persistence"]["z"] == pytest.approx(1.0)
    # l1_bz_gsm: live == scaler_mean -> z=0
    assert drift["l1_bz_gsm"]["z"] == pytest.approx(0.0)


def test_compute_input_drift_ignores_fallback_runs(tmp_path):
    artifacts = _artifacts_with_models()
    run_start = datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc)
    path = _write_forecast(tmp_path, run_start, model_variant="fallback")  # l1_valid False, no features

    drift = compute_input_drift([path], artifacts, k=1)

    assert drift["persistence"]["n"] == 0
    assert math.isnan(drift["persistence"]["z"])


def _dummy_row(k: int) -> dict:
    return {
        "Datum": "2026-03-02", "k": k, "p_swcast": 0.1, "verpasst": False, "model_variant": "main",
        "p_swpc": 0.2, "Label": 0.0, "Klimatologie": 0.15, "Ausschlussgrund": "",
    }


def test_write_live_status_md_includes_drift_section_when_given(tmp_path):
    stats_by_k = {k: compute_k_stats([_dummy_row(k)]) for k in (1, 2, 3)}
    drift = {
        "persistence": {"n": 3, "mean_live": 6.0, "scaler_mean": 4.0, "scaler_scale": 2.0, "z": 1.0},
    }
    path = write_live_status_md(stats_by_k, tmp_path, tmp_path / "reports" / "live_status.md", drift=drift)
    text = path.read_text()
    assert "Eingangsdrift" in text
    assert "persistence" in text


def test_write_live_status_md_omits_drift_section_when_empty(tmp_path):
    stats_by_k = {k: compute_k_stats([_dummy_row(k)]) for k in (1, 2, 3)}
    path = write_live_status_md(stats_by_k, tmp_path, tmp_path / "reports" / "live_status.md", drift={})
    assert "Eingangsdrift" not in path.read_text()


# ---------------------------------------------------------------------------
# compute_k_stats: an empty rows list (e.g. before the run has ever started)
# must not crash and must report "zu wenig Daten", not "nicht erreicht".
# ---------------------------------------------------------------------------

def test_compute_k_stats_empty_list_does_not_crash():
    stats = compute_k_stats([])
    assert stats["n"] == 0
    assert math.isnan(stats["bss_swcast"])
    assert stats["classification"] == "zu wenig Daten"


# ---------------------------------------------------------------------------
# rows_since_start: pre-start rows (before forecasts/START.md's date, or
# when START.md doesn't exist yet at all) must not enter the stats table.
# ---------------------------------------------------------------------------

def test_rows_since_start_returns_empty_without_start_md(tmp_path):
    rows = [{"Datum": "2026-03-01", "k": 1}]
    assert rows_since_start(rows, tmp_path) == []


def test_rows_since_start_filters_out_rows_before_start_date(tmp_path):
    (tmp_path / "START.md").write_text("2026-03-03\n")
    rows = [
        {"Datum": "2026-03-01", "k": 1},  # before start -> excluded
        {"Datum": "2026-03-03", "k": 1},  # exactly start -> included
        {"Datum": "2026-03-05", "k": 1},  # after start -> included
    ]
    result = rows_since_start(rows, tmp_path)
    assert {r["Datum"] for r in result} == {"2026-03-03", "2026-03-05"}


def test_end_to_end_pre_start_test_run_excluded_from_status_table(tmp_path):
    """
    A manual workflow_dispatch test run before 22:00 UTC (so it doesn't even
    get selected) and before any START.md exists must not show up as
    "SWPC fehlt"/"GFZ-Lücke" counts in the aggregated stats.
    """
    run_day = date(2026, 3, 1)
    daily_dict = {run_day + timedelta(days=k): {"storm_label": False} for k in (1, 2, 3)}
    for i in range(1, 366):
        daily_dict.setdefault(run_day - timedelta(days=i), {"storm_label": False})

    # No forecast attempt at all that day, no SWPC archived -> both excluded
    rows = build_evaluation_rows({}, {run_day}, [], daily_dict, _artifacts())

    forecasts_dir = tmp_path  # no START.md written
    stats_rows = rows_since_start(rows, forecasts_dir)
    stats = compute_k_stats([r for r in stats_rows if r["k"] == 1])

    assert stats["n"] == 0
    assert stats["n_swpc_missing"] == 0  # not tallied — pre-start, not counted at all
    assert stats["n_label_gap"] == 0
    assert stats["classification"] == "zu wenig Daten"

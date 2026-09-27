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
    climatology_rate,
    compute_k_stats,
    maybe_write_start_md,
    select_swcast_forecasts,
    write_live_evaluation_csv,
)

MODEL_NAME = "swcast-kp-baseline-v0"


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_forecast(dir_path: Path, run_start: datetime, model_variant="main") -> Path:
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
        "artifacts_sha256": "deadbeef",
        "issue_time": "note",
        "targets": targets,
    }
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


def test_select_includes_missed_files_with_no_issue_time(tmp_path):
    d = date(2026, 3, 1)
    missed = _write_missed(tmp_path / "x", datetime(2026, 3, 1, 22, 0, tzinfo=timezone.utc))

    def must_not_be_called(path):
        raise AssertionError("issue_time must not be checked for a MISSED file")

    selected = select_swcast_forecasts([missed], issue_time_fn=must_not_be_called)

    assert selected[d]["issue_time"] is None
    assert "targets" not in selected[d]["payload"]


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
    assert stats["classification"] == "nicht erreicht"


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

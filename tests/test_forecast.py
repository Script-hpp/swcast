"""Tests for swcast.forecast – all network/freeze functions mocked, no filesystem
side effects outside tmp_path, nothing written to the real forecasts/ dir."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from swcast.fetch.swpc import LIVE_PRODUCTS
from swcast.forecast import ForecastRunError, _cli, dry_run, freeze_models, main
from swcast.live_features import MissingFeatureError

MODEL_NAME = "swcast-kp-baseline-v0"


def _all_products_archived(archive_root: Path) -> dict[str, Path]:
    """A full, successful archive_live_products() result (all 4 products)."""
    return {name: archive_root / name for name in LIVE_PRODUCTS}


def _cfg(forecasts_dir: Path) -> dict:
    return {
        "kp_baseline": {"model_name": MODEL_NAME},
        "paths": {"forecasts_dir": str(forecasts_dir)},
    }


def _write_artifacts(path: Path, content: bytes = b'{"models": {}}') -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _fake_live_features(run_start, l1_valid=True, last_data_time=None):
    from datetime import timedelta

    days = {
        i: {
            "target_date": run_start.date() + timedelta(days=i),
            "persistence": 4.0, "recurrence": 3.0, "climatology": 0.1,
            "l1_bz_gsm": -5.0, "l1_by_gsm": 1.0, "l1_speed": 400.0,
            "l1_dyn_pressure": 2.0, "l1_newell": 3000.0,
        }
        for i in (1, 2, 3)
    }
    return {
        "run_start": run_start,
        "inputs_last_data_time": last_data_time or run_start,
        "l1_valid": l1_valid,
        "l1_fallback_reason": None,
        "l1_source": "SOLAR1" if l1_valid else None,
        "l1_density_2h_mean": 4.2 if l1_valid else None,
        "l1_speed_2h_mean": 400.0 if l1_valid else None,
        "days": days,
    }


# ---------------------------------------------------------------------------
# freeze_models
# ---------------------------------------------------------------------------

@patch("swcast.forecast.freeze_file")
@patch("swcast.forecast._artifacts_path")
def test_freeze_models_freezes_artifacts_file(mock_path, mock_freeze, tmp_path):
    artifacts_path = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    _write_artifacts(artifacts_path)
    mock_path.return_value = artifacts_path

    result = freeze_models()

    mock_freeze.assert_called_once_with(artifacts_path)
    assert result == artifacts_path


@patch("swcast.forecast._artifacts_path")
def test_freeze_models_missing_file_raises(mock_path, tmp_path):
    mock_path.return_value = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    with pytest.raises(FileNotFoundError):
        freeze_models()


# ---------------------------------------------------------------------------
# main(): artifact-freeze gate
# ---------------------------------------------------------------------------

@patch("swcast.forecast._artifacts_path")
@patch("swcast.forecast.load_config")
def test_main_aborts_when_sha256_missing(mock_cfg, mock_path, tmp_path):
    artifacts_path = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    _write_artifacts(artifacts_path)
    mock_path.return_value = artifacts_path
    mock_cfg.return_value = _cfg(tmp_path / "forecasts")

    with pytest.raises(RuntimeError, match="not frozen"):
        main(run_start=datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc))


@patch("swcast.forecast._artifacts_path")
@patch("swcast.forecast.load_config")
def test_main_aborts_when_sha256_mismatched(mock_cfg, mock_path, tmp_path):
    artifacts_path = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    _write_artifacts(artifacts_path)
    (Path(f"{artifacts_path}.sha256")).write_text("deadbeef  model_artifacts.json\n")
    mock_path.return_value = artifacts_path
    mock_cfg.return_value = _cfg(tmp_path / "forecasts")

    with pytest.raises(RuntimeError, match="changed since freezing"):
        main(run_start=datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc))


@patch("swcast.forecast._artifacts_path")
@patch("swcast.forecast.load_config")
def test_main_aborts_when_artifacts_file_missing(mock_cfg, mock_path, tmp_path):
    mock_path.return_value = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    mock_cfg.return_value = _cfg(tmp_path / "forecasts")

    with pytest.raises(RuntimeError, match="not found"):
        main(run_start=datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# main(): happy path
# ---------------------------------------------------------------------------

@patch("swcast.forecast.freeze_file")
@patch("swcast.forecast.archive_live_products")
@patch("swcast.forecast.predict")
@patch("swcast.forecast.build_live_features")
@patch("swcast.forecast._artifacts_path")
@patch("swcast.forecast.load_config")
def test_main_writes_forecast_json_and_freezes_everything(
    mock_cfg, mock_path, mock_build_features, mock_predict, mock_archive, mock_freeze, tmp_path,
):
    artifacts_path = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    digest = _write_artifacts(artifacts_path)
    Path(f"{artifacts_path}.sha256").write_text(f"{digest}  model_artifacts.json\n")
    mock_path.return_value = artifacts_path

    forecasts_dir = tmp_path / "forecasts"
    mock_cfg.return_value = _cfg(forecasts_dir)

    run_start = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    mock_build_features.return_value = _fake_live_features(run_start)
    mock_predict.return_value = {
        1: {"p_storm": 0.1, "kp_max": 3.0},
        2: {"p_storm": 0.2, "kp_max": 3.5},
        3: {"p_storm": 0.3, "kp_max": 4.0},
    }

    archived_paths = _all_products_archived(tmp_path / "archive")
    mock_archive.return_value = archived_paths

    result_path = main(run_start=run_start)

    expected_dir = forecasts_dir / "2026-01-02"  # D+1
    assert result_path == expected_dir / f"{MODEL_NAME}.20260101T060000Z.json"
    assert result_path.exists()

    payload = json.loads(result_path.read_text())
    assert payload["model"] == MODEL_NAME
    assert payload["model_variant"] == "main"
    assert payload["l1_valid"] is True
    assert payload["artifacts_sha256"] == digest
    assert "issue_time" in payload and "RFC-3161" in payload["issue_time"]
    assert payload["run_start"] == "2026-01-01T06:00:00Z"
    assert payload["targets"] == [
        {"date": "2026-01-02", "kp_max": 3.0, "p_storm": 0.1},
        {"date": "2026-01-03", "kp_max": 3.5, "p_storm": 0.2},
        {"date": "2026-01-04", "kp_max": 4.0, "p_storm": 0.3},
    ]
    assert payload["l1_source"] == "SOLAR1"
    assert payload["l1_density_2h_mean"] == pytest.approx(4.2)
    assert payload["l1_speed_2h_mean"] == pytest.approx(400.0)
    assert payload["features"]["1"] == {
        "persistence": 4.0, "recurrence": 3.0, "climatology": 0.1,
        "l1_bz_gsm": -5.0, "l1_by_gsm": 1.0, "l1_speed": 400.0,
        "l1_dyn_pressure": 2.0, "l1_newell": 3000.0,
    }
    assert set(payload["features"]) == {"1", "2", "3"}

    # forecast json + both archived files must be frozen
    frozen_paths = {call.args[0] for call in mock_freeze.call_args_list}
    assert result_path in frozen_paths
    assert archived_paths["solar_probabilities.json"] in frozen_paths
    assert archived_paths["sgarf.txt"] in frozen_paths
    mock_archive.assert_called_once()


@patch("swcast.forecast.freeze_file")
@patch("swcast.forecast.archive_live_products")
@patch("swcast.forecast.predict")
@patch("swcast.forecast.build_live_features")
@patch("swcast.forecast._artifacts_path")
@patch("swcast.forecast.load_config")
def test_main_uses_fallback_variant_when_l1_invalid(
    mock_cfg, mock_path, mock_build_features, mock_predict, mock_archive, mock_freeze, tmp_path,
):
    artifacts_path = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    digest = _write_artifacts(artifacts_path)
    Path(f"{artifacts_path}.sha256").write_text(f"{digest}  model_artifacts.json\n")
    mock_path.return_value = artifacts_path
    mock_cfg.return_value = _cfg(tmp_path / "forecasts")
    mock_archive.return_value = _all_products_archived(tmp_path / "archive")

    run_start = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    mock_build_features.return_value = _fake_live_features(run_start, l1_valid=False)
    mock_predict.return_value = {i: {"p_storm": 0.1, "kp_max": 3.0} for i in (1, 2, 3)}

    result_path = main(run_start=run_start)
    payload = json.loads(result_path.read_text())
    assert payload["model_variant"] == "fallback"
    assert payload["l1_valid"] is False


# ---------------------------------------------------------------------------
# main(): failures in the prediction step -> MISSED file, no forecast json,
# SWPC still archived, and ForecastRunError raised at the end.
# ---------------------------------------------------------------------------

@patch("swcast.forecast.freeze_file")
@patch("swcast.forecast.archive_live_products")
@patch("swcast.forecast.predict")
@patch("swcast.forecast.build_live_features")
@patch("swcast.forecast._artifacts_path")
@patch("swcast.forecast.load_config")
def test_main_missing_feature_writes_missed_json_and_still_archives(
    mock_cfg, mock_path, mock_build_features, mock_predict, mock_archive, mock_freeze, tmp_path,
):
    artifacts_path = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    digest = _write_artifacts(artifacts_path)
    Path(f"{artifacts_path}.sha256").write_text(f"{digest}  model_artifacts.json\n")
    mock_path.return_value = artifacts_path

    forecasts_dir = tmp_path / "forecasts"
    mock_cfg.return_value = _cfg(forecasts_dir)

    run_start = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    mock_build_features.return_value = _fake_live_features(run_start)
    mock_predict.side_effect = MissingFeatureError("day+1: required feature(s) NaN/missing: ['persistence']")

    archived_paths = _all_products_archived(tmp_path / "archive")
    mock_archive.return_value = archived_paths

    with pytest.raises(ForecastRunError, match="MissingFeatureError"):
        main(run_start=run_start)

    expected_dir = forecasts_dir / "2026-01-02"
    missed_path = expected_dir / "MISSED.20260101T060000Z.json"
    assert missed_path.exists()
    # no forecast json for this run
    assert not (expected_dir / f"{MODEL_NAME}.20260101T060000Z.json").exists()

    payload = json.loads(missed_path.read_text())
    assert payload["model"] == MODEL_NAME
    assert payload["error_type"] == "MissingFeatureError"
    assert "persistence" in payload["reason"]

    mock_archive.assert_called_once()
    frozen_paths = {call.args[0] for call in mock_freeze.call_args_list}
    assert missed_path in frozen_paths
    for path in archived_paths.values():
        assert path in frozen_paths


@patch("swcast.forecast.freeze_file")
@patch("swcast.forecast.archive_live_products")
@patch("swcast.forecast.predict")
@patch("swcast.forecast.build_live_features")
@patch("swcast.forecast._artifacts_path")
@patch("swcast.forecast.load_config")
def test_main_gfz_outage_writes_missed_json_and_still_archives(
    mock_cfg, mock_path, mock_build_features, mock_predict, mock_archive, mock_freeze, tmp_path,
):
    """A non-MissingFeatureError failure (e.g. GFZ nowcast API down) must be
    handled exactly the same way: MISSED written, SWPC still archived, and
    the run must not crash uncaught."""
    artifacts_path = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    digest = _write_artifacts(artifacts_path)
    Path(f"{artifacts_path}.sha256").write_text(f"{digest}  model_artifacts.json\n")
    mock_path.return_value = artifacts_path

    forecasts_dir = tmp_path / "forecasts"
    mock_cfg.return_value = _cfg(forecasts_dir)

    run_start = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    mock_build_features.side_effect = ConnectionError("GFZ nowcast API unreachable")
    archived_paths = _all_products_archived(tmp_path / "archive")
    mock_archive.return_value = archived_paths

    with pytest.raises(ForecastRunError, match="ConnectionError"):
        main(run_start=run_start)

    mock_predict.assert_not_called()

    expected_dir = forecasts_dir / "2026-01-02"
    missed_path = expected_dir / "MISSED.20260101T060000Z.json"
    payload = json.loads(missed_path.read_text())
    assert payload["error_type"] == "ConnectionError"
    assert "unreachable" in payload["reason"]
    mock_archive.assert_called_once()


@patch("swcast.forecast.archive_live_products")
@patch("swcast.forecast.predict")
@patch("swcast.forecast.build_live_features")
@patch("swcast.forecast._artifacts_path")
@patch("swcast.forecast.load_config")
def test_main_both_tsas_down_missed_file_kept_unfrozen_but_still_raises(
    mock_cfg, mock_path, mock_build_features, mock_predict, mock_archive, tmp_path,
):
    """
    If freeze_file itself raises (both TSAs down) while freezing the MISSED
    file, the file must still be kept on disk and the run must still signal
    failure — it must not silently look like a clean run.
    """
    artifacts_path = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    digest = _write_artifacts(artifacts_path)
    Path(f"{artifacts_path}.sha256").write_text(f"{digest}  model_artifacts.json\n")
    mock_path.return_value = artifacts_path

    forecasts_dir = tmp_path / "forecasts"
    mock_cfg.return_value = _cfg(forecasts_dir)

    run_start = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    mock_build_features.side_effect = TimeoutError("GFZ nowcast timed out")
    mock_archive.return_value = _all_products_archived(tmp_path / "archive")

    with patch("swcast.forecast.freeze_file") as mock_freeze:
        mock_freeze.side_effect = RuntimeError("Both TSA requests failed")
        with pytest.raises(ForecastRunError, match="missed-freeze"):
            main(run_start=run_start)

    expected_dir = forecasts_dir / "2026-01-02"
    missed_path = expected_dir / "MISSED.20260101T060000Z.json"
    assert missed_path.exists()  # kept even though freezing it failed
    payload = json.loads(missed_path.read_text())
    assert payload["error_type"] == "TimeoutError"


# ---------------------------------------------------------------------------
# main(): a single missing SWPC product must not block the others, but must
# still be reported as a failure at the end.
# ---------------------------------------------------------------------------

@patch("swcast.forecast.freeze_file")
@patch("swcast.forecast.archive_live_products")
@patch("swcast.forecast.predict")
@patch("swcast.forecast.build_live_features")
@patch("swcast.forecast._artifacts_path")
@patch("swcast.forecast.load_config")
def test_main_one_swpc_product_down_still_raises_but_forecast_and_others_ok(
    mock_cfg, mock_path, mock_build_features, mock_predict, mock_archive, mock_freeze, tmp_path,
):
    artifacts_path = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    digest = _write_artifacts(artifacts_path)
    Path(f"{artifacts_path}.sha256").write_text(f"{digest}  model_artifacts.json\n")
    mock_path.return_value = artifacts_path

    forecasts_dir = tmp_path / "forecasts"
    mock_cfg.return_value = _cfg(forecasts_dir)

    run_start = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    mock_build_features.return_value = _fake_live_features(run_start)
    mock_predict.return_value = {i: {"p_storm": 0.1, "kp_max": 3.0} for i in (1, 2, 3)}

    # sgarf.txt failed to fetch; archive_live_products already swallowed that
    # internally and just returns fewer keys.
    all_products = _all_products_archived(tmp_path / "archive")
    del all_products["sgarf.txt"]
    mock_archive.return_value = all_products

    with pytest.raises(ForecastRunError, match="sgarf.txt"):
        main(run_start=run_start)

    expected_dir = forecasts_dir / "2026-01-02"
    result_path = expected_dir / f"{MODEL_NAME}.20260101T060000Z.json"
    assert result_path.exists()  # forecast itself still succeeded

    frozen_paths = {call.args[0] for call in mock_freeze.call_args_list}
    assert result_path in frozen_paths
    for path in all_products.values():
        assert path in frozen_paths


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@patch("swcast.forecast.freeze_models")
def test_cli_freeze_models_flag_does_not_run_main(mock_freeze_models):
    with patch("swcast.forecast.main") as mock_main:
        assert _cli(["--freeze-models"]) == 0
        mock_freeze_models.assert_called_once()
        mock_main.assert_not_called()


@patch("swcast.forecast.main")
def test_cli_default_runs_main_and_returns_zero_on_success(mock_main):
    assert _cli([]) == 0
    mock_main.assert_called_once()


@patch("swcast.forecast.main")
def test_cli_returns_nonzero_on_forecast_run_error(mock_main):
    mock_main.side_effect = ForecastRunError("forecast: ConnectionError: down")
    assert _cli([]) == 1


@patch("swcast.forecast.dry_run")
def test_cli_dry_run_flag_does_not_run_main(mock_dry_run):
    mock_dry_run.return_value = 0
    with patch("swcast.forecast.main") as mock_main:
        assert _cli(["--dry-run"]) == 0
        mock_dry_run.assert_called_once()
        mock_main.assert_not_called()


# ---------------------------------------------------------------------------
# dry_run(): real pipeline shape, but nothing written/frozen; no artifact-
# freeze gate (must work before --freeze-models has ever run).
# ---------------------------------------------------------------------------

@patch("swcast.forecast.freeze_file")
@patch("swcast.forecast.archive_live_products")
@patch("swcast.forecast.predict")
@patch("swcast.forecast.build_live_features")
@patch("swcast.forecast._artifacts_path")
@patch("swcast.forecast.load_config")
def test_dry_run_writes_and_freezes_nothing(
    mock_cfg, mock_path, mock_build_features, mock_predict, mock_archive, mock_freeze, tmp_path, capsys,
):
    artifacts_path = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    _write_artifacts(artifacts_path)  # NOTE: no .sha256 sidecar written at all
    mock_path.return_value = artifacts_path
    mock_cfg.return_value = _cfg(tmp_path / "forecasts")

    run_start = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    mock_build_features.return_value = _fake_live_features(run_start)
    mock_predict.return_value = {i: {"p_storm": 0.1 * i, "kp_max": 3.0 + i} for i in (1, 2, 3)}

    rc = dry_run(run_start=run_start)

    assert rc == 0
    mock_archive.assert_not_called()
    mock_freeze.assert_not_called()
    assert not (tmp_path / "forecasts").exists()

    out = capsys.readouterr().out
    assert "p_storm" in out
    assert "0.1000" in out


@patch("swcast.forecast.predict")
@patch("swcast.forecast.build_live_features")
@patch("swcast.forecast._artifacts_path")
@patch("swcast.forecast.load_config")
def test_dry_run_reports_missing_feature_without_raising(
    mock_cfg, mock_path, mock_build_features, mock_predict, tmp_path, capsys,
):
    artifacts_path = tmp_path / "models" / MODEL_NAME / "model_artifacts.json"
    _write_artifacts(artifacts_path)
    mock_path.return_value = artifacts_path
    mock_cfg.return_value = _cfg(tmp_path / "forecasts")

    run_start = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    mock_build_features.return_value = _fake_live_features(run_start)
    mock_predict.side_effect = MissingFeatureError("day+1: required feature(s) NaN/missing: ['persistence']")

    rc = dry_run(run_start=run_start)

    assert rc == 1
    out = capsys.readouterr().out
    assert "MISS" in out

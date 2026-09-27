"""Tests for swcast.forecast – all network/freeze functions mocked, no filesystem
side effects outside tmp_path, nothing written to the real forecasts/ dir."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from swcast.forecast import _cli, freeze_models, main
from swcast.live_features import MissingFeatureError

MODEL_NAME = "swcast-kp-baseline-v0"


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
        i: {"target_date": run_start.date() + timedelta(days=i)}
        for i in (1, 2, 3)
    }
    return {
        "run_start": run_start,
        "inputs_last_data_time": last_data_time or run_start,
        "l1_valid": l1_valid,
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

    archived_paths = {
        "solar_probabilities.json": tmp_path / "archive" / "sp.json",
        "sgarf.txt": tmp_path / "archive" / "sgarf.txt",
    }
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
    mock_archive.return_value = {}

    run_start = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    mock_build_features.return_value = _fake_live_features(run_start, l1_valid=False)
    mock_predict.return_value = {i: {"p_storm": 0.1, "kp_max": 3.0} for i in (1, 2, 3)}

    result_path = main(run_start=run_start)
    payload = json.loads(result_path.read_text())
    assert payload["model_variant"] == "fallback"
    assert payload["l1_valid"] is False


# ---------------------------------------------------------------------------
# main(): MissingFeatureError -> MISSED file, no forecast json, SWPC still archived
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

    archived_paths = {"solar_probabilities.json": tmp_path / "archive" / "sp.json"}
    mock_archive.return_value = archived_paths

    result_path = main(run_start=run_start)

    assert result_path is None

    expected_dir = forecasts_dir / "2026-01-02"
    missed_path = expected_dir / f"MISSED.20260101T060000Z.json"
    assert missed_path.exists()
    # no forecast json for this run
    assert not (expected_dir / f"{MODEL_NAME}.20260101T060000Z.json").exists()

    payload = json.loads(missed_path.read_text())
    assert payload["model"] == MODEL_NAME
    assert "persistence" in payload["reason"]

    mock_archive.assert_called_once()
    frozen_paths = {call.args[0] for call in mock_freeze.call_args_list}
    assert missed_path in frozen_paths
    assert archived_paths["solar_probabilities.json"] in frozen_paths


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@patch("swcast.forecast.freeze_models")
def test_cli_freeze_models_flag_does_not_run_main(mock_freeze_models):
    with patch("swcast.forecast.main") as mock_main:
        _cli(["--freeze-models"])
        mock_freeze_models.assert_called_once()
        mock_main.assert_not_called()


@patch("swcast.forecast.main")
def test_cli_default_runs_main(mock_main):
    _cli([])
    mock_main.assert_called_once()

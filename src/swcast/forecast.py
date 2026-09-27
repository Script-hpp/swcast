"""
forecast.py – daily swcast-kp-baseline-v0 live run.

main(run_start=None):
  1. run_start = now (UTC) if not given; build live features + predict.
  2. Write the Kp forecast JSON (PRD.md §6) to
     forecasts/<target_date_day+1>/<model>.<run_start %Y%m%dT%H%M%SZ>.json,
     then freeze_file() it.
  3. archive_live_products() for SWPC (daypre, sgarf, solar_probabilities,
     Kp forecast), freeze_file() each archived file.
  4. If build_live_features/predict raises MissingFeatureError: no forecast
     JSON is written; instead forecasts/<date>/MISSED.<run_start>.json is
     written and frozen, recording the reason. SWPC is still archived.

The JSON never sets its own `issue_time`: per PREREGISTRATION §6 the
authoritative issue time is the earliest verified RFC-3161 timestamp of this
file (see freeze.issue_time on the produced .freetsa.tsr/.digicert.tsr), not
a self-reported clock value. The JSON instead carries a note saying so.

python -m swcast.forecast --freeze-models is a one-off command that freezes
models/<model>/model_artifacts.json (TSA + OTS). It must be run once before
the first live prediction. main() refuses to run (RuntimeError) if that
artifacts file has no matching, unmodified .sha256 sidecar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from swcast.config import load_config
from swcast.fetch.swpc import archive_live_products
from swcast.freeze import freeze_file
from swcast.live_features import MissingFeatureError, build_live_features, predict

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _model_name(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    return cfg["kp_baseline"]["model_name"]


def _artifacts_path(model_name: str | None = None) -> Path:
    model_name = model_name or _model_name()
    return _REPO_ROOT / "models" / model_name / "model_artifacts.json"


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_models(model_name: str | None = None) -> Path:
    """One-off: freeze model_artifacts.json (TSA + OTS). Must run before the first live run."""
    path = _artifacts_path(model_name)
    if not path.exists():
        raise FileNotFoundError(f"Model artifacts not found: {path}")
    freeze_file(path)
    logger.info("Froze model artifacts: %s", path)
    return path


def _verify_artifacts_frozen(artifacts_path: Path) -> str:
    """
    Confirm model_artifacts.json was frozen (via --freeze-models) and is
    unmodified since. Returns its SHA-256 digest.
    """
    sha_path = Path(f"{artifacts_path}.sha256")
    if not artifacts_path.exists():
        raise RuntimeError(f"Model artifacts not found: {artifacts_path}")
    if not sha_path.exists():
        raise RuntimeError(
            f"Model artifacts are not frozen: {sha_path} missing. "
            "Run `python -m swcast.forecast --freeze-models` first."
        )
    digest = _sha256_of(artifacts_path)
    recorded = sha_path.read_text().split()[0]
    if digest != recorded:
        raise RuntimeError(
            f"Model artifacts changed since freezing: {artifacts_path} has "
            f"sha256 {digest}, but {sha_path} records {recorded}."
        )
    return digest


def _load_artifacts(artifacts_path: Path) -> dict:
    with open(artifacts_path, encoding="utf-8") as f:
        return json.load(f)


def _forecasts_dir(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    return Path(cfg["paths"]["forecasts_dir"])


def _iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_and_freeze(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    freeze_file(path)
    return path


def main(run_start: datetime | None = None) -> Path | None:
    """Run the daily forecast. Returns the forecast JSON path, or None if MISSED."""
    cfg = load_config()
    model_name = _model_name(cfg)
    artifacts_path = _artifacts_path(model_name)
    artifacts_sha256 = _verify_artifacts_frozen(artifacts_path)
    artifacts = _load_artifacts(artifacts_path)

    if run_start is None:
        run_start = datetime.now(timezone.utc)

    run_stamp = run_start.strftime("%Y%m%dT%H%M%SZ")
    day1_date = run_start.date() + timedelta(days=1)
    out_dir = _forecasts_dir(cfg) / day1_date.isoformat()

    result_path: Path | None = None
    try:
        features = build_live_features(run_start)
        predictions = predict(features, artifacts)

        targets = []
        for i in (1, 2, 3):
            target_date = features["days"][i]["target_date"]
            targets.append({
                "date": target_date.isoformat(),
                "kp_max": predictions[i]["kp_max"],
                "p_storm": predictions[i]["p_storm"],
            })

        payload = {
            "model": model_name,
            "model_variant": "main" if features["l1_valid"] else "fallback",
            "run_start": _iso_z(run_start),
            "inputs_last_data_time": _iso_z(features["inputs_last_data_time"]),
            "l1_valid": features["l1_valid"],
            "artifacts_sha256": artifacts_sha256,
            "issue_time": "earliest verified RFC-3161 timestamp of this file (PREREGISTRATION §6)",
            "targets": targets,
        }

        result_path = out_dir / f"{model_name}.{run_stamp}.json"
        _write_and_freeze(result_path, payload)
        logger.info("Forecast written and frozen: %s", result_path)

    except MissingFeatureError as exc:
        missed_payload = {
            "model": model_name,
            "run_start": _iso_z(run_start),
            "reason": str(exc),
        }
        missed_path = out_dir / f"MISSED.{run_stamp}.json"
        _write_and_freeze(missed_path, missed_payload)
        logger.warning("No forecast produced (missing features): %s", missed_path)
        result_path = None

    # SWPC archival happens regardless of whether the swcast forecast succeeded.
    archived = archive_live_products()
    for archived_path in archived.values():
        freeze_file(archived_path)

    return result_path


def _cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="swcast daily Kp forecast run")
    parser.add_argument(
        "--freeze-models", action="store_true",
        help="One-off: freeze models/<model>/model_artifacts.json (TSA+OTS) before the first live run",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)

    if args.freeze_models:
        freeze_models()
        return

    main()


if __name__ == "__main__":
    _cli()

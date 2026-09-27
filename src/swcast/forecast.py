"""
forecast.py – daily swcast-kp-baseline-v0 live run.

main(run_start=None):
  1. run_start = now (UTC) if not given; build live features + predict.
  2. Write the Kp forecast JSON (PRD.md §6) to
     forecasts/<target_date_day+1>/<model>.<run_start %Y%m%dT%H%M%SZ>.json,
     then freeze_file() it.
  3. archive_live_products() for SWPC (daypre, sgarf, solar_probabilities,
     Kp forecast), freeze_file() each archived file.
  4. If the prediction step raises ANY exception (MissingFeatureError, GFZ/
     SWPC outage, freeze_file failing because both TSAs are down, ...): no
     forecast JSON is written; instead forecasts/<date>/MISSED.<run_start>.json
     is written recording the error type and message, and freezing that file
     is attempted too (best-effort: if freezing it also fails, the file is
     still kept and the failure logged). SWPC archival is attempted next
     regardless — archive_live_products() fetches each product independently,
     so one missing product never blocks the others.
  5. If anything failed anywhere in the run (prediction, SWPC fetch, or any
     freeze), main() raises ForecastRunError at the very end, after every
     output that could be produced was written. The CLI uses this to exit
     non-zero so GitHub Actions notices.

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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from swcast.config import load_config
from swcast.fetch.swpc import LIVE_PRODUCTS, archive_live_products
from swcast.freeze import freeze_file
from swcast.live_features import build_live_features, predict

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]


class ForecastRunError(Exception):
    """
    Raised by main() at the very end if any part of the run failed, after
    every possible output (forecast/MISSED json, SWPC archive) was still
    attempted and written to disk. Outputs already on disk are unaffected;
    this only signals failure to the caller (the CLI exits non-zero on it).
    """


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
    """
    Run the daily forecast. Returns the forecast JSON path, or None if MISSED.

    Raises ForecastRunError at the end if anything failed anywhere in the
    run — but only after writing every output it could still produce.
    """
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
    failures: list[str] = []

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
            "l1_fallback_reason": features.get("l1_fallback_reason"),
            "artifacts_sha256": artifacts_sha256,
            "issue_time": "earliest verified RFC-3161 timestamp of this file (PREREGISTRATION §6)",
            "targets": targets,
        }

        result_path = out_dir / f"{model_name}.{run_stamp}.json"
        _write_and_freeze(result_path, payload)
        logger.info("Forecast written and frozen: %s", result_path)

    except Exception as exc:
        # ANY failure here (MissingFeatureError, GFZ nowcast down, network
        # timeout, freeze_file raising because both TSAs are down, ...) must
        # neither crash the run nor go unnoticed — log a MISSED record and
        # keep going so SWPC archival still gets a chance to run.
        failures.append(f"forecast: {type(exc).__name__}: {exc}")
        logger.warning("No forecast produced (%s): %s", type(exc).__name__, exc)
        result_path = None

        missed_payload = {
            "model": model_name,
            "run_start": _iso_z(run_start),
            "error_type": type(exc).__name__,
            "reason": str(exc),
        }
        missed_path = out_dir / f"MISSED.{run_stamp}.json"
        try:
            _write_and_freeze(missed_path, missed_payload)
        except Exception as freeze_exc:
            failures.append(f"missed-freeze: {type(freeze_exc).__name__}: {freeze_exc}")
            logger.error(
                "Could not freeze MISSED file %s (kept unfrozen on disk): %s",
                missed_path, freeze_exc,
            )

    # SWPC archival is always attempted, regardless of the forecast outcome.
    # archive_live_products() fetches each product independently, so one
    # missing product never blocks the others.
    archived = archive_live_products()
    for name, archived_path in archived.items():
        try:
            freeze_file(archived_path)
        except Exception as exc:
            failures.append(f"swpc-freeze:{name}: {type(exc).__name__}: {exc}")
            logger.error("Could not freeze archived SWPC product %s: %s", archived_path, exc)

    for name in sorted(set(LIVE_PRODUCTS) - set(archived)):
        failures.append(f"swpc-fetch:{name}: not archived")
        logger.error("SWPC product not archived: %s", name)

    if failures:
        raise ForecastRunError("; ".join(failures))

    return result_path


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="swcast daily Kp forecast run")
    parser.add_argument(
        "--freeze-models", action="store_true",
        help="One-off: freeze models/<model>/model_artifacts.json (TSA+OTS) before the first live run",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)

    if args.freeze_models:
        freeze_models()
        return 0

    try:
        main()
    except ForecastRunError as exc:
        logger.error("Forecast run had failures: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())

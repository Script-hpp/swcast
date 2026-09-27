"""
evaluate.py – laufende Live-Auswertung von swcast-kp-baseline-v0
(PREREGISTRATION.md §4–§6, §8; nur beschreibend/vorläufig, siehe §5:
maßgeblich ist erst N = 365 Tage).

Implementierungsentscheidung: Welche swcast-Vorhersage zählt
------------------------------------------------------------
Für jeden Lauftag D wird unter allen an diesem Tag geschriebenen
Vorhersage-Dateien (forecast ODER MISSED, jeweils mit `run_start` im
JSON) NUR der FRÜHESTE Versuch mit `run_start` an Tag D um oder nach
22:00 UTC berücksichtigt. Jeder spätere Wiederholungslauf desselben
Tages wird komplett ignoriert – auch dann, wenn er selbst einen
gültigen TSA-Zeitstempel hätte. Sonst könnte man beliebig oft neu
starten, bis ein Lauf zufällig gültig wird (§6 Missbrauchsschutz).

Dieser eine ausgewählte Versuch zählt für Vorlauftag k (1/2/3) als
GÜLTIG, wenn er ein `p_storm` für k enthält UND sein per
`freeze.issue_time` geprüfter TSA-Zeitstempel < 00:00 UTC des Zieltags
D+k liegt (§6). Das wird pro k einzeln geprüft, weil die Frist mit k
später liegt: ein Lauf kann für k=1 knapp zu spät sein, aber für k=2/3
noch rechtzeitig. Gibt es für D gar keinen qualifizierenden Versuch,
oder schlägt die Prüfung für ein bestimmtes k fehl, gilt D für dieses k
als "verpasst" und wird nach §6/§5 hart durch die Klimatologie-Vorhersage
ersetzt (der Brier-Score dieses Tages ist dann exakt der der
Klimatologie).

SWPC (§8): Für Lauftag D zählt das an D archivierte `daypre`-Produkt
(3-day-solar-geomag-predictions.txt) nur, wenn sein `issue_time`-Datum
== D ist (`is_valid_live_product`); sonst gilt SWPC für D als fehlend
und der Tag wird aus dem gepaarten ΔBSS ausgeschlossen (Anzahl wird
berichtet), zählt aber weiter für BSS(swcast) allein.
P = Mid-Minor-Storm + Mid-Major-Severe-Storm, rekalibriert (oder roh)
nach der je Vorlauftag in `model_artifacts.json["swpc_recalibration"]`
festgehaltenen Referenzvariante (PREREGISTRATION §8), Clip [0.005, 0.995]
vor dem Logit.

Label (§1, §4): GFZ-Nowcast-Tagesmaximum Kp >= 5.0 (maßgeblich).
Tage mit Lücke im Nowcast werden ausgeschlossen (Anzahl wird berichtet).
Zusätzlich rein beschreibend dieselbe Auswertung gegen GFZ definitiv,
sobald verfügbar (siehe `definitive_label_comparison`).

Klimatologie (§4): Sturmtag-Anteil der exakt 365 Tage bis einschließlich
D−1 (GFZ-Nowcast), wobei D hier der Lauftag ist (= Zieltag − k).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from swcast.config import load_config
from swcast.fetch.kp import daily_storm_label, fetch_nowcast, fetch_training_data
from swcast.fetch.swpc import is_valid_live_product, parse_daypre
from swcast.freeze import issue_time
from swcast.metrics import block_bootstrap_ci, brier_skill_score
from swcast.training.generate_report import recalibrate_swpc

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]

BLOCK_DAYS = 27
BOOTSTRAP_ITERATIONS = 10_000
BOOTSTRAP_SEED = 2026
KEEP_UP_MARGIN = -0.05
DAY_AHEADS = (1, 2, 3)


def _model_name(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    return cfg["kp_baseline"]["model_name"]


def _artifacts_path(model_name: str | None = None) -> Path:
    model_name = model_name or _model_name()
    return _REPO_ROOT / "models" / model_name / "model_artifacts.json"


def _forecasts_dir(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    return Path(cfg["paths"]["forecasts_dir"])


def _archive_swpc_dir(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    return Path(cfg["paths"]["archive_swpc_dir"])


def _reports_dir(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    return Path(cfg["paths"]["reports_dir"])


def _parse_run_start(payload: dict) -> datetime | None:
    raw = payload.get("run_start")
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# swcast forecast selection (PREREGISTRATION §6)
# ---------------------------------------------------------------------------

def select_swcast_forecasts(forecast_json_paths: list[Path], issue_time_fn=issue_time) -> dict[date, dict]:
    """
    Pick the single counted attempt per run-day D, per the rule in this
    module's docstring. `forecast_json_paths` is every forecasts/*/*.json
    file (forecast AND MISSED; anything else, e.g. START.md, must already
    be filtered out by the caller).

    Returns {D: {"path", "run_start", "payload", "issue_time"}}. `issue_time`
    is None if the file could not be verified at all (e.g. MISSED files
    have no .tsr tokens, or both TSAs failed) — such a day is then "missed"
    for every k, since there is nothing to check a deadline against.
    """
    by_day: dict[date, list[tuple[datetime, Path, dict]]] = {}
    for path in forecast_json_paths:
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable forecast file %s: %s", path, exc)
            continue
        run_start = _parse_run_start(payload)
        if run_start is None or run_start.hour < 22:
            continue  # not a qualifying daily-run attempt
        by_day.setdefault(run_start.date(), []).append((run_start, path, payload))

    selected: dict[date, dict] = {}
    for d, candidates in by_day.items():
        candidates.sort(key=lambda c: c[0])
        run_start, path, payload = candidates[0]  # earliest attempt only; later reruns ignored
        ts = None
        if "targets" in payload:  # only real forecast files have a TSA-worthy file to check
            try:
                ts = issue_time_fn(path)
            except Exception as exc:
                logger.warning("issue_time() failed for %s: %s", path, exc)
                ts = None
        selected[d] = {"path": path, "run_start": run_start, "payload": payload, "issue_time": ts}
    return selected


def _valid_for_k(entry: dict, run_day: date, k: int) -> bool:
    """PREREGISTRATION §6: TSA timestamp must be < 00:00 UTC of the target day D+k."""
    if entry["issue_time"] is None or "targets" not in entry["payload"]:
        return False
    deadline = datetime.combine(run_day + timedelta(days=k), datetime.min.time(), tzinfo=timezone.utc)
    return entry["issue_time"] < deadline


# ---------------------------------------------------------------------------
# SWPC (PREREGISTRATION §8)
# ---------------------------------------------------------------------------

def _find_swpc_for_day(daypre_paths: list[Path], run_day: date) -> pd.DataFrame | None:
    """The daypre product archived on run_day, or None if none/no valid one exists."""
    for path in sorted(daypre_paths):
        try:
            df = parse_daypre(path.read_text())
        except Exception as exc:
            logger.debug("Could not parse %s as daypre: %s", path, exc)
            continue
        if is_valid_live_product(df, run_day):
            return df
    return None


def _p_swpc_for_k(df_swpc: pd.DataFrame, k: int, recal: dict) -> float:
    p_raw = float(df_swpc.iloc[k - 1]["p_storm"])
    if recal.get("use_calib"):
        return float(recalibrate_swpc(np.array([p_raw]), recal["coef"], recal["intercept"])[0])
    return p_raw


# ---------------------------------------------------------------------------
# GFZ label + climatology (PREREGISTRATION §1, §4)
# ---------------------------------------------------------------------------

def _daily_dict(df_kp: pd.DataFrame) -> dict[date, dict]:
    df_daily = daily_storm_label(df_kp)
    return df_daily.set_index("date").to_dict("index")


def _label_for_date(daily_dict: dict, target_date: date) -> float:
    """1.0 / 0.0 / NaN (gap or no data)."""
    info = daily_dict.get(target_date)
    if not info or pd.isna(info["storm_label"]):
        return float("nan")
    return 1.0 if info["storm_label"] else 0.0


def climatology_rate(daily_dict: dict, run_day: date) -> float:
    """Storm-day fraction over the 365 days up to and including run_day - 1."""
    storms = 0
    valid = 0
    for i in range(1, 366):
        d = run_day - timedelta(days=i)
        info = daily_dict.get(d)
        if info and pd.notna(info["storm_label"]):
            valid += 1
            if info["storm_label"]:
                storms += 1
    return storms / valid if valid > 0 else float("nan")


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------

def build_evaluation_rows(
    selected: dict[date, dict],
    run_days: set[date],
    daypre_paths: list[Path],
    daily_dict: dict[date, dict],
    artifacts: dict,
) -> list[dict]:
    """
    One row per (target_date, k) for every run-day D in `run_days`.
    `run_days` should be the FULL calendar-day universe (see
    `build_run_day_universe`), not just days that happen to have a file —
    a day the daily run never even attempted (GitHub Actions down, no
    forecast, no MISSED file) must still show up here as missed, or an
    outage would silently disappear from the evaluation instead of
    counting against it (PREREGISTRATION §6).
    `selected` need not have an entry for every D in `run_days`: that's
    either because there's truly no file for that day, or because the
    only attempt(s) were before 22:00 UTC and don't qualify.
    """
    rows = []
    swpc_cache: dict[date, pd.DataFrame | None] = {}

    for run_day in sorted(run_days):
        entry = selected.get(run_day)
        clim = climatology_rate(daily_dict, run_day)

        if run_day not in swpc_cache:
            swpc_cache[run_day] = _find_swpc_for_day(daypre_paths, run_day)
        df_swpc = swpc_cache[run_day]

        for k in DAY_AHEADS:
            target_date = run_day + timedelta(days=k)
            missed = entry is None or not _valid_for_k(entry, run_day, k)

            if missed:
                p_swcast = clim
                model_variant = None
            else:
                targets = entry["payload"]["targets"]
                target_row = next(t for t in targets if t["date"] == target_date.isoformat())
                p_swcast = float(target_row["p_storm"])
                model_variant = entry["payload"].get("model_variant")

            label = _label_for_date(daily_dict, target_date)
            label_gap = pd.isna(label)

            recal = artifacts.get("swpc_recalibration", {}).get(str(k), {})
            if df_swpc is not None and not recal_missing(recal):
                p_swpc = _p_swpc_for_k(df_swpc, k, recal)
                swpc_missing = False
            else:
                p_swpc = float("nan")
                swpc_missing = True

            reasons = []
            if entry is None:
                # No forecast/MISSED file at all for this run-day (e.g. the
                # cron didn't run) — a purely descriptive label, distinct
                # from "swpc_fehlt"/"gfz_luecke": it does NOT exclude the
                # day from the paired ΔBSS (§5 still substitutes climatology
                # and scores it), it only records *why* it was missed.
                reasons.append("kein_lauf")
            if swpc_missing:
                reasons.append("swpc_fehlt")
            if label_gap:
                reasons.append("gfz_luecke")

            rows.append({
                "Datum": target_date.isoformat(),
                "k": k,
                "p_swcast": p_swcast,
                "verpasst": missed,
                "model_variant": model_variant,
                "p_swpc": p_swpc,
                "Label": label,
                "Klimatologie": clim,
                "Ausschlussgrund": ",".join(reasons),
            })
    return rows


def recal_missing(recal: dict) -> bool:
    return not recal or "coef" not in recal or "intercept" not in recal


def write_live_evaluation_csv(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=[
        "Datum", "k", "p_swcast", "verpasst", "model_variant", "p_swpc",
        "Label", "Klimatologie", "Ausschlussgrund",
    ])
    df.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# Stats + report
# ---------------------------------------------------------------------------

def classify(ci_low: float) -> str:
    if ci_low > 0:
        return "Übertreffen"
    if ci_low > KEEP_UP_MARGIN:
        return "Mithalten"
    return "nicht erreicht"


def compute_k_stats(rows_k: list[dict]) -> dict:
    """
    BSS(swcast), BSS(SWPC) and delta-BSS with a 95% block-bootstrap CI
    (PREREGISTRATION §4/§5), computed on the paired subset only (label
    present AND SWPC present) — missed swcast days (whether "kein_lauf",
    too late, or any other reason) stay IN this subset with p_swcast
    already substituted by climatology (§5); "kein_lauf" is a descriptive
    label in Ausschlussgrund, not a real exclusion from the paired set.
    """
    if not rows_k:
        return {
            "n": 0, "n_label_gap": 0, "n_swpc_missing": 0,
            "bss_swcast": float("nan"), "bss_swpc": float("nan"),
            "delta": (float("nan"), float("nan"), float("nan")), "classification": "zu wenig Daten",
        }

    df = pd.DataFrame(rows_k)
    n_label_gap = int(df["Ausschlussgrund"].str.contains("gfz_luecke").sum())
    n_swpc_missing = int(df["Ausschlussgrund"].str.contains("swpc_fehlt").sum())

    excluded = df["Ausschlussgrund"].str.contains("gfz_luecke") | df["Ausschlussgrund"].str.contains("swpc_fehlt")
    paired = df[~excluded].copy()
    if paired.empty:
        return {
            "n": 0, "n_label_gap": n_label_gap, "n_swpc_missing": n_swpc_missing,
            "bss_swcast": float("nan"), "bss_swpc": float("nan"),
            "delta": (float("nan"), float("nan"), float("nan")), "classification": "zu wenig Daten",
        }

    y = paired["Label"].to_numpy(dtype=float)
    p_sw = paired["p_swcast"].to_numpy(dtype=float)
    p_ref = paired["p_swpc"].to_numpy(dtype=float)
    clim = paired["Klimatologie"].to_numpy(dtype=float)
    day_index = pd.to_datetime(paired["Datum"]).map(pd.Timestamp.toordinal).to_numpy()

    bss_swcast = brier_skill_score(y, p_sw, clim)
    bss_swpc = brier_skill_score(y, p_ref, clim)

    values = np.column_stack([y, p_sw, p_ref, clim])

    def delta_bss(v: np.ndarray) -> float:
        return brier_skill_score(v[:, 0], v[:, 1], v[:, 3]) - brier_skill_score(v[:, 0], v[:, 2], v[:, 3])

    point, lo, hi = block_bootstrap_ci(
        values, day_index, delta_bss, block_length_days=BLOCK_DAYS,
        n_iterations=BOOTSTRAP_ITERATIONS, ci=0.95, seed=BOOTSTRAP_SEED,
    )
    classification = "zu wenig Daten" if math.isnan(lo) else classify(lo)

    return {
        "n": len(paired), "n_label_gap": n_label_gap, "n_swpc_missing": n_swpc_missing,
        "bss_swcast": bss_swcast, "bss_swpc": bss_swpc,
        "delta": (point, lo, hi), "classification": classification,
    }


def _read_start_date(start_path: Path) -> date | None:
    if not start_path.exists():
        return None
    for line in start_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            try:
                return date.fromisoformat(line.split()[0])
            except ValueError:
                continue
    return None


def days_since_start(forecasts_dir: Path) -> int | None:
    start_date = _read_start_date(forecasts_dir / "START.md")
    if start_date is None:
        return None
    return (datetime.now(timezone.utc).date() - start_date).days


def build_run_day_universe(forecasts_dir: Path, file_run_days: set[date], today: date | None = None) -> set[date]:
    """
    The full run-day universe to evaluate: every calendar day from the
    daily run's start (forecasts/START.md's target_date - 1) through
    yesterday (UTC), inclusive, regardless of whether a file exists for
    it — a day the cron silently skipped must still show up as missed
    (§6), or the outage would just vanish from the evaluation instead of
    counting against it.

    Before there is a START.md (the run has never produced a valid
    forecast yet), there's no fixed day to start counting from, so only
    days that actually have a file are considered.
    """
    start_target_date = _read_start_date(forecasts_dir / "START.md")
    if start_target_date is None:
        return set(file_run_days)

    run_day_start = start_target_date - timedelta(days=1)
    yesterday = (today or datetime.now(timezone.utc).date()) - timedelta(days=1)
    if run_day_start > yesterday:
        return set(file_run_days)

    n_days = (yesterday - run_day_start).days + 1
    all_days = {run_day_start + timedelta(days=i) for i in range(n_days)}
    return all_days | file_run_days


def maybe_write_start_md(rows: list[dict], forecasts_dir: Path) -> Path | None:
    """
    PREREGISTRATION §5: N=365 starts at the target_date +1 of the first
    forecast whose TSA proof was valid before its deadline. Written once,
    the first time such a row exists; never overwritten afterwards.
    """
    start_path = forecasts_dir / "START.md"
    if start_path.exists():
        return start_path

    k1_valid = [r for r in rows if r["k"] == 1 and not r["verpasst"]]
    if not k1_valid:
        return None

    first_date = min(date.fromisoformat(r["Datum"]) for r in k1_valid)
    start_path.parent.mkdir(parents=True, exist_ok=True)
    start_path.write_text(
        f"{first_date.isoformat()}\n\n"
        "N=365-Zählung (PREREGISTRATION §5) beginnt an diesem Zieltag (+1 der "
        "ersten Vorhersage mit gültigem TSA-Beleg vor der Deadline).\n"
    )
    return start_path


def rows_since_start(rows: list[dict], forecasts_dir: Path) -> list[dict]:
    """
    Filter rows down to target dates on or after forecasts/START.md's date.
    Used for the aggregated stats/counts table in live_status.md — not the
    raw CSV, which keeps the full history for audit purposes.

    Before the run has ever produced a valid forecast (no START.md yet),
    there is no official evaluation period, so this returns an empty list:
    stray runs (manual workflow_dispatch tests, etc.) must not pollute the
    "SWPC fehlt"/"GFZ-Lücke" counts or BSS with pre-start noise.
    """
    start_date = _read_start_date(forecasts_dir / "START.md")
    if start_date is None:
        return []
    return [r for r in rows if date.fromisoformat(r["Datum"]) >= start_date]


def definitive_label_comparison(rows: list[dict], start_year: int, end_year: int) -> list[dict] | None:
    """
    Rein beschreibend (§1): dieselbe Auswertung gegen GFZ definitiv statt
    Nowcast, sobald verfügbar. Best-effort — gibt None zurück, wenn
    definitive Daten (noch) nicht abrufbar sind, statt den Lauf
    fehlschlagen zu lassen.
    """
    try:
        df_def = fetch_training_data(start_year, end_year)
    except Exception as exc:
        logger.warning("GFZ definitive not available for descriptive comparison: %s", exc)
        return None
    daily_dict_def = _daily_dict(df_def)

    out = []
    for r in rows:
        target_date = date.fromisoformat(r["Datum"])
        label_def = _label_for_date(daily_dict_def, target_date)
        out.append({**r, "Label_definitiv": label_def})
    return out


DRIFT_FEATURES = (
    "persistence", "recurrence", "climatology",
    "l1_bz_gsm", "l1_by_gsm", "l1_speed", "l1_dyn_pressure", "l1_newell",
)


def compute_input_drift(forecast_json_paths: list[Path], artifacts: dict, k: int = 1) -> dict:
    """
    Rein beschreibend (kein Erfolgskriterium, ändert v0 nicht — PREREGISTRATION
    §9): pro Merkmal des Tag+k-Hauptmodells der Mittelwert über alle bisherigen
    Live-Läufe mit gültigem L1 gegen `scaler_mean`/`scaler_scale` aus dem
    Training als z-Wert: z = (Mittelwert_live - scaler_mean) / scaler_scale.
    Großes |z| heißt, die Live-Eingangsverteilung hat sich vom eingefrorenen
    Trainings-Scaler entfernt (z. B. weil eine andere rtsw-Sonde mit anderer
    Kalibrierung aktiv ist, siehe `l1_source`/`l1_density_2h_mean` im JSON).

    Nur Läufe mit gespeichertem `features` UND `l1_valid=True` fließen ein
    (Rückfall-Läufe haben keine sinnvollen l1_*-Werte).
    """
    art = artifacts["models"][str(k)]["p_storm_main"]
    feature_names = art["features"]
    per_feature_values: dict[str, list[float]] = {f: [] for f in feature_names}

    for path in forecast_json_paths:
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not payload.get("l1_valid"):
            continue
        day_features = payload.get("features", {}).get(str(k))
        if not day_features:
            continue
        for f in feature_names:
            v = day_features.get(f)
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                per_feature_values[f].append(float(v))

    drift = {}
    for f, mean_, scale_ in zip(feature_names, art["scaler_mean"], art["scaler_scale"]):
        vs = per_feature_values[f]
        if not vs:
            drift[f] = {"n": 0, "mean_live": float("nan"), "scaler_mean": mean_, "scaler_scale": scale_, "z": float("nan")}
            continue
        mean_live = float(np.mean(vs))
        z = (mean_live - mean_) / scale_ if scale_ else float("nan")
        drift[f] = {"n": len(vs), "mean_live": mean_live, "scaler_mean": mean_, "scaler_scale": scale_, "z": z}
    return drift


def write_live_status_md(
    stats_by_k: dict[int, dict],
    forecasts_dir: Path,
    path: Path,
    drift: dict | None = None,
) -> Path:
    lines = [
        "# swcast-kp-baseline-v0 – Live-Status",
        "",
        "**Vorläufig – maßgeblich erst bei N = 365 Tagen (PREREGISTRATION §5).**",
        "",
    ]
    n_days = days_since_start(forecasts_dir)
    if n_days is not None:
        lines.append(f"Tage seit Start (Zieltag +1 der ersten gültigen Vorhersage): {n_days}")
    else:
        lines.append("Noch keine gültige Vorhersage seit Live-Start (kein `forecasts/START.md`).")
    lines.append("")

    lines += [
        "| Vorlauftag | n (gepaart) | SWPC fehlt | GFZ-Lücke | BSS swcast | BSS SWPC | ΔBSS [95%-KI] | Einordnung |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for k in DAY_AHEADS:
        s = stats_by_k[k]
        point, lo, hi = s["delta"]
        lines.append(
            f"| +{k} | {s['n']} | {s['n_swpc_missing']} | {s['n_label_gap']} | "
            f"{s['bss_swcast']:.4f} | {s['bss_swpc']:.4f} | {point:+.4f} [{lo:+.4f}, {hi:+.4f}] | {s['classification']} |"
        )
    lines.append("")

    if drift:
        lines += [
            "## Eingangsdrift (nur beschreibend, kein Erfolgskriterium)",
            "",
            "Mittelwert der Tag+1-Hauptmodell-Merkmale über alle Live-Läufe mit "
            "gültigem L1 gegen `scaler_mean`/`scaler_scale` aus dem Training "
            "(PREREGISTRATION §9: rein beobachtend, ändert `swcast-kp-baseline-v0` "
            "nicht). Großes |z| kann z. B. auf eine anders kalibrierte aktive "
            "rtsw-Sonde hindeuten (siehe `l1_source` je Lauf).",
            "",
            "| Merkmal | n | Mittelwert live | scaler_mean | scaler_scale | z |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for f in DRIFT_FEATURES:
            d = drift.get(f)
            if d is None:
                continue
            lines.append(
                f"| `{f}` | {d['n']} | {d['mean_live']:.4f} | {d['scaler_mean']:.4f} | "
                f"{d['scaler_scale']:.4f} | {d['z']:+.4f} |"
            )
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    return path


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def main(nowcast_lookback_days: int = 400) -> Path:
    cfg = load_config()
    model_name = _model_name(cfg)
    artifacts = json.loads(_artifacts_path(model_name).read_text())

    forecasts_dir = _forecasts_dir(cfg)
    archive_dir = _archive_swpc_dir(cfg)
    reports_dir = _reports_dir(cfg)

    forecast_paths = [
        p for p in sorted(forecasts_dir.glob("*/*.json")) if p.name != "START.md"
    ]
    daypre_paths = sorted(archive_dir.glob("*_3-day-solar-geomag-predictions.txt"))

    selected = select_swcast_forecasts(forecast_paths)
    file_run_days: set[date] = set(selected)
    for p in forecast_paths:
        try:
            payload = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        rs = _parse_run_start(payload)
        if rs is not None:
            file_run_days.add(rs.date())

    run_days = build_run_day_universe(forecasts_dir, file_run_days)

    if not run_days:
        logger.warning("No forecast/MISSED files found under %s; nothing to evaluate.", forecasts_dir)

    now = datetime.now(timezone.utc)
    df_nowcast = fetch_nowcast(now - timedelta(days=nowcast_lookback_days), now)
    daily_dict = _daily_dict(df_nowcast)

    rows = build_evaluation_rows(selected, run_days, daypre_paths, daily_dict, artifacts)

    csv_path = write_live_evaluation_csv(rows, reports_dir / "live_evaluation.csv")
    maybe_write_start_md(rows, forecasts_dir)

    stats_rows = rows_since_start(rows, forecasts_dir)
    stats_by_k = {k: compute_k_stats([r for r in stats_rows if r["k"] == k]) for k in DAY_AHEADS}
    drift = compute_input_drift(forecast_paths, artifacts, k=1)
    status_path = write_live_status_md(stats_by_k, forecasts_dir, reports_dir / "live_status.md", drift=drift)

    logger.info("Wrote %s and %s", csv_path, status_path)
    return status_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

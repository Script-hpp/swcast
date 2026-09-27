"""
live_features.py – Merkmale für einen Live-Lauf (PREREGISTRATION.md §7).

build_live_features(run_start) berechnet dieselben Merkmale wie
swcast.training.dataset.build_training_dataset, für genau EINEN Lauf, ohne
Dateiausgabe und ohne freeze.py-Aufruf.

Bekannte Einschränkung (PREREGISTRATION §7): Das Training nutzte GFZ
*definitiv* für Persistenz, Rekurrenz und Klimatologie. Im Live-Betrieb sind
definitive Werte nicht rechtzeitig verfügbar, deshalb wird hier GFZ
*Nowcast* (status=now) verwendet. L1-Sonnenwind kommt in beiden Fällen aus
Echtzeitquellen (Training: OMNI High-Res; Live: SWPC rtsw), wie in §7
spezifiziert.

predict(features, artifacts) berechnet p_storm und kp_max je Vorlauftag
direkt aus den JSON-Modellartefakten (scaler mean/scale, coef, intercept),
ohne sklearn-Objekte zu rekonstruieren.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from swcast.fetch.kp import daily_storm_label, fetch_nowcast, get_persistence_intervals
from swcast.fetch.solarwind import compute_2h_features, fetch_swpc_live

logger = logging.getLogger(__name__)

L1_FEATURE_KEYS = ["bz_gsm", "by_gsm", "speed", "dyn_pressure", "newell"]


class MissingFeatureError(Exception):
    """
    Raised by predict() when a required model feature is NaN (e.g. persistence
    missing because GFZ nowcast failed, or recurrence missing). A NaN input
    must not silently produce p_storm = NaN: the run counts as not produced,
    and per PREREGISTRATION §6 the evaluation substitutes climatology for it.
    """


def build_live_features(run_start: datetime) -> dict:
    """
    Build live-run features for run_start, matching PREREGISTRATION §7.

    Returns
    -------
    dict
      {
        "run_start": run_start,
        "inputs_last_data_time": datetime | None,
            # latest data point actually consumed: the end of the latest
            # used GFZ-nowcast persistence interval, and, if l1_valid, the
            # latest valid L1 minute in the 2h window (whichever is later).
        "l1_valid": bool,
        "l1_fallback_reason": str | None,
            # set whenever l1_valid is False: the exception type and message
            # from fetching/computing L1 (SWPC rtsw down, timeout, malformed
            # JSON, or FallbackError for <60/120 valid minutes).
        "days": {
          1: {"target_date": date, "persistence": float, "recurrence": float,
              "climatology": float, "l1_bz_gsm": float, "l1_by_gsm": float,
              "l1_speed": float, "l1_dyn_pressure": float, "l1_newell": float},
          2: {...}, 3: {...},
        },
      }

    Any failure fetching or computing L1 (SWPC rtsw API down, timeout,
    malformed response, or FallbackError for fewer than 60/120 valid
    minutes) is treated the same: l1_valid is False, all l1_* values are NaN
    for every day, and l1_fallback_reason records why.
    """
    run_start = pd.Timestamp(run_start)
    if run_start.tzinfo is None:
        raise ValueError("build_live_features: run_start must be timezone-aware (UTC)")

    current_date = run_start.date()

    # --- GFZ nowcast: persistence, recurrence, climatology ---------------
    fetch_start = run_start - timedelta(days=366)
    df_kp = fetch_nowcast(fetch_start, run_start)
    kp_interval_dict = df_kp.set_index("time")["kp"].to_dict()

    df_daily = daily_storm_label(df_kp)
    daily_kp_dict = df_daily.set_index("date").to_dict("index")

    # Persistence: max Kp over the last 8 complete 3h intervals before run_start,
    # excluding the ongoing interval. inputs_last_data_time for Kp is the END
    # of the latest of these intervals that actually had data — not the raw
    # max timestamp in the fetched frame, which could include a same-day
    # in-progress interval with a partial/unconfirmed nowcast value.
    persistence_intervals = get_persistence_intervals(run_start)
    persistence_kps = []
    last_kp_time = None
    for dt_start in persistence_intervals:
        val = kp_interval_dict.get(pd.Timestamp(dt_start), np.nan)
        if pd.notna(val):
            persistence_kps.append(val)
            last_kp_time = dt_start + timedelta(hours=3)
    persistence = max(persistence_kps) if persistence_kps else np.nan

    # Climatology: fraction of storm days (Kp >= 5.0) in the 365 days up to
    # and including the last complete UTC day before run_start.
    clim_storms = 0
    clim_valid_days = 0
    for i in range(1, 366):
        d_prev = current_date - timedelta(days=i)
        day_info = daily_kp_dict.get(d_prev)
        if day_info and pd.notna(day_info["storm_label"]):
            clim_valid_days += 1
            if day_info["storm_label"]:
                clim_storms += 1
    climatology = clim_storms / clim_valid_days if clim_valid_days > 0 else np.nan

    # --- SWPC rtsw: L1 solar wind ------------------------------------------
    # Any failure here (API down, timeout, empty/malformed JSON, or the
    # <60/120-valid-minutes FallbackError) must fall back to the fallback
    # model per PREREGISTRATION §7 ("irgendein L1-Merkmal fehlt"), not crash
    # the whole run — fetch_swpc_live() is therefore inside this try too.
    l1_features = None
    last_l1_time = None
    l1_fallback_reason = None
    try:
        df_l1 = fetch_swpc_live()
        l1_features = compute_2h_features(df_l1, run_start)
        window_start = run_start - timedelta(hours=2)
        mask = (df_l1["time"] >= window_start) & (df_l1["time"] < run_start)
        df_win = df_l1[mask].dropna(subset=["by_gsm", "bz_gsm", "speed", "density"])
        if not df_win.empty:
            last_l1_time = df_win["time"].max().to_pydatetime()
    except Exception as exc:
        l1_fallback_reason = f"{type(exc).__name__}: {exc}"
        logger.warning("L1 fallback for run_start=%s: %s", run_start, l1_fallback_reason)

    l1_valid = l1_features is not None

    candidate_times = [t for t in (last_kp_time, last_l1_time) if t is not None]
    inputs_last_data_time = max(candidate_times) if candidate_times else None

    days: dict[int, dict] = {}
    for i in (1, 2, 3):
        target_date = current_date + timedelta(days=i)

        # Recurrence: max Kp exactly 27 days before the target day.
        recur_date = target_date - timedelta(days=27)
        recur_info = daily_kp_dict.get(recur_date)
        recurrence = recur_info["max_kp"] if recur_info else np.nan

        day_rec = {
            "target_date": target_date,
            "persistence": persistence,
            "recurrence": recurrence,
            "climatology": climatology,
        }
        for k in L1_FEATURE_KEYS:
            day_rec[f"l1_{k}"] = l1_features[k] if l1_valid else np.nan
        days[i] = day_rec

    return {
        "run_start": run_start,
        "inputs_last_data_time": inputs_last_data_time,
        "l1_valid": l1_valid,
        "l1_fallback_reason": l1_fallback_reason,
        "days": days,
    }


def _standardize(x: np.ndarray, mean: list[float], scale: list[float]) -> np.ndarray:
    return (x - np.array(mean)) / np.array(scale)


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + np.exp(-z))


def _linear_score(x: np.ndarray, art: dict) -> float:
    x_s = _standardize(x, art["scaler_mean"], art["scaler_scale"])
    return float(np.dot(x_s, art["coef"]) + art["intercept"])


def predict(features: dict, artifacts: dict) -> dict:
    """
    Predict p_storm and kp_max per day-ahead (1, 2, 3) directly from the JSON
    model artifacts. Uses the *_main model when features["l1_valid"] is True,
    otherwise the *_fallback model (persistence/recurrence/climatology only),
    per the PREREGISTRATION §7 fallback rule.

    Parameters
    ----------
    features : dict
        As returned by build_live_features(...).
    artifacts : dict
        Parsed model_artifacts.json (must contain artifacts["models"][str(day)]
        with keys p_storm_main, p_storm_fallback, kp_max_main, kp_max_fallback,
        each holding scaler_mean, scaler_scale, coef, intercept, features).

    Returns
    -------
    dict
        {day: {"p_storm": float, "kp_max": float}} for day in (1, 2, 3).

    Raises
    ------
    MissingFeatureError
        If a feature required by the selected model is NaN for some day.
    """
    l1_valid = features["l1_valid"]
    suffix = "main" if l1_valid else "fallback"

    results = {}
    for day, day_feats in features["days"].items():
        models = artifacts["models"][str(day)]
        p_art = models[f"p_storm_{suffix}"]
        k_art = models[f"kp_max_{suffix}"]

        needed = sorted(set(p_art["features"]) | set(k_art["features"]))
        missing = [f for f in needed if not np.isfinite(day_feats.get(f, np.nan))]
        if missing:
            raise MissingFeatureError(
                f"day+{day}: required feature(s) NaN/missing: {missing}"
            )

        x_p = np.array([day_feats[f] for f in p_art["features"]], dtype=float)
        x_k = np.array([day_feats[f] for f in k_art["features"]], dtype=float)

        results[day] = {
            "p_storm": _sigmoid(_linear_score(x_p, p_art)),
            "kp_max": _linear_score(x_k, k_art),
        }
    return results

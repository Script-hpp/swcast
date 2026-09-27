import math
from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from swcast.fetch.solarwind import FallbackError
from swcast.live_features import build_live_features, predict
from swcast.training.dataset import build_training_dataset
from swcast.training.train import train_final_model

FEATURES_MAIN = [
    "persistence", "recurrence", "climatology",
    "l1_bz_gsm", "l1_by_gsm", "l1_speed", "l1_dyn_pressure", "l1_newell",
]
FEATURES_FALLBACK = ["persistence", "recurrence", "climatology"]


def _eq_or_both_nan(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


# ---------------------------------------------------------------------------
# predict(): must exactly reproduce sklearn (tolerance 1e-9)
# ---------------------------------------------------------------------------

def _synthetic_df(n=200, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "persistence": rng.uniform(0, 9, n),
        "recurrence": rng.uniform(0, 9, n),
        "climatology": rng.uniform(0, 1, n),
        "l1_bz_gsm": rng.uniform(-20, 20, n),
        "l1_by_gsm": rng.uniform(-20, 20, n),
        "l1_speed": rng.uniform(250, 800, n),
        "l1_dyn_pressure": rng.uniform(0, 20, n),
        "l1_newell": rng.uniform(0, 5000, n),
    })
    df["target_storm"] = (df["persistence"] - 0.3 * df["l1_bz_gsm"] + rng.normal(0, 2, n)) > 5
    df["target_kp_max"] = df["persistence"] * 0.5 + df["l1_speed"] * 0.001 + rng.normal(0, 0.5, n)
    return df


def test_predict_reproduces_sklearn_exactly_main_model():
    df = _synthetic_df()
    art_p = train_final_model(df, FEATURES_MAIN, "target_storm", True, 1.0)
    art_k = train_final_model(df, FEATURES_MAIN, "target_kp_max", False, 1.0)

    artifacts = {"models": {"1": {
        "p_storm_main": art_p, "p_storm_fallback": art_p,
        "kp_max_main": art_k, "kp_max_fallback": art_k,
    }}}

    scaler = StandardScaler().fit(df[FEATURES_MAIN].values)
    X_s = scaler.transform(df[FEATURES_MAIN].values)
    logreg = LogisticRegression(C=1.0, solver="lbfgs", random_state=42, max_iter=1000)
    logreg.fit(X_s, df["target_storm"].astype(int).values)
    ridge = Ridge(alpha=1.0, solver="svd", random_state=42)
    ridge.fit(X_s, df["target_kp_max"].values)

    for row_idx in [0, 5, 42, 199]:
        row = df.iloc[row_idx]
        day_feats = {f: float(row[f]) for f in FEATURES_MAIN}
        day_feats["target_date"] = None
        features = {"l1_valid": True, "days": {1: day_feats}}
        result = predict(features, artifacts)[1]

        expected_p = logreg.predict_proba(X_s[row_idx:row_idx + 1])[0, 1]
        expected_k = ridge.predict(X_s[row_idx:row_idx + 1])[0]

        assert abs(result["p_storm"] - expected_p) < 1e-9
        assert abs(result["kp_max"] - expected_k) < 1e-9


def test_predict_uses_fallback_model_when_l1_invalid():
    df = _synthetic_df()
    art_p_fb = train_final_model(df, FEATURES_FALLBACK, "target_storm", True, 0.1)
    art_k_fb = train_final_model(df, FEATURES_FALLBACK, "target_kp_max", False, 0.1)
    # main artifacts present but must NOT be used
    art_p_main = train_final_model(df, FEATURES_MAIN, "target_storm", True, 10.0)
    art_k_main = train_final_model(df, FEATURES_MAIN, "target_kp_max", False, 10.0)

    artifacts = {"models": {"2": {
        "p_storm_main": art_p_main, "p_storm_fallback": art_p_fb,
        "kp_max_main": art_k_main, "kp_max_fallback": art_k_fb,
    }}}

    scaler = StandardScaler().fit(df[FEATURES_FALLBACK].values)
    X_s = scaler.transform(df[FEATURES_FALLBACK].values)
    logreg = LogisticRegression(C=0.1, solver="lbfgs", random_state=42, max_iter=1000)
    logreg.fit(X_s, df["target_storm"].astype(int).values)
    ridge = Ridge(alpha=0.1, solver="svd", random_state=42)
    ridge.fit(X_s, df["target_kp_max"].values)

    row = df.iloc[7]
    day_feats = {f: float(row[f]) for f in FEATURES_FALLBACK}
    for k in ["l1_bz_gsm", "l1_by_gsm", "l1_speed", "l1_dyn_pressure", "l1_newell"]:
        day_feats[k] = float("nan")
    features = {"l1_valid": False, "days": {2: day_feats}}
    result = predict(features, artifacts)[2]

    expected_p = logreg.predict_proba(X_s[7:8])[0, 1]
    expected_k = ridge.predict(X_s[7:8])[0]
    assert abs(result["p_storm"] - expected_p) < 1e-9
    assert abs(result["kp_max"] - expected_k) < 1e-9


# ---------------------------------------------------------------------------
# build_live_features(): feature parity with build_training_dataset
# ---------------------------------------------------------------------------

def _make_shared_kp_df():
    start_time = datetime(2009, 1, 1, tzinfo=timezone.utc)
    times = pd.date_range(
        start_time, end=datetime(2010, 12, 31, 23, 59, tzinfo=timezone.utc),
        freq="3h", inclusive="left",
    )
    rng = np.random.default_rng(42)
    df_kp = pd.DataFrame({
        "time": times,
        "kp": rng.uniform(0, 4, len(times)),
        "is_gap": [False] * len(times),
    })
    plant_time = datetime(2010, 1, 1, 18, 0, tzinfo=timezone.utc)
    df_kp.loc[df_kp["time"] == plant_time, "kp"] = 9.0
    return df_kp


@patch("swcast.live_features.fetch_swpc_live")
@patch("swcast.live_features.compute_2h_features")
@patch("swcast.live_features.fetch_nowcast")
@patch("swcast.training.dataset.fetch_training_data")
@patch("swcast.training.dataset.fetch_omni_historical")
@patch("swcast.training.dataset.compute_2h_features")
def test_feature_parity_with_training_dataset(
    mock_train_compute2h, mock_train_omni, mock_train_kp,
    mock_live_nowcast, mock_live_compute2h, mock_live_swpc,
):
    df_kp = _make_shared_kp_df()
    mock_train_kp.return_value = df_kp
    mock_live_nowcast.return_value = df_kp

    df_omni = pd.DataFrame(columns=["time", "bx", "by_gsm", "bz_gsm", "speed", "density"])
    mock_train_omni.return_value = df_omni
    mock_live_swpc.return_value = pd.DataFrame(
        columns=["time", "by_gsm", "bz_gsm", "speed", "density"]
    )

    l1_result = {
        "bz_gsm": -5.0, "by_gsm": 1.0, "speed": 400.0,
        "dyn_pressure": 2.0, "newell": 3000.0, "valid_minutes": 120,
    }
    mock_train_compute2h.return_value = l1_result
    mock_live_compute2h.return_value = l1_result

    df_train = build_training_dataset(2010, 2010)

    run_start = datetime(2010, 1, 1, 22, 30, tzinfo=timezone.utc)
    live = build_live_features(run_start)

    assert live["l1_valid"] is True

    day_runs = df_train[df_train["run_date"] == pd.Timestamp("2010-01-01").date()]
    for i in (1, 2, 3):
        train_row = day_runs[day_runs["target_day_ahead"] == i].iloc[0]
        live_day = live["days"][i]

        assert _eq_or_both_nan(live_day["persistence"], train_row["persistence"])
        assert _eq_or_both_nan(live_day["climatology"], train_row["climatology"])
        assert _eq_or_both_nan(live_day["recurrence"], train_row["recurrence"])
        assert live_day["target_date"] == train_row["target_date"]
        for k in ["bz_gsm", "by_gsm", "speed", "dyn_pressure", "newell"]:
            assert _eq_or_both_nan(live_day[f"l1_{k}"], train_row[f"l1_{k}"])

@patch("swcast.live_features.fetch_swpc_live")
@patch("swcast.live_features.compute_2h_features")
@patch("swcast.live_features.fetch_nowcast")
def test_build_live_features_l1_fallback(mock_nowcast, mock_compute2h, mock_swpc):
    df_kp = _make_shared_kp_df()
    mock_nowcast.return_value = df_kp
    mock_swpc.return_value = pd.DataFrame(columns=["time", "by_gsm", "bz_gsm", "speed", "density"])
    mock_compute2h.side_effect = FallbackError("only 10/120 valid minutes")

    run_start = datetime(2010, 1, 1, 22, 30, tzinfo=timezone.utc)
    live = build_live_features(run_start)

    assert live["l1_valid"] is False
    for i in (1, 2, 3):
        day = live["days"][i]
        for k in ["l1_bz_gsm", "l1_by_gsm", "l1_speed", "l1_dyn_pressure", "l1_newell"]:
            assert math.isnan(day[k])
        # persistence/climatology/recurrence must still be computed from GFZ nowcast
        assert not math.isnan(day["persistence"])
        assert not math.isnan(day["climatology"])

from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
import pytest

from swcast.fetch.solarwind import compute_2h_features, FallbackError

def test_compute_2h_features_success():
    run_start = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
    # create 120 minutes of valid data
    times = pd.date_range(run_start - timedelta(hours=2), periods=120, freq="1min", tz=timezone.utc)
    
    df = pd.DataFrame({
        "time": times,
        "bx": np.ones(120),
        "by_gsm": np.ones(120) * 3.0,
        "bz_gsm": np.ones(120) * 4.0, # bt = 5, theta_c = atan2(3, 4)
        "speed": np.ones(120) * 400.0,
        "density": np.ones(120) * 5.0
    })
    
    features = compute_2h_features(df, run_start)
    assert features["valid_minutes"] == 120
    assert features["bz_gsm"] == 4.0
    assert features["by_gsm"] == 3.0
    assert features["speed"] == 400.0
    assert features["dyn_pressure"] == 5.0 * (400.0 ** 2)
    
    # check newell
    # theta_c = atan2(3, 4) ~ 0.6435 rad
    # sin(theta_c / 2) ~ 0.3162
    # bt = 5
    # speed = 400
    expected_newell = (400 ** (4/3)) * (5 ** (2/3)) * (np.sin(np.arctan2(3, 4) / 2) ** (8/3))
    assert np.isclose(features["newell"], expected_newell)

def test_compute_2h_features_fallback():
    run_start = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
    times = pd.date_range(run_start - timedelta(hours=2), periods=120, freq="1min", tz=timezone.utc)
    
    # only 59 valid minutes
    bz = np.ones(120) * 4.0
    bz[59:] = np.nan
    
    df = pd.DataFrame({
        "time": times,
        "bx": np.ones(120),
        "by_gsm": np.ones(120) * 3.0,
        "bz_gsm": bz,
        "speed": np.ones(120) * 400.0,
        "density": np.ones(120) * 5.0
    })
    
    with pytest.raises(FallbackError, match="Only 59/120 valid minutes"):
        compute_2h_features(df, run_start)

def test_compute_2h_features_exact_60():
    run_start = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
    times = pd.date_range(run_start - timedelta(hours=2), periods=120, freq="1min", tz=timezone.utc)
    
    # exactly 60 valid minutes
    bz = np.ones(120) * 4.0
    bz[60:] = np.nan
    
    df = pd.DataFrame({
        "time": times,
        "bx": np.ones(120),
        "by_gsm": np.ones(120) * 3.0,
        "bz_gsm": bz,
        "speed": np.ones(120) * 400.0,
        "density": np.ones(120) * 5.0
    })
    
    features = compute_2h_features(df, run_start)
    assert features["valid_minutes"] == 60

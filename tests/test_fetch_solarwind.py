import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timezone, timedelta
import json
from unittest.mock import patch

from swcast.fetch.solarwind import compute_2h_features, FallbackError, fetch_swpc_live

def test_fetch_swpc_live_filtering():
    # Mock responses
    mag_data = [
        {"time_tag": "2026-09-27T12:00:00", "active": True, "source": "SOLAR1", "bx_gsm": 1.0, "by_gsm": 2.0, "bz_gsm": 3.0, "overall_quality": 0, "max_data_flag": 0},
        {"time_tag": "2026-09-27T12:00:00", "active": False, "source": "ACE", "bx_gsm": 9.0, "by_gsm": 9.0, "bz_gsm": 9.0, "overall_quality": 1, "max_data_flag": 1},
        {"time_tag": "2026-09-27T12:01:00", "active": True, "source": "SOLAR1", "bx_gsm": 1.1, "by_gsm": 2.1, "bz_gsm": 3.1, "overall_quality": 0, "max_data_flag": 0}
    ]
    
    wind_data = [
        {"time_tag": "2026-09-27T12:00:00", "active": True, "source": "SOLAR1", "proton_speed": 400.0, "proton_density": 5.0, "overall_quality": 0, "max_data_flag": 0},
        {"time_tag": "2026-09-27T12:00:00", "active": False, "source": "ACE", "proton_speed": 999.0, "proton_density": 99.0, "overall_quality": 1, "max_data_flag": 1},
        {"time_tag": "2026-09-27T12:01:00", "active": True, "source": "SOLAR1", "proton_speed": 401.0, "proton_density": 5.1, "overall_quality": 0, "max_data_flag": 0}
    ]
    
    class MockResponse:
        def __init__(self, json_data):
            self._json = json_data
        def json(self): return self._json
        def raise_for_status(self): pass
        
    def mock_get(url):
        if "mag" in url: return MockResponse(mag_data)
        if "wind" in url: return MockResponse(wind_data)
        return MockResponse([])

    with patch('requests.get', side_effect=mock_get):
        df = fetch_swpc_live()
        
    assert len(df) == 2
    assert "source" in df.columns
    assert df.iloc[0]["source"] == "SOLAR1"
    assert df.iloc[0]["bx"] == 1.0
    assert df.iloc[0]["speed"] == 400.0

def test_compute_2h_features_success():
    run_start = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
    times = pd.date_range(run_start - timedelta(hours=2), periods=120, freq="1min", tz=timezone.utc)
    
    df = pd.DataFrame({
        "time": times,
        "bx": np.ones(120),
        "by_gsm": np.ones(120) * 3.0,
        "bz_gsm": np.ones(120) * 4.0,
        "speed": np.ones(120) * 400.0,
        "density": np.ones(120) * 5.0
    })
    
    features = compute_2h_features(df, run_start)
    assert features["valid_minutes"] == 120
    assert features["bz_gsm"] == 4.0
    
def test_compute_2h_features_fallback():
    run_start = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
    times = pd.date_range(run_start - timedelta(hours=2), periods=120, freq="1min", tz=timezone.utc)
    
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

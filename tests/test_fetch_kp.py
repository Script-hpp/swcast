from datetime import datetime, timezone
import pandas as pd
import numpy as np

from swcast.fetch.kp import daily_storm_label, get_kp_dataframe

def test_daily_storm_label():
    times = pd.date_range("2026-01-01", "2026-01-02", freq="3h", tz=timezone.utc, inclusive="left")
    # Jan 1 has max Kp = 4.667 (5-) -> False
    # Jan 2 has max Kp = 5.0 -> True
    kps = [
        3.0, 3.333, 4.0, 4.667, 2.0, 1.0, 1.0, 1.0, # Jan 1
        1.0, 2.0, 3.0, 5.0, 4.667, 3.0, 2.0, 1.0  # Jan 2
    ]
    df = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=16, freq="3h", tz=timezone.utc),
        "kp": kps,
        "is_gap": [False] * 16
    })
    
    daily = daily_storm_label(df)
    
    assert len(daily) == 2
    assert daily.iloc[0]["date"].strftime("%Y-%m-%d") == "2026-01-01"
    assert not daily.iloc[0]["storm_label"]
    assert not daily.iloc[0]["has_gap"]
    
    assert daily.iloc[1]["date"].strftime("%Y-%m-%d") == "2026-01-02"
    assert daily.iloc[1]["storm_label"]
    
def test_daily_storm_label_with_gaps():
    # Introduce a gap
    df = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=8, freq="3h", tz=timezone.utc),
        "kp": [3.0, np.nan, 4.0, 4.667, 2.0, 1.0, 1.0, 1.0],
        "is_gap": [False, True, False, False, False, False, False, False]
    })
    
    daily = daily_storm_label(df)
    assert len(daily) == 1
    assert daily.iloc[0]["has_gap"]
    assert daily.iloc[0]["gap_count"] == 1
    assert not daily.iloc[0]["storm_label"]

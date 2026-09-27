from datetime import datetime, timezone
import pandas as pd
import numpy as np
import math

from swcast.fetch.kp import daily_storm_label, get_kp_dataframe

def test_daily_storm_label():
    times = pd.date_range("2026-01-01", "2026-01-02", freq="3h", tz=timezone.utc, inclusive="left")
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
    assert daily.iloc[0]["storm_label"] == False
    assert not daily.iloc[0]["has_gap"]
    
    assert daily.iloc[1]["date"].strftime("%Y-%m-%d") == "2026-01-02"
    assert daily.iloc[1]["storm_label"] == True
    
def test_daily_storm_label_with_gaps():
    # Gap but max < 5 -> unknown (NaN)
    df1 = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=8, freq="3h", tz=timezone.utc),
        "kp": [3.0, np.nan, 4.0, 4.667, 2.0, 1.0, 1.0, 1.0],
        "is_gap": [False, True, False, False, False, False, False, False]
    })
    daily1 = daily_storm_label(df1)
    assert daily1.iloc[0]["has_gap"]
    assert math.isnan(daily1.iloc[0]["storm_label"])
    
    # Gap but max >= 5 -> True
    df2 = pd.DataFrame({
        "time": pd.date_range("2026-01-02", periods=8, freq="3h", tz=timezone.utc),
        "kp": [3.0, np.nan, 5.0, 4.667, 2.0, 1.0, 1.0, 1.0],
        "is_gap": [False, True, False, False, False, False, False, False]
    })
    daily2 = daily_storm_label(df2)
    assert daily2.iloc[0]["has_gap"]
    assert daily2.iloc[0]["storm_label"] == True

from swcast.fetch.kp import get_persistence_intervals

def test_get_persistence_intervals():
    run_time = datetime(2026, 9, 27, 22, 30, tzinfo=timezone.utc)
    intervals = get_persistence_intervals(run_time)
    assert len(intervals) == 8
    assert intervals[-1] == datetime(2026, 9, 27, 18, 0, tzinfo=timezone.utc)
    assert intervals[0] == datetime(2026, 9, 26, 21, 0, tzinfo=timezone.utc)
    
    run_time = datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)
    intervals = get_persistence_intervals(run_time)
    assert intervals[-1] == datetime(2026, 9, 27, 21, 0, tzinfo=timezone.utc)

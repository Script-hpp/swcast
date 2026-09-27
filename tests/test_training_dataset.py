import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from swcast.training.dataset import build_training_dataset
from swcast.fetch.solarwind import FallbackError

@patch('swcast.training.dataset.fetch_training_data')
@patch('swcast.training.dataset.fetch_omni_historical')
@patch('swcast.training.dataset.compute_2h_features')
def test_dataset_no_leakage(mock_compute_2h, mock_fetch_omni, mock_fetch_kp):
    # Mock Kp data: 1 year before 2010 to 2010
    start_time = datetime(2009, 1, 1, tzinfo=timezone.utc)
    times = pd.date_range(start_time, end=datetime(2010, 12, 31, 23, 59, tzinfo=timezone.utc), freq='3h', inclusive='left')
    df_kp = pd.DataFrame({"time": times, "kp": np.random.uniform(0, 4, len(times)), "is_gap": [False] * len(times)})
    
    # Let's plant a specific Kp value to check persistence
    # We are testing run_date = 2010-01-01
    # Run time is 2010-01-01 22:30
    # Intervals to check: D-1 21:00 to D 18:00
    # That is 2009-12-31 21:00 to 2010-01-01 18:00
    plant_time = datetime(2010, 1, 1, 18, 0, tzinfo=timezone.utc)
    df_kp.loc[df_kp['time'] == plant_time, 'kp'] = 9.0 # Plant persistence maximum
    
    # We plant a storm on 2010-01-03 to check day+2 targets
    target_time = datetime(2010, 1, 3, 3, 0, tzinfo=timezone.utc)
    df_kp.loc[df_kp['time'] == target_time, 'kp'] = 8.0
    
    mock_fetch_kp.return_value = df_kp
    
    df_omni = pd.DataFrame(columns=["time", "bx", "by_gsm", "bz_gsm", "speed", "density"])
    mock_fetch_omni.return_value = df_omni
    
    mock_compute_2h.return_value = {
        "bz_gsm": -5.0, "by_gsm": 1.0, "speed": 400.0, "dyn_pressure": 2.0, "newell": 3000.0, "valid_minutes": 120
    }
    
    df_train = build_training_dataset(2010, 2010)
    
    # check run_date 2010-01-01
    day_runs = df_train[df_train['run_date'] == pd.Timestamp("2010-01-01").date()]
    assert len(day_runs) == 3
    
    # Persistence should be 9.0
    assert day_runs.iloc[0]['persistence'] == 9.0
    
    # Target day + 2 should have max_kp 8.0 and storm_label True
    day2 = day_runs[day_runs['target_day_ahead'] == 2].iloc[0]
    assert day2['target_kp_max'] == 8.0
    assert day2['target_storm'] == True
    
    # Verify mock_compute_2h was called with run_datetime = 2010-01-01 22:30
    args, _ = mock_compute_2h.call_args_list[0]
    assert args[1] == datetime(2010, 1, 1, 22, 30, tzinfo=timezone.utc)

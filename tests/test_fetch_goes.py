import pandas as pd
import xarray as xr
import numpy as np
from swcast.fetch.goes import build_gap_series

def test_build_gap_series_combined_mask():
    start_ts = "2024-01-01T00:00:00"
    end_ts = "2024-01-01T00:05:00"
    times = pd.date_range(start_ts, end_ts, freq="1min", inclusive="left")
    
    # Sat 18
    # 0: good
    # 1: eclipse (invalid)
    # 2: bad_data (invalid)
    # 3: eclipse + bad_data (invalid)
    # 4: interpolated (valid)
    flags_18 = [0, 1, 2, 3, 4]
    flux_18 = [1e-6, 1e-6, 1e-6, 1e-6, 1e-6]
    ds_18 = xr.Dataset(
        {"xrsb_flag": (["time"], flags_18), "xrsb_flux": (["time"], flux_18)},
        coords={"time": times}
    )
    
    # Sat 19
    # For minute 0: both valid -> gap = False
    # For minute 1: G18 eclipse, G19 valid -> gap = False
    # For minute 2: G18 bad, G19 bad -> gap = True
    # For minute 3: G18 eclipse+bad, G19 missing (NaN) -> gap = True
    # For minute 4: G18 interpolated (valid), G19 NaN -> gap = False
    flags_19 = [0, 0, 2, 0, 0]
    flux_19 = [1e-6, 1e-6, 1e-6, np.nan, np.nan]
    ds_19 = xr.Dataset(
        {"xrsb_flag": (["time"], flags_19), "xrsb_flux": (["time"], flux_19)},
        coords={"time": times}
    )
    
    ds_dict = {18: ds_18, 19: ds_19}
    
    gap_series = build_gap_series(ds_dict, start_ts, end_ts)
    
    # Expected: False, False, True, True, False
    assert list(gap_series) == [False, False, True, True, False]
    
def test_build_gap_series_missing_rows():
    start_ts = "2024-01-01T00:00:00"
    end_ts = "2024-01-01T00:05:00"
    # Provide only 1 row of data for minute 0, meaning minutes 1-4 are missing completely from dataset
    times = pd.date_range(start_ts, periods=1, freq="1min")
    ds_18 = xr.Dataset(
        {"xrsb_flag": (["time"], [0]), "xrsb_flux": (["time"], [1e-6])},
        coords={"time": times}
    )
    ds_dict = {18: ds_18}
    gap_series = build_gap_series(ds_dict, start_ts, end_ts)
    
    # First minute is valid, rest are missing -> True
    assert list(gap_series) == [False, True, True, True, True]


import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from swcast.fetch.kp import fetch_training_data, daily_storm_label
from swcast.fetch.solarwind import fetch_omni_historical, compute_2h_features, FallbackError

logger = logging.getLogger(__name__)

def build_training_dataset(start_year: int = 2005, end_year: int = 2025) -> pd.DataFrame:
    """
    Builds the training dataset for the specified years according to PREREGISTRATION.md §7.
    Returns a dataframe where each row is a simulation run at D 22:30 UTC predicting D+i.
    """
    df_kp = fetch_training_data(start_year - 1, end_year) # -1 for climatology and persistence
    df_daily_kp = daily_storm_label(df_kp)
    
    # Pre-compute daily metrics for fast lookup
    daily_kp_dict = df_daily_kp.set_index("date").to_dict("index")
    
    # We also need interval lookups for persistence
    # df_kp has 'time' as the start of the interval
    kp_interval_dict = df_kp.set_index("time")["kp"].to_dict()
    
    records = []
    
    # We might need to load OMNI year by year to save memory
    omni_cache = {}
    
    start_date = pd.Timestamp(f"{start_year}-01-01", tz="UTC").date()
    end_date = pd.Timestamp(f"{end_year}-12-31", tz="UTC").date()
    
    current_date = start_date
    while current_date <= end_date:
        run_datetime = datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=22, minutes=30)
        
        # 1. Persistence: max Kp over last 8 complete 3h intervals before 22:30
        # Intervals: D-1 21:00 to D 18:00 (since 18:00-21:00 ends at 21:00)
        persistence_kps = []
        for i in range(8):
            # Interval starts
            # D 18:00 is the latest start
            dt_start = datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=18) - timedelta(hours=3*i)
            # The API returns pd.Timestamp in UTC
            ts = pd.Timestamp(dt_start)
            val = kp_interval_dict.get(ts, np.nan)
            if pd.notna(val):
                persistence_kps.append(val)
                
        if len(persistence_kps) > 0:
            persistence = max(persistence_kps)
        else:
            persistence = np.nan
            
        # 2. Climatology: fraction of storm days (Kp >= 5.0) in the 365 days up to and including D-1
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
        
        # 3. L1 Features: 2h mean 20:30-22:30 from OMNI
        # Fetch OMNI if needed
        yr = current_date.year
        if yr not in omni_cache:
            omni_cache[yr] = fetch_omni_historical(yr)
            # clear previous year to save memory
            if yr - 1 in omni_cache:
                del omni_cache[yr - 1]
                
        df_omni = omni_cache[yr]
        
        l1_features = None
        try:
            l1_features = compute_2h_features(df_omni, run_datetime)
        except FallbackError:
            pass # L1 features remain None
            
        # Targets for D+1, D+2, D+3
        for i in range(1, 4):
            target_date = current_date + timedelta(days=i)
            
            target_info = daily_kp_dict.get(target_date)
            
            target_kp_max = np.nan
            target_storm = np.nan
            if target_info:
                target_kp_max = target_info["max_kp"]
                target_storm = target_info["storm_label"]
                
            # Drop if NaN label
            if pd.isna(target_storm):
                continue
                
            # Recurrence: max Kp on (target_day - 27)
            recur_date = target_date - timedelta(days=27)
            recur_info = daily_kp_dict.get(recur_date)
            recurrence = np.nan
            if recur_info:
                recurrence = recur_info["max_kp"]
                
            rec = {
                "run_date": current_date,
                "target_date": target_date,
                "target_day_ahead": i,
                "persistence": persistence,
                "recurrence": recurrence,
                "climatology": climatology,
                "target_kp_max": target_kp_max,
                "target_storm": target_storm
            }
            
            if l1_features:
                for k, v in l1_features.items():
                    if k != "valid_minutes":
                        rec[f"l1_{k}"] = v
                rec["l1_valid"] = True
            else:
                # Fill with NaNs
                for k in ["bz_gsm", "by_gsm", "speed", "dyn_pressure", "newell"]:
                    rec[f"l1_{k}"] = np.nan
                rec["l1_valid"] = False
                
            records.append(rec)
            
        current_date += timedelta(days=1)
        
    return pd.DataFrame(records)

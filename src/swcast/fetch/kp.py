import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from swcast.config import load_config
from swcast.net import get_with_retry

logger = logging.getLogger(__name__)

from datetime import timedelta

def get_persistence_intervals(run_time: datetime) -> list[datetime]:
    """
    Returns the start times of the 8 complete 3h intervals immediately before run_time.
    For run_time = D 22:30 UTC, returns intervals starting from D-1 21:00 to D 18:00.
    This strictly excludes the ongoing interval (e.g. 21:00 to 00:00).
    """
    current_interval_start = run_time.replace(minute=0, second=0, microsecond=0)
    current_interval_start -= timedelta(hours=current_interval_start.hour % 3)
    
    if current_interval_start + timedelta(hours=3) <= run_time:
        latest_complete_start = current_interval_start
    else:
        latest_complete_start = current_interval_start - timedelta(hours=3)
        
    intervals = []
    for i in range(8):
        intervals.append(latest_complete_start - timedelta(hours=3*i))
        
    return sorted(intervals)

GFZ_KP_URL = "https://kp.gfz.de/app/json/"

def fetch_kp_raw(start: datetime, end: datetime, status: str = "def", use_cache: bool = True) -> dict:
    """Fetch raw Kp JSON from GFZ API, with optional caching."""
    cfg = load_config()
    data_dir = cfg["data_dir"]
    cache_dir = data_dir / "cache" / "kp"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    cache_file = cache_dir / f"kp_{status}_{start_str.replace(':', '')}_{end_str.replace(':', '')}.json"
    
    if use_cache and cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
            
    url = f"{GFZ_KP_URL}?start={start_str}&end={end_str}&index=Kp&status={status}"
    logger.info(f"Fetching Kp from {url}")
    resp = get_with_retry(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    
    if use_cache:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
            
    return data

def get_kp_dataframe(start: datetime, end: datetime, status: str = "def", use_cache: bool = True) -> pd.DataFrame:
    """Get Kp data as a pandas DataFrame on a complete 3-hourly grid.

    `start`/`end` are normalized to tz-aware pandas Timestamps (a plain
    `datetime.datetime` has no `.floor()`, which crashed every live run:
    forecast.main passes `datetime.now(timezone.utc)` straight through to
    here via fetch_nowcast). A naive datetime is rejected outright rather
    than silently assumed to be UTC.
    """
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("get_kp_dataframe: start and end must be timezone-aware (UTC)")

    data = fetch_kp_raw(start, end, status=status, use_cache=use_cache)
    
    if not data.get("datetime"):
        df_api = pd.DataFrame(columns=["time", "kp"])
    else:
        # Convert Kp values to numeric, coercing errors (like 'pre' or nulls) to NaN
        kp_vals = pd.to_numeric(data["Kp"], errors='coerce')
        df_api = pd.DataFrame({
            "time": pd.to_datetime(data["datetime"], utc=True),
            "kp": kp_vals
        })
        # If there are negative values indicating missing, replace with NaN
        df_api.loc[df_api["kp"] < 0, "kp"] = float("nan")
    
    grid_start = start.floor("3h")
    grid_end = end.floor("3h")
    full_grid = pd.date_range(start=grid_start, end=grid_end, freq="3h", tz=timezone.utc)
    
    df_grid = pd.DataFrame({"time": full_grid})
    
    if not df_api.empty:
        df = pd.merge(df_grid, df_api, on="time", how="left")
    else:
        df = df_grid.copy()
        df["kp"] = float("nan")
        
    df["is_gap"] = df["kp"].isna()
    return df

def fetch_training_data(start_year: int = 2005, end_year: int = 2025) -> pd.DataFrame:
    """Fetch definitive Kp data for the training period."""
    start = pd.Timestamp(f"{start_year}-01-01T00:00:00Z")
    end = pd.Timestamp(f"{end_year}-12-31T23:59:59Z")
    return get_kp_dataframe(start, end, status="def")

def fetch_nowcast(start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch nowcast Kp data for live operations."""
    return get_kp_dataframe(start, end, status="now")

def daily_storm_label(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute daily storm label.
    Storm = max Kp on UTC day >= 5.0 (5- = 4.667 is not enough).
    """
    df_daily = df.copy()
    df_daily["date"] = df_daily["time"].dt.date
    
    daily = df_daily.groupby("date").agg(
        max_kp=("kp", "max"),
        has_gap=("is_gap", "any"),
        gap_count=("is_gap", "sum")
    ).reset_index()
    
    # If max_kp >= 5.0, it's definitely a storm regardless of gaps.
    # If max_kp < 5.0 but there is a gap, we don't know if a storm occurred -> NaN
    # If max_kp < 5.0 and no gap -> False
    
    def get_label(row):
        if pd.notna(row["max_kp"]) and row["max_kp"] >= 5.0:
            return True
        if row["has_gap"]:
            return float("nan")
        return False
        
    daily["storm_label"] = daily.apply(get_label, axis=1)
    
    return daily

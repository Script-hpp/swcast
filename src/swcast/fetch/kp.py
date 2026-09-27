import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from swcast.config import load_config

logger = logging.getLogger(__name__)

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
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    
    if use_cache:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
            
    return data

def get_kp_dataframe(start: datetime, end: datetime, status: str = "def", use_cache: bool = True) -> pd.DataFrame:
    """Get Kp data as a pandas DataFrame on a complete 3-hourly grid."""
    data = fetch_kp_raw(start, end, status=status, use_cache=use_cache)
    
    if not data.get("datetime"):
        df_api = pd.DataFrame(columns=["time", "kp"])
    else:
        df_api = pd.DataFrame({
            "time": pd.to_datetime(data["datetime"], utc=True),
            "kp": data["Kp"]
        })
    
    # Ensure complete 3-hourly grid
    full_grid = pd.date_range(start=start, end=end, freq="3h", tz=timezone.utc, inclusive="both")
    # Actually date_range with '3h' might not align exactly if start is not 00,03 etc.
    # We should floor the start and ceil the end to nearest 3h.
    grid_start = start.floor("3h")
    grid_end = end.floor("3h")
    if grid_end < end:
        # We just want the grid to cover the requested range up to end
        pass
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
    # Group by UTC day
    df_daily = df.copy()
    df_daily["date"] = df_daily["time"].dt.date
    
    # We also want to mark a day as having a gap if any 3h interval is missing
    daily = df_daily.groupby("date").agg(
        max_kp=("kp", "max"),
        has_gap=("is_gap", "any"),
        gap_count=("is_gap", "sum")
    ).reset_index()
    
    daily["storm_label"] = daily["max_kp"] >= 5.0
    # If all values are NaN, max_kp is NaN, so storm_label is False. Let's make it NaN or False but we should check has_gap.
    # The requirement: "Tage, an denen im GFZ-Nowcast Lücken herrschen, werden von der Auswertung ausgeschlossen".
    # So we provide the gap info to downstream.
    
    return daily

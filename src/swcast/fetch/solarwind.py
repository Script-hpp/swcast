import logging
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from swcast.config import load_config

logger = logging.getLogger(__name__)

SWPC_JSON_BASE = "https://services.swpc.noaa.gov/json/rtsw"
OMNI_MIN_BASE = "https://spdf.gsfc.nasa.gov/pub/data/omni/high_res_omni"


class FallbackError(Exception):
    """Raised when less than 60 of 120 minutes of solar wind data are valid."""
    pass


def _get_cache_dir(subdir: str) -> Path:
    cfg = load_config()
    data_dir = cfg["data_dir"]
    cache_dir = data_dir / "cache" / subdir
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def fetch_swpc_live(use_cache: bool = False) -> pd.DataFrame:
    """
    Fetch real-time solar wind data (mag and wind) from NOAA SWPC.
    Endpoints:
    - https://services.swpc.noaa.gov/json/rtsw/rtsw_mag_1m.json
    - https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json
    
    Quality Handling:
    - Only records from the currently active spacecraft ('active' == True) are used.
    - Only records with 'overall_quality' == 0 are preserved, to ensure bad values are filtered explicitly.
    - Quality fields ('overall_quality', 'max_data_flag') are preserved in the output for transparency.
    - The source spacecraft ('source') is stored per minute.
    """
    mag_url = f"{SWPC_JSON_BASE}/rtsw_mag_1m.json"
    wind_url = f"{SWPC_JSON_BASE}/rtsw_wind_1m.json"
    
    mag_resp = requests.get(mag_url)
    mag_resp.raise_for_status()
    mag_data = mag_resp.json()
    
    wind_resp = requests.get(wind_url)
    wind_resp.raise_for_status()
    wind_data = wind_resp.json()
    
    df_mag = pd.DataFrame(mag_data)
    df_wind = pd.DataFrame(wind_data)
    
    if df_mag.empty or df_wind.empty:
        return pd.DataFrame(columns=["time", "bx", "by_gsm", "bz_gsm", "speed", "density", "source", "overall_quality", "max_data_flag"])
        
    # Filter for active spacecraft and good quality only
    df_mag = df_mag[(df_mag["active"] == True) & (df_mag["overall_quality"] == 0)].copy()
    df_wind = df_wind[(df_wind["active"] == True) & (df_wind["overall_quality"] == 0)].copy()
    
    df_mag["time"] = pd.to_datetime(df_mag["time_tag"], utc=True)
    df_wind["time"] = pd.to_datetime(df_wind["time_tag"], utc=True)
    
    if not df_mag["time"].is_unique:
        raise ValueError("Duplicate timestamps found in live SWPC mag data after filtering for active=True.")
    if not df_wind["time"].is_unique:
        raise ValueError("Duplicate timestamps found in live SWPC wind data after filtering for active=True.")
    
    # We want to merge the two dataframes. They should theoretically come from the same source if active=True.
    # To preserve source cleanly, we can rename them or assume they match. We'll use the mag source as primary 
    # (or check they are consistent if joined).
    df = pd.merge(df_mag, df_wind, on="time", how="outer", suffixes=('_mag', '_wind'))
    
    # Combine source if one is missing
    df["source"] = df["source_mag"].combine_first(df["source_wind"])
    df["overall_quality"] = df["overall_quality_mag"].combine_first(df["overall_quality_wind"])
    df["max_data_flag"] = df["max_data_flag_mag"].combine_first(df["max_data_flag_wind"])
    
    df = df.rename(columns={
        "bx_gsm": "bx",  # SWPC gives bx_gsm which is same as bx_gse
        "proton_speed": "speed",
        "proton_density": "density"
    })
    
    cols = ["time", "bx", "by_gsm", "bz_gsm", "speed", "density", "source", "overall_quality", "max_data_flag"]
    return df[[c for c in cols if c in df.columns]].sort_values("time").reset_index(drop=True)


def fetch_omni_historical(year: int, use_cache: bool = True) -> pd.DataFrame:
    """
    Fetch historical 1-minute OMNI solar wind data for a given year.
    Replaces fill values (9999.99, etc.) with NaN.
    Caches as parquet to save space, deletes the downloaded .asc file.
    """
    cache_dir = _get_cache_dir("omni")
    parquet_name = f"omni_min{year}.parquet"
    parquet_path = cache_dir / parquet_name
    
    if use_cache and parquet_path.exists():
        return pd.read_parquet(parquet_path)
        
    asc_name = f"omni_min{year}.asc"
    asc_path = cache_dir / asc_name
    url = f"{OMNI_MIN_BASE}/{asc_name}"
    
    logger.info(f"Downloading OMNI data for {year} from {url}")
    urllib.request.urlretrieve(url, asc_path)
        
    usecols = [0, 1, 2, 3, 14, 17, 18, 21, 25]
    names = ["year", "doy", "hour", "minute", "bx", "by_gsm", "bz_gsm", "speed", "density"]
    
    df = pd.read_csv(
        asc_path,
        sep=r"\s+",
        header=None,
        usecols=usecols,
        names=names,
        na_values={
            "bx": [9999.99],
            "by_gsm": [9999.99],
            "bz_gsm": [9999.99],
            "speed": [99999.9],
            "density": [999.99]
        }
    )
    
    # Construct datetime
    df["time"] = pd.to_datetime(
        df["year"].astype(str) + "-" + df["doy"].astype(str).str.zfill(3), 
        format="%Y-%j", utc=True
    ) + pd.to_timedelta(df["hour"], unit="h") + pd.to_timedelta(df["minute"], unit="m")
    
    cols = ["time", "bx", "by_gsm", "bz_gsm", "speed", "density"]
    df = df[cols].sort_values("time").reset_index(drop=True)
    
    if use_cache:
        df.to_parquet(parquet_path, index=False)
        asc_path.unlink(missing_ok=True)
        
    return df


def compute_2h_features(df: pd.DataFrame, run_start: datetime) -> dict:
    """
    Extract features from a 2-hour window before the run_start.
    
    Features (mean over valid minutes):
    - Bz
    - By
    - V (speed)
    - Dynamic pressure (density * V^2)
    - Newell coupling (V^(4/3) * B_T^(2/3) * sin^(8/3)(theta_c/2))
    
    Note: Newell coupling is calculated per minute and then averaged, not from averages.
    
    Rule: if less than 60 of 120 minutes are valid -> FallbackError.
    A minute is valid if it has all required data (bz, by, speed, density).
    """
    window_start = run_start - timedelta(hours=2)
    window_end = run_start - timedelta(seconds=1)
    
    if df.index.name == "time":
        df_win = df.loc[window_start:window_end].copy()
    else:
        mask = (df["time"] >= window_start) & (df["time"] < run_start)
        df_win = df[mask].copy()
    
    
    df_win = df_win.dropna(subset=["by_gsm", "bz_gsm", "speed", "density"])
    
    valid_minutes = len(df_win)
    if valid_minutes < 60:
        raise FallbackError(f"Only {valid_minutes}/120 valid minutes in 2h window before {run_start}")
        
    df_win["dyn_pressure"] = df_win["density"] * (df_win["speed"] ** 2)
    
    bt = np.sqrt(df_win["by_gsm"]**2 + df_win["bz_gsm"]**2)
    theta_c = np.arctan2(df_win["by_gsm"], df_win["bz_gsm"])
    
    sin_tc2 = np.abs(np.sin(theta_c / 2.0))
    newell = (df_win["speed"] ** (4/3)) * (bt ** (2/3)) * (sin_tc2 ** (8/3))
    
    df_win["newell"] = newell
    
    return {
        "bz_gsm": float(df_win["bz_gsm"].mean()),
        "by_gsm": float(df_win["by_gsm"].mean()),
        "speed": float(df_win["speed"].mean()),
        "dyn_pressure": float(df_win["dyn_pressure"].mean()),
        "newell": float(df_win["newell"].mean()),
        "valid_minutes": valid_minutes
    }

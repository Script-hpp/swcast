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
    """
    mag_url = f"{SWPC_JSON_BASE}/rtsw_mag_1m.json"
    wind_url = f"{SWPC_JSON_BASE}/rtsw_wind_1m.json"
    
    # Normally we do not cache live data as it updates continuously,
    # but we allow it for testing if needed.
    
    mag_resp = requests.get(mag_url)
    mag_resp.raise_for_status()
    mag_data = mag_resp.json()
    
    wind_resp = requests.get(wind_url)
    wind_resp.raise_for_status()
    wind_data = wind_resp.json()
    
    df_mag = pd.DataFrame(mag_data)
    df_wind = pd.DataFrame(wind_data)
    
    if df_mag.empty or df_wind.empty:
        return pd.DataFrame(columns=["time", "bx", "by_gsm", "bz_gsm", "speed", "density"])
        
    df_mag["time"] = pd.to_datetime(df_mag["time_tag"], utc=True)
    df_wind["time"] = pd.to_datetime(df_wind["time_tag"], utc=True)
    
    df = pd.merge(df_mag, df_wind, on="time", how="outer")
    
    df = df.rename(columns={
        "bx_gsm": "bx",  # SWPC gives bx_gsm which is same as bx_gse
        "proton_speed": "speed",
        "proton_density": "density"
    })
    
    # Return uniform columns
    cols = ["time", "bx", "by_gsm", "bz_gsm", "speed", "density"]
    return df[[c for c in cols if c in df.columns]].sort_values("time").reset_index(drop=True)


def fetch_omni_historical(year: int, use_cache: bool = True) -> pd.DataFrame:
    """
    Fetch historical 1-minute OMNI solar wind data for a given year.
    Replaces fill values (9999.99, etc.) with NaN.
    """
    cache_dir = _get_cache_dir("omni")
    file_name = f"omni_min{year}.asc"
    cache_path = cache_dir / file_name
    
    if not (use_cache and cache_path.exists()):
        url = f"{OMNI_MIN_BASE}/{file_name}"
        logger.info(f"Downloading OMNI data for {year} from {url}")
        # Note: can be large (20-30 MB)
        urllib.request.urlretrieve(url, cache_path)
        
    # Parse OMNI 1-min ASCII
    # Column indices (0-based):
    # 0: Year, 1: Day, 2: Hour, 3: Minute
    # 14: Bx (GSE/GSM)
    # 17: By (GSM)
    # 18: Bz (GSM)
    # 21: Flow speed (km/s)
    # 25: Proton Density (n/cc)
    
    # We load only the required columns to save memory
    usecols = [0, 1, 2, 3, 14, 17, 18, 21, 25]
    names = ["year", "doy", "hour", "minute", "bx", "by_gsm", "bz_gsm", "speed", "density"]
    
    df = pd.read_csv(
        cache_path,
        delim_whitespace=True,
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
    return df[cols].sort_values("time").reset_index(drop=True)


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
    mask = (df["time"] >= window_start) & (df["time"] < run_start)
    df_win = df[mask].copy()
    
    # Compute per-minute features
    # Required base columns
    df_win = df_win.dropna(subset=["by_gsm", "bz_gsm", "speed", "density"])
    
    valid_minutes = len(df_win)
    if valid_minutes < 60:
        raise FallbackError(f"Only {valid_minutes}/120 valid minutes in 2h window before {run_start}")
        
    df_win["dyn_pressure"] = df_win["density"] * (df_win["speed"] ** 2)
    
    # Newell coupling
    # B_T = sqrt(By^2 + Bz^2)
    # theta_c = atan2(By, Bz)
    bt = np.sqrt(df_win["by_gsm"]**2 + df_win["bz_gsm"]**2)
    theta_c = np.arctan2(df_win["by_gsm"], df_win["bz_gsm"])
    
    # Newell = V^(4/3) * B_T^(2/3) * (sin(theta_c/2))^(8/3)
    # Using absolute value of sin for robustness, though theta_c/2 is in [-pi/2, pi/2] where sin can be negative,
    # the 8/3 power is equivalent to (sin^2)^(4/3). We compute np.abs(sin(theta_c/2))**(8/3).
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

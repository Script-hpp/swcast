import logging
import json
import re
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from swcast.config import load_config

logger = logging.getLogger(__name__)

SWPC_JSON_BASE = "https://services.swpc.noaa.gov/json"
SWPC_TEXT_BASE = "https://services.swpc.noaa.gov/text"
SWPC_FTP_BASE = "ftp://ftp.swpc.noaa.gov/pub/warehouse"


def _get_archive_dir() -> Path:
    cfg = load_config()
    archive_dir = Path(cfg["paths"]["archive_swpc_dir"])
    archive_dir.mkdir(parents=True, exist_ok=True)
    return archive_dir


def _get_cache_dir() -> Path:
    cfg = load_config()
    cache_dir = cfg["data_dir"] / "cache" / "swpc"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def archive_live_products() -> dict[str, Path]:
    """
    Fetch and archive live SWPC products with fetch time.
    Returns the paths to the archived files.
    """
    archive_dir = _get_archive_dir()
    now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    
    products = {
        "solar_probabilities.json": f"{SWPC_JSON_BASE}/solar_probabilities.json",
        "noaa-planetary-k-index-forecast.json": f"{SWPC_JSON_BASE}/noaa-planetary-k-index-forecast.json",
        "3-day-solar-geomag-predictions.txt": f"{SWPC_TEXT_BASE}/3-day-solar-geomag-predictions.txt"
    }
    
    saved_paths = {}
    
    for filename, url in products.items():
        logger.info(f"Archiving {url}")
        resp = requests.get(url)
        resp.raise_for_status()
        
        out_name = f"{now_str}_{filename}"
        out_path = archive_dir / out_name
        
        with open(out_path, "wb") as f:
            f.write(resp.content)
            
        saved_paths[filename] = out_path
        
    return saved_paths


def parse_rsga(text: str) -> pd.DataFrame:
    """
    Parses the 3-day-solar-geomag-predictions.txt (or historical RSGA).
    Extracts Middle Latitude probabilities for Minor Storm and Major-Severe Storm.
    """
    # Extract Issue Time
    # Example: ":Issued: 2024 Jan 01 2200 UTC"
    m_issue = re.search(r":Issued:\s*(.* UTC)", text)
    if not m_issue:
        # Fallback for some old formats if needed, or raise
        raise ValueError("Could not find issue time in text")
    
    # Parse as datetime
    # We might need to handle different formats, but usually "%Y %b %d %H%M %Z"
    issue_str = m_issue.group(1).strip()
    try:
        issue_time = pd.to_datetime(issue_str, utc=True)
    except Exception:
        raise ValueError(f"Could not parse issue time: {issue_str}")
        
    lines = text.split('\n')
    in_mid_lat = False
    
    minor_storm = None
    major_severe = None
    
    for line in lines:
        line = line.strip()
        if re.search(r"A\.\s+Middle Latitudes", line, re.IGNORECASE):
            in_mid_lat = True
            continue
        elif re.search(r"B\.\s+High Latitudes", line, re.IGNORECASE):
            in_mid_lat = False
            continue
            
        if in_mid_lat:
            m1 = re.match(r"(Minor\s+Storm)\s+(\d+)/(\d+)/(\d+)", line, re.IGNORECASE)
            if m1:
                minor_storm = [int(m1.group(2))/100.0, int(m1.group(3))/100.0, int(m1.group(4))/100.0]
                
            m2 = re.match(r"(Major-severe\s+storm)\s+(\d+)/(\d+)/(\d+)", line, re.IGNORECASE)
            if m2:
                major_severe = [int(m2.group(2))/100.0, int(m2.group(3))/100.0, int(m2.group(4))/100.0]

    if minor_storm is None or major_severe is None:
        raise ValueError("Could not find required probability fields in text")
        
    # Build dataframe for Tag +1, +2, +3
    base_date = issue_time.floor("D")
    
    res = []
    for i in range(3):
        target_date = (base_date + pd.Timedelta(days=i+1)).date()
        p_minor = minor_storm[i]
        p_major = major_severe[i]
        res.append({
            "issue_time": issue_time,
            "target_date": target_date,
            "p_minor_storm": p_minor,
            "p_major_severe_storm": p_major,
            "p_storm": p_minor + p_major
        })
        
    return pd.DataFrame(res)


def fetch_historical_rsga(start_year: int = 2010, end_year: int = 2025) -> pd.DataFrame:
    """
    Fetch and parse historical RSGA products from SWPC FTP warehouse.
    """
    cache_dir = _get_cache_dir()
    all_dfs = []
    
    for year in range(start_year, end_year + 1):
        tar_filename = f"{year}_RSGA.tar.gz"
        cache_path = cache_dir / tar_filename
        
        if not cache_path.exists():
            url = f"{SWPC_FTP_BASE}/{year}/{tar_filename}"
            logger.info(f"Downloading historical RSGA for {year} from {url}")
            try:
                urllib.request.urlretrieve(url, cache_path)
            except Exception as e:
                logger.warning(f"Could not download {url}: {e}")
                continue
                
        # Extract and parse all 22:00 UTC products
        with tarfile.open(cache_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith("RSGA.txt"):
                    f = tar.extractfile(member)
                    if f:
                        text = f.read().decode("utf-8", errors="replace")
                        # Usually there are multiple issues per day, we want the one around 2200 UTC.
                        # We parse the file, if it fails we skip or log.
                        try:
                            df = parse_rsga(text)
                            # We only want to keep the 22:00 UTC product (issue_time.hour == 22)
                            if df["issue_time"].iloc[0].hour == 22:
                                all_dfs.append(df)
                        except ValueError:
                            # It could be an irregularly formatted file or wrong time
                            pass
                            
    if not all_dfs:
        return pd.DataFrame()
        
    final_df = pd.concat(all_dfs, ignore_index=True)
    return final_df.sort_values(["issue_time", "target_date"]).reset_index(drop=True)

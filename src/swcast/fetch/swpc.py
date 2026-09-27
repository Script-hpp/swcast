import logging
import json
import re
import shutil
import tarfile
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests

from swcast.config import load_config

logger = logging.getLogger(__name__)

SWPC_JSON_BASE = "https://services.swpc.noaa.gov/json"
SWPC_TEXT_BASE = "https://services.swpc.noaa.gov/text"
# https://ftp.swpc.noaa.gov does not answer (verified with curl -I, times out);
# requests can't do ftp:// either, so this uses urllib.request.urlopen with an
# explicit timeout instead (see fetch_historical_rsga).
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


def parse_rsga(text: str) -> pd.DataFrame:
    """
    Parses the historical RSGA product (or live sgarf.txt).
    Extracts Middle Latitude probabilities for Minor Storm and Major-Severe Storm.
    """
    m_issue = re.search(r":Issued:\s*(.* UTC)", text)
    if not m_issue:
        raise ValueError("Could not find issue time in text")
    
    issue_str = m_issue.group(1).strip()
    try:
        issue_time = pd.to_datetime(issue_str, utc=True)
    except Exception:
        raise ValueError(f"Could not parse issue time: {issue_str}")
        
    lines = text.split('\n')
    in_mid_lat = False
    
    minor_storm = None
    major_severe = None
    target_dates = []
    
    for line in lines:
        line = line.strip()
        
        m_dates = re.search(r"VI\.\s+Geomagnetic Activity Probabilities\s+(\d+\s+[A-Za-z]+)-(\d+\s+[A-Za-z]+)", line, re.IGNORECASE)
        if m_dates:
            d1_str = f"{issue_time.year} {m_dates.group(1)}"
            d1 = pd.to_datetime(d1_str).date()
            if d1 < issue_time.date() and issue_time.month == 12 and d1.month == 1:
                d1 = pd.to_datetime(f"{issue_time.year + 1} {m_dates.group(1)}").date()
            target_dates = [d1, d1 + timedelta(days=1), d1 + timedelta(days=2)]
            
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
        
    if not target_dates:
        raise ValueError("Could not find prediction dates in section VI header")


    res = []
    for i in range(3):
        res.append({
            "issue_time": issue_time,
            "target_date": target_dates[i],
            "p_minor_storm": minor_storm[i],
            "p_major_severe_storm": major_severe[i],
            "p_storm": minor_storm[i] + major_severe[i]
        })
        
    return pd.DataFrame(res)


def parse_daypre(text: str) -> pd.DataFrame:
    """
    Parses the live 3-day-solar-geomag-predictions.txt (daypre).
    """
    m_issue = re.search(r":Issued:\s*(.* UTC)", text)
    if not m_issue:
        raise ValueError("Could not find issue time in text")
    
    issue_str = m_issue.group(1).strip()
    try:
        issue_time = pd.to_datetime(issue_str, utc=True)
    except Exception:
        raise ValueError(f"Could not parse issue time: {issue_str}")

    m_dates = re.search(r":Prediction_dates:\s+(.*)", text)
    if not m_dates:
        raise ValueError("Could not find :Prediction_dates: in text")
    
    dates_str = m_dates.group(1).strip()
    parts = re.findall(r'\d{4}\s+[A-Za-z]{3}\s+\d{1,2}', dates_str)
    
    if len(parts) != 3:
        raise ValueError(f"Could not parse 3 dates from {dates_str}")

    target_dates = [pd.to_datetime(p).date() for p in parts]
    
    if issue_time.hour >= 20:
        base_date = issue_time.floor("D")
        for i in range(3):
            expected_date = (base_date + pd.Timedelta(days=i+1)).date()
            assert target_dates[i] == expected_date, f"Target date mismatch: {target_dates[i]} != {expected_date}"

    minor_storm = None
    major_severe = None
    
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        m1 = re.match(r"Mid/Minor_Storm\s+(\d+)\s+(\d+)\s+(\d+)", line, re.IGNORECASE)
        if m1:
            minor_storm = [int(m1.group(1))/100.0, int(m1.group(2))/100.0, int(m1.group(3))/100.0]
            
        m2 = re.match(r"Mid/Major-Severe_Storm\s+(\d+)\s+(\d+)\s+(\d+)", line, re.IGNORECASE)
        if m2:
            major_severe = [int(m2.group(1))/100.0, int(m2.group(2))/100.0, int(m2.group(3))/100.0]

    if minor_storm is None or major_severe is None:
        raise ValueError("Could not find required probability fields in text")

    res = []
    for i in range(3):
        p_minor = minor_storm[i]
        p_major = major_severe[i]
        res.append({
            "issue_time": issue_time,
            "target_date": target_dates[i],
            "p_minor_storm": p_minor,
            "p_major_severe_storm": p_major,
            "p_storm": p_minor + p_major
        })
        
    return pd.DataFrame(res)


LIVE_PRODUCTS = {
    "solar_probabilities.json": f"{SWPC_JSON_BASE}/solar_probabilities.json",
    # NOT under /json/ — that 404s. Verified: /products/... returns 200 with
    # a time_tag/kp/observed JSON list.
    "noaa-planetary-k-index-forecast.json": "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json",
    "3-day-solar-geomag-predictions.txt": f"{SWPC_TEXT_BASE}/3-day-solar-geomag-predictions.txt",
    "sgarf.txt": f"{SWPC_TEXT_BASE}/sgarf.txt",
}


def archive_live_products() -> dict[str, Path]:
    """
    Fetch and archive live SWPC products with fetch time.
    Also verifies that daypre and sgarf are consistent, if both were fetched.

    Each product is fetched independently: a failure fetching one product
    (network error, timeout, HTTP error) is logged and skipped, and does not
    prevent the others from being archived. The daily run must not go down
    because a single SWPC product is unavailable.

    Returns the paths to the successfully archived files (a subset of
    LIVE_PRODUCTS' keys if some fetches failed).
    """
    archive_dir = _get_archive_dir()
    now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    saved_paths = {}

    for filename, url in LIVE_PRODUCTS.items():
        try:
            logger.info(f"Archiving {url}")
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()

            out_name = f"{now_str}_{filename}"
            out_path = archive_dir / out_name

            with open(out_path, "wb") as f:
                f.write(resp.content)

            saved_paths[filename] = out_path
        except Exception as exc:
            logger.error(f"Failed to archive {filename} from {url}: {exc}")

    if "3-day-solar-geomag-predictions.txt" in saved_paths and "sgarf.txt" in saved_paths:
        with open(saved_paths["3-day-solar-geomag-predictions.txt"], "r") as f:
            daypre_text = f.read()
        with open(saved_paths["sgarf.txt"], "r") as f:
            sgarf_text = f.read()

        try:
            df_daypre = parse_daypre(daypre_text)
            df_sgarf = parse_rsga(sgarf_text)

            pd.testing.assert_frame_equal(
                df_daypre[["target_date", "p_minor_storm", "p_major_severe_storm"]],
                df_sgarf[["target_date", "p_minor_storm", "p_major_severe_storm"]]
            )
        except Exception as e:
            logger.warning(f"Inconsistency between daypre and sgarf products: {e}")

    return saved_paths


def is_valid_live_product(df: pd.DataFrame, run_date: datetime.date) -> bool:
    """
    Check if the live SWPC product is valid for the given run date.
    It is valid if its issue_date matches the run_date.
    """
    if df.empty:
        return False
    issue_date = df["issue_time"].iloc[0].date()
    return issue_date == run_date


def is_valid_historical_product(df: pd.DataFrame, file_date: datetime.date) -> tuple[bool, str]:
    """
    Checks historical RSGA product validity.
    Returns (is_valid, reason).
    """
    if df.empty:
        return False, "empty"
        
    issue_time = df["issue_time"].iloc[0]
    target_date_1 = df["target_date"].iloc[0]
    
    # Rule 1: issue_time < 00:00 UTC of target_date_1
    if issue_time >= pd.Timestamp(target_date_1, tz=timezone.utc):
        return False, "time"
        
    # Rule 2: target dates exactly file_date + 1..+3
    expected_target_1 = file_date + timedelta(days=1)
    if target_date_1 != expected_target_1:
        return False, "dates"
        
    return True, ""


def fetch_historical_rsga(start_year: int = 2010, end_year: int = 2025) -> pd.DataFrame:
    """
    Fetch and parse historical RSGA products from SWPC FTP warehouse.
    Uses product if issue_time < 00:00 UTC of first target date, and target dates match issue_date +1..+3.
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
                with urllib.request.urlopen(url, timeout=60) as resp, open(cache_path, "wb") as f:
                    shutil.copyfileobj(resp, f)
            except Exception as e:
                cache_path.unlink(missing_ok=True)
                logger.error(f"Failed to download {url}: {e}")
                raise RuntimeError(f"Missing historical RSGA data for year {year}") from e
                
        valid_count = 0
        parse_errors = 0
        excluded_time = 0
        excluded_dates = 0
        
        with tarfile.open(cache_path, "r:gz") as tar:
            members = [m for m in tar.getmembers() if m.name.endswith("RSGA.txt")]
            for member in members:
                # Extract filename date: e.g., 20100609RSGA.txt
                m_name = member.name.split("/")[-1]
                m_date_str = m_name[:8]
                try:
                    file_date = pd.to_datetime(m_date_str, format="%Y%m%d").date()
                except Exception:
                    continue
                    
                f = tar.extractfile(member)
                if f:
                    text = f.read().decode("utf-8", errors="replace")
                    try:
                        df = parse_rsga(text)
                    except Exception as e:
                        parse_errors += 1
                        continue
                        
                    valid, reason = is_valid_historical_product(df, file_date)
                    if not valid:
                        if reason == "time":
                            excluded_time += 1
                        elif reason == "dates":
                            excluded_dates += 1
                        continue
                        
                    all_dfs.append(df)
                    valid_count += 1
                        
        expected = 365 if year % 4 != 0 else 366
        missing = expected - valid_count
        logger.info(f"Year {year}: Used {valid_count}. Excluded(time): {excluded_time}. Excluded(dates): {excluded_dates}. Parse errors: {parse_errors}. Missing: {missing}")
                            
    if not all_dfs:
        return pd.DataFrame()
        
    final_df = pd.concat(all_dfs, ignore_index=True)
    return final_df.sort_values(["issue_time", "target_date"]).reset_index(drop=True)

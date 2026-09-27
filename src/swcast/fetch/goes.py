"""Download and parse the NOAA NCEI GOES-R XRS flare summary.

Source: NCEI mission-length flare report (GOES 8-19, science-quality), CSV form.
https://www.ncei.noaa.gov/products/goes-r-extreme-ultraviolet-xray-irradiance

The mission-length CSV filename encodes its end date (`..._eYYYYMMDD_v*.csv`) and
changes whenever NCEI regenerates it, so the directory listing is scanned for the
current filename rather than hardcoding it.

GOES 8-15 flares are calibrated with an operational scaling factor that later
science-quality reprocessing removed (see PRD.md, Abschnitt 4). Only GOES-16+
rows should be used for anything comparable to current NOAA/scoreboard classes;
`fetch_goes_flares` filters this by default via `min_satellite`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import requests

CSV_DIR_URL = (
    "https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/"
    "goes/multi/l2/data/xrsf-l2-flrpt_science/csv/"
)
_MISSION_LENGTH_RE = re.compile(
    r'href="(sci_xrsf-l2-flrpt_geo_s\d{8}_e\d{8}_v[\d.\-]+\.csv)"'
)


def _find_mission_length_csv_url(session: requests.Session) -> str:
    resp = session.get(CSV_DIR_URL, timeout=30)
    resp.raise_for_status()
    matches = _MISSION_LENGTH_RE.findall(resp.text)
    if not matches:
        raise RuntimeError(f"No mission-length flare CSV found at {CSV_DIR_URL}")
    # Filenames are fixed-width (sYYYYMMDD_eYYYYMMDD), so lexical sort == date sort.
    return CSV_DIR_URL + sorted(matches)[-1]


def _download_raw_csv(cache_path: Path, force: bool = False) -> Path:
    if cache_path.exists() and not force:
        return cache_path
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        url = _find_mission_length_csv_url(session)
        resp = session.get(url, timeout=120)
        resp.raise_for_status()
    cache_path.write_bytes(resp.content)
    return cache_path


def _parse_satellite(source: str) -> int | None:
    # xrsb_irrad_source looks like "GOES-16".
    if not isinstance(source, str) or "-" not in source:
        return None
    try:
        return int(source.rsplit("-", 1)[-1])
    except ValueError:
        return None


def _parse_flare_class(flare_class: str) -> tuple[str | None, float | None]:
    # e.g. "M1.2" -> ("M", 1.2); malformed/missing values -> (None, None).
    if not isinstance(flare_class, str) or len(flare_class) < 2:
        return None, None
    letter, number = flare_class[0], flare_class[1:]
    try:
        return letter, float(number)
    except ValueError:
        return None, None


def fetch_goes_flares(
    data_dir: Path,
    start_date: str,
    end_date: str,
    min_satellite: int = 16,
    force_download: bool = False,
) -> pd.DataFrame:
    """Return the GOES XRS flare list, filtered to [start_date, end_date] and
    to satellites >= min_satellite.

    Columns: peak_time, start_time, end_time, satellite, flare_class,
    class_letter, class_number, peak_flux_wm2 (xrsb_irrad), active_region.
    `peak_time` is the raw CSV's `time` column, confirmed by inspection to
    fall strictly between `start_time` and `end_time` (i.e. it is the flare's
    peak, not its onset).
    """
    raw_path = Path(data_dir) / "raw" / "goes_flares_mission_length.csv"
    _download_raw_csv(raw_path, force=force_download)

    df = pd.read_csv(
        raw_path,
        usecols=[
            "time",
            "start_time",
            "end_time",
            "xrsb_irrad",
            "flare_class",
            "xrsb_irrad_source",
            "active_region",
        ],
        parse_dates=["time", "start_time", "end_time"],
    )
    df["satellite"] = df["xrsb_irrad_source"].apply(_parse_satellite)
    df[["class_letter", "class_number"]] = df["flare_class"].apply(
        lambda c: pd.Series(_parse_flare_class(c))
    )
    df = df.rename(columns={"xrsb_irrad": "peak_flux_wm2", "time": "peak_time"})
    df = df.drop(columns=["xrsb_irrad_source", "flare_class"])

    mask = (
        (df["satellite"] >= min_satellite)
        & (df["start_time"] >= pd.Timestamp(start_date, tz="UTC").tz_localize(None))
        & (df["start_time"] <= pd.Timestamp(end_date, tz="UTC").tz_localize(None))
    )
    return df.loc[mask].sort_values("start_time").reset_index(drop=True)


def _find_mission_length_nc_url(session: requests.Session, satellite: int) -> str:
    url = f"https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/goes{satellite}/l2/data/xrsf-l2-avg1m_science/"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    matches = re.findall(rf'href="(sci_xrsf-l2-avg1m_g{satellite}_s\d{{8}}_e\d{{8}}_v[\d.\-]+\.nc)"', resp.text)
    if not matches:
        raise RuntimeError(f"No mission-length 1m NC found at {url}")
    return url + sorted(matches)[-1]


def build_gap_series(ds_dict: dict[int, "xr.Dataset"], start_date: str, end_date: str) -> pd.Series:
    """Pure function to build the combined gap mask from multiple datasets."""
    start_ts = pd.Timestamp(start_date, tz="UTC").tz_localize(None)
    end_ts = pd.Timestamp(end_date, tz="UTC").tz_localize(None)
    
    # Create the common 1-minute grid
    common_idx = pd.date_range(start_ts, end_ts, freq="1min", inclusive="left")
    combined_gap = pd.Series(True, index=common_idx)
    
    for sat, ds in ds_dict.items():
        ds_sub = ds.sel(time=slice(start_ts, end_ts))
        
        # Missing rows in the file will naturally become NaN when we reindex later,
        # but first let's build a series for this satellite.
        times = ds_sub["time"].to_pandas().dt.tz_localize(None)
        
        # flag_meanings: good_data(0) eclipse(1) bad_data(2) interpolated(4)
        # 1 (eclipse) and 2 (bad_data) are invalid. 4 (interpolated) is valid.
        flag_vals = ds_sub["xrsb_flag"].to_pandas().fillna(0).astype(int)
        
        is_bad = ((flag_vals & 2) != 0) | ((flag_vals & 1) != 0)
        is_nan = ds_sub["xrsb_flux"].to_pandas().isna()
        
        # A point is a gap for THIS satellite if it's bad or NaN
        sat_gap = is_bad | is_nan
        sat_gap.index = times
        
        # Reindex to common grid. Missing rows become True (gap)
        sat_gap_reindexed = sat_gap.reindex(common_idx, fill_value=True)
        
        # Combined gap: minute is gap only if ALL satellites have a gap
        combined_gap = combined_gap & sat_gap_reindexed
        
    return combined_gap

def fetch_goes_1m_gaps(
    data_dir: Path,
    start_date: str,
    end_date: str,
    satellites: tuple[int, ...] = (18, 19),
    force_download: bool = False,
) -> pd.Series:
    """Return a boolean pandas Series (index: time, value: True if data is MISSING or BAD).

    Downloads the mission-length 1-minute average science netCDF for the given satellites.
    A minute is considered a gap if ALL specified satellites have missing/invalid data.
    Values are considered invalid if `xrsb_flux` is NaN, or if `(xrsb_flag & 2) != 0` (bad_data),
    or if `(xrsb_flag & 1) != 0` (eclipse).
    Eclipse is treated as a gap because the Earth blocks the satellite's view of the sun.
    Interpolated data (`(xrsb_flag & 4) != 0`) remains valid.
    """
    import xarray as xr

    ds_dict = {}
    for satellite in satellites:
        raw_path = Path(data_dir) / "raw" / f"goes{satellite}_xrs_1m_mission_length.nc"
        if not raw_path.exists() or force_download:
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            with requests.Session() as session:
                url = _find_mission_length_nc_url(session, satellite)
                resp = session.get(url, timeout=120)
                resp.raise_for_status()
            raw_path.write_bytes(resp.content)

        ds = xr.open_dataset(raw_path)
        ds_dict[satellite] = ds

    combined_gap = build_gap_series(ds_dict, start_date, end_date)
    
    for ds in ds_dict.values():
        ds.close()
        
    return combined_gap


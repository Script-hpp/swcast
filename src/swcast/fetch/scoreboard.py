"""Download and parse the CCMC Flare Scoreboard's per-model static file archive.

Primary access path (PRD.md Abschnitt 4/9): the flat file archive under
https://iswa.gsfc.nasa.gov/iswa_data_tree/model/solar/flare-scoreboard/<MODEL>/<YYYY>/<MM>/,
one file per issued forecast. The HAPI API
(iswa.gsfc.nasa.gov/IswaSystemWebApp/flarescoreboard/hapi/) is the documented
fallback if this archive is retired or a model migrates away from it.

Confirmed by manual inspection (2026-09-27) that models do NOT share one file
format:
  - NOAA_1, SIDC_v2: ISES-standard XML (<message><forecast>...), but with
    different tag names for the prediction window (<starttime>/<endtime> vs
    <begin>/<end>) and flux-bin naming (M/X vs C+/M+/X+). SIDC's issuetime and
    window tags also omit the trailing "Z" that NOAA's carry -- both are UTC,
    so it is stripped rather than parsed as a timezone difference.
  - ASSA_1: a fixed-column plain-text table, not XML at all.
Only these two formats are implemented; an unregistered model raises
NotImplementedError naming the model, rather than being silently skipped
(PRD.md FR-0.3 principle: mark, don't drop).

NOAA's Full Disk forecast only ever carries M and X probabilities (confirmed
from a live file, 2026-09-27) -- no C-class full-disk probability is
submitted, only per-active-region C probabilities (Region group, not parsed
here). This must not be read as "NOAA predicts C+ = 0"; it is "NOAA does not
forecast full-disk C+ at all", and downstream code must treat it as missing,
not zero.
"""

from __future__ import annotations

import concurrent.futures as cf
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pandas as pd
import requests

ARCHIVE_BASE_URL = "https://iswa.gsfc.nasa.gov/iswa_data_tree/model/solar/flare-scoreboard"

# Hard cap: never open more than this many concurrent connections to the
# CCMC/ISWA archive, regardless of what a caller passes in (politeness to a
# shared, unauthenticated public server).
MAX_CONCURRENT_CONNECTIONS = 4

# Full-disk flux-bin names, as submitted by each model, normalized to the
# classes used elsewhere in swcast (PRD.md Abschnitt 3/6).
_FLUXBIN_TO_CLASS = {"C": "C+", "C+": "C+", "M": "M+", "M+": "M+", "X": "X", "X+": "X"}

_HREF_RE = re.compile(r'href="([^"?][^"]*)"')


def _strip_z(value: str | None) -> str | None:
    return value[:-1] if isinstance(value, str) and value.endswith("Z") else value


def _list_dir(session: requests.Session, url: str) -> list[str]:
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return [name for name in _HREF_RE.findall(resp.text) if not name.startswith("/")]


def list_forecast_files(session: requests.Session, model: str, year: int, month: int) -> list[str]:
    url = f"{ARCHIVE_BASE_URL}/{model}/{year:04d}/{month:02d}/"
    try:
        names = _list_dir(session, url)
    except requests.HTTPError:
        return []
    return [url + name for name in names if not name.endswith("/")]


def _parse_ises_xml(content: bytes, model: str) -> list[dict]:
    root = ET.fromstring(content)
    forecast = root.find("forecast")
    issue_time = _strip_z(forecast.findtext("issuetime"))
    window = forecast.find("predictionwindow")
    window_start = _strip_z(window.findtext("starttime") or window.findtext("begin"))
    window_end = _strip_z(window.findtext("endtime") or window.findtext("end"))

    rows = []
    for group in forecast.findall("group"):
        if group.findtext("forecasttype") != "Full Disk":
            continue
        for entry in group.findall("entry"):
            fluxbin = entry.find("fluxbin").get("name")
            value = entry.findtext("./probability/value")
            klass = _FLUXBIN_TO_CLASS.get(fluxbin)
            if klass is None or value is None:
                continue
            rows.append(
                dict(
                    model=model,
                    klass=klass,
                    issue_time=issue_time,
                    window_start=window_start,
                    window_end=window_end,
                    probability=float(value),
                )
            )
    return rows


def _parse_assa_text(content: bytes, model: str) -> list[dict]:
    lines = content.decode("utf-8", errors="replace").splitlines()
    meta: dict[str, str] = {}
    header_idx = None
    for i, line in enumerate(lines):
        if ":" in line and not line.startswith("#"):
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
        if line.startswith("X_prob"):
            header_idx = i
            break
    if header_idx is None:
        return []

    headers = lines[header_idx].split()
    values = lines[header_idx + 1].split()
    row = dict(zip(headers, values))

    issue_time = _strip_z(meta.get("Issue Time"))
    window_start = _strip_z(meta.get("Prediction Window Start Time"))
    window_end = _strip_z(meta.get("Prediction Window End Time"))

    rows = []
    for letter in ("X", "M", "C"):
        key = f"{letter}_prob"
        if key not in row:
            continue
        rows.append(
            dict(
                model=model,
                klass=_FLUXBIN_TO_CLASS[letter],
                issue_time=issue_time,
                window_start=window_start,
                window_end=window_end,
                probability=float(row[key]),
            )
        )
    return rows


_PARSERS = {
    "NOAA_1": _parse_ises_xml,
    "SIDC_v2": _parse_ises_xml,
    "ASSA_1": _parse_assa_text,
}


def _cache_path(data_dir: Path, model: str, year: int, month: int, filename: str) -> Path:
    return Path(data_dir) / "raw" / "scoreboard" / model / f"{year:04d}" / f"{month:02d}" / filename


def _fetch_one_file(session: requests.Session, file_url: str, cache_path: Path) -> bytes | None:
    """Return the file's bytes, from the local cache if present, else from
    the network (caching the result). Returns None on a non-200 response so
    the caller can skip it rather than crash the whole batch.
    """
    if cache_path.exists():
        return cache_path.read_bytes()
    resp = session.get(file_url, timeout=30)
    if resp.status_code != 200:
        return None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(resp.content)
    return resp.content


def fetch_scoreboard_model(
    model: str,
    start_date: str,
    end_date: str,
    data_dir: Path,
    max_workers: int = MAX_CONCURRENT_CONNECTIONS,
) -> pd.DataFrame:
    """Download and parse one model's Full-Disk forecasts in [start_date, end_date].

    Raw files are cached under `data_dir/raw/scoreboard/<model>/<year>/<month>/`
    and re-used on subsequent calls without re-downloading. Downloads run
    concurrently, capped at `MAX_CONCURRENT_CONNECTIONS` (4) connections to
    the CCMC/ISWA archive regardless of `max_workers` -- this server is
    shared and unauthenticated, so we stay polite.

    Columns: model, class, issue_time, window_start, window_end, probability
    (PRD.md FR-0.1).
    """
    if model not in _PARSERS:
        raise NotImplementedError(
            f"No parser registered for scoreboard model '{model}'. Inspect a "
            f"sample file under {ARCHIVE_BASE_URL}/{model}/ and add one to "
            f"fetch/scoreboard.py's _PARSERS before including this model."
        )
    parser = _PARSERS[model]
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    max_workers = min(max_workers, MAX_CONCURRENT_CONNECTIONS)

    rows: list[dict] = []
    with requests.Session() as session:
        jobs: list[tuple[str, Path]] = []
        for period in pd.period_range(start, end, freq="M"):
            for file_url in list_forecast_files(session, model, period.year, period.month):
                filename = file_url.rsplit("/", 1)[-1]
                jobs.append((file_url, _cache_path(data_dir, model, period.year, period.month, filename)))

        with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_fetch_one_file, session, url, path) for url, path in jobs]
            for future in cf.as_completed(futures):
                content = future.result()
                if content is None:
                    continue
                try:
                    rows.extend(parser(content, model))
                except ET.ParseError:
                    continue

    df = pd.DataFrame(
        rows, columns=["model", "klass", "issue_time", "window_start", "window_end", "probability"]
    )
    df = df.rename(columns={"klass": "class"})
    if df.empty:
        return df
    for col in ("issue_time", "window_start", "window_end"):
        df[col] = pd.to_datetime(df[col])
    mask = (df["window_start"] >= start) & (df["window_start"] <= end)
    # Sort key must fully disambiguate rows for deterministic output: parallel
    # downloads complete in a nondeterministic order, and NOAA's day1/day2/day3
    # files share the same issue_time (only window_start differs between them).
    return (
        df.loc[mask]
        .sort_values(["issue_time", "window_start", "class"])
        .reset_index(drop=True)
    )

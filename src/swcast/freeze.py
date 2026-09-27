"""
freeze.py – Timestamp-Freeze für swcast-Ausgabedateien.

Workflow
--------
1. freeze_file(path) berechnet den SHA-256-Hash der Datei und speichert ihn
   als <path>.sha256 (Format kompatibel mit sha256sum(1)).
2. Für ZWEI TSAs (FreeTSA und DigiCert) werden RFC-3161-Zeitstempel-Token
   angefordert und als <path>.freetsa.tsr bzw. <path>.digicert.tsr gespeichert.
   Falls eine TSA ausfällt, wird protokolliert und weitergemacht.
   Fallen beide aus, wird ein RuntimeError geworfen.
3. OpenTimestamps (ots stamp) wird gestartet → <path>.ots.
   OTS-Fehler sind nicht fristrelevant; es wird nur gewarnt.
   Das .ots wird später per `ots upgrade <path>.ots` vervollständigt,
   sobald Bitcoin die Transaktion bestätigt hat.

issue_time(path) liest <path>.freetsa.tsr und <path>.digicert.tsr,
prüft beide Signaturen mit openssl ts -verify gegen die Zertifikate in
proofs/ (dieselben Befehle wie in proofs/VERIFY.md) und gibt den FRÜHESTEN
gültig verifizierten Zeitstempel als UTC-aware datetime zurück.
Schlägt die Verifikation beider Token fehl, wird None zurückgegeben.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import struct
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# Certificates directory (relative to this file: ../../proofs/)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PROOFS_DIR = _REPO_ROOT / "proofs"

FREETSA_URL = "https://freetsa.org/tsr"
DIGICERT_URL = "http://timestamp.digicert.com"


# ---------------------------------------------------------------------------
# Internal helpers – wrapped so tests can monkeypatch them
# ---------------------------------------------------------------------------

def _http_post(url: str, data: bytes, content_type: str, timeout: int = 30) -> bytes:
    """POST binary data to a TSA URL and return the raw response body."""
    resp = requests.post(
        url,
        data=data,
        headers={"Content-Type": content_type},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.content


def _ots_stamp(path: Path) -> None:
    """Run `ots stamp <path>`.  Caller catches exceptions."""
    ots_bin = shutil.which("ots")
    if ots_bin is None:
        raise FileNotFoundError("ots binary not found in PATH")
    subprocess.run([ots_bin, "stamp", str(path)], check=True, capture_output=True)


def _openssl_verify(data_path: Path, tsr_path: Path, cafile: Path,
                    untrusted: Path | None = None) -> bool:
    """Return True iff openssl ts -verify reports 'Verification: OK'."""
    cmd = [
        "openssl", "ts", "-verify",
        "-data", str(data_path),
        "-in", str(tsr_path),
        "-CAfile", str(cafile),
    ]
    if untrusted is not None:
        cmd += ["-untrusted", str(untrusted)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    combined = result.stdout + result.stderr
    return "Verification: OK" in combined


def _openssl_ts_time(tsr_path: Path) -> datetime | None:
    """
    Extract the timestamp from a .tsr file using openssl ts -reply -text.
    Returns a UTC-aware datetime or None on failure.
    """
    result = subprocess.run(
        ["openssl", "ts", "-reply", "-in", str(tsr_path), "-text"],
        capture_output=True, text=True,
    )
    combined = result.stdout + result.stderr
    # Line like: "Time stamp: Sep 27 11:24:12 2026 GMT"
    m = re.search(r"Time stamp:\s+(.+)", combined)
    if not m:
        return None
    raw = m.group(1).strip()
    try:
        dt = datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def freeze_file(path: str | Path) -> None:
    """
    Freeze *path* with SHA-256, two RFC-3161 TSA tokens, and OpenTimestamps.

    Files written next to *path*:
      <path>.sha256        – SHA-256 hex digest in sha256sum format
      <path>.freetsa.tsr   – RFC-3161 token from FreeTSA
      <path>.digicert.tsr  – RFC-3161 token from DigiCert
      <path>.ots           – OpenTimestamps calendar file (to be upgraded later)

    Raises
    ------
    RuntimeError
        When both TSA requests fail.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    # --- SHA-256 ---------------------------------------------------------
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sha256_path = Path(str(path) + ".sha256")
    sha256_path.write_text(f"{digest}  {path.name}\n")
    logger.info("SHA-256: %s  %s", digest, path.name)

    # --- Build TSQ (openssl ts -query) -----------------------------------
    with tempfile.NamedTemporaryFile(suffix=".tsq", delete=False) as tmp:
        tsq_path = Path(tmp.name)

    subprocess.run(
        [
            "openssl", "ts", "-query",
            "-sha256",
            "-digest", digest,
            "-cert",
            "-out", str(tsq_path),
        ],
        check=True,
        capture_output=True,
    )
    tsq_bytes = tsq_path.read_bytes()
    tsq_path.unlink(missing_ok=True)

    # --- TSA requests ----------------------------------------------------
    tsa_results: dict[str, bytes] = {}
    tsa_errors: dict[str, str] = {}

    for name, url in [("freetsa", FREETSA_URL), ("digicert", DIGICERT_URL)]:
        try:
            raw = _http_post(url, tsq_bytes, "application/timestamp-query")
            out_path = Path(f"{path}.{name}.tsr")
            out_path.write_bytes(raw)
            tsa_results[name] = raw
            logger.info("TSA %s: token saved to %s", name, out_path)
        except Exception as exc:
            tsa_errors[name] = str(exc)
            logger.warning("TSA %s failed: %s", name, exc)

    if not tsa_results:
        raise RuntimeError(
            f"Both TSA requests failed:\n"
            f"  FreeTSA: {tsa_errors.get('freetsa', 'unknown')}\n"
            f"  DigiCert: {tsa_errors.get('digicert', 'unknown')}"
        )

    # --- OpenTimestamps --------------------------------------------------
    try:
        _ots_stamp(path)
        logger.info("OTS: stamp created (%s.ots)", path)
    except Exception as exc:
        logger.warning("OTS stamp failed (not fristrelevant): %s", exc)


def issue_time(path: str | Path) -> datetime | None:
    """
    Verify the RFC-3161 tokens for *path* and return the earliest valid timestamp.

    Verification uses the same openssl commands as proofs/VERIFY.md:
      - FreeTSA:  -CAfile proofs/freetsa_cacert.pem
      - DigiCert: -CAfile proofs/digicert_trusted_root_g4.pem
                  -untrusted proofs/digicert_certs.pem

    Returns
    -------
    datetime | None
        The earliest UTC timestamp that could be verified, or None if neither
        token is valid or present.
    """
    path = Path(path)

    tsa_configs = [
        (
            "freetsa",
            Path(f"{path}.freetsa.tsr"),
            _PROOFS_DIR / "freetsa_cacert.pem",
            None,
        ),
        (
            "digicert",
            Path(f"{path}.digicert.tsr"),
            _PROOFS_DIR / "digicert_trusted_root_g4.pem",
            _PROOFS_DIR / "digicert_certs.pem",
        ),
    ]

    timestamps: list[datetime] = []
    for name, tsr_path, cafile, untrusted in tsa_configs:
        if not tsr_path.exists():
            logger.debug("TSR not found: %s", tsr_path)
            continue
        if not _openssl_verify(path, tsr_path, cafile, untrusted):
            logger.warning("TSA %s verification FAILED for %s", name, path)
            continue
        ts = _openssl_ts_time(tsr_path)
        if ts is not None:
            logger.info("TSA %s: verified timestamp %s", name, ts)
            timestamps.append(ts)

    if not timestamps:
        return None
    return min(timestamps)

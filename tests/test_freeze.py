"""Tests for swcast.freeze – no network access."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from swcast.freeze import freeze_file, issue_time, _openssl_ts_time, _parse_ts_time_string

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
PREREG = REPO_ROOT / "PREREGISTRATION.md"
FREETSA_TSR = REPO_ROOT / "PREREGISTRATION.md.freetsa.tsr"
DIGICERT_TSR = REPO_ROOT / "PREREGISTRATION.md.digicert.tsr"

# Expected timestamp from both TSRs
EXPECTED_TS = datetime(2026, 9, 27, 11, 24, 12, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Tests for _openssl_ts_time (uses real TSR files – no network)
# ---------------------------------------------------------------------------

def test_openssl_ts_time_freetsa():
    """Parse real FreeTSA token – expected 2026-09-27 11:24:12 UTC."""
    assert FREETSA_TSR.exists(), "FreeTSA TSR fixture missing"
    ts = _openssl_ts_time(FREETSA_TSR)
    assert ts == EXPECTED_TS


def test_openssl_ts_time_digicert():
    """Parse real DigiCert token – expected 2026-09-27 11:24:12 UTC."""
    assert DIGICERT_TSR.exists(), "DigiCert TSR fixture missing"
    ts = _openssl_ts_time(DIGICERT_TSR)
    assert ts == EXPECTED_TS


def test_parse_ts_time_string_fractional_seconds():
    """Some TSAs emit sub-second precision; it must not be dropped as invalid."""
    ts = _parse_ts_time_string("Sep 27 11:24:12.123 2026 GMT")
    assert ts == EXPECTED_TS


def test_parse_ts_time_string_no_fraction_still_works():
    ts = _parse_ts_time_string("Sep 27 11:24:12 2026 GMT")
    assert ts == EXPECTED_TS


def test_parse_ts_time_string_garbage_returns_none():
    assert _parse_ts_time_string("not a timestamp") is None


# ---------------------------------------------------------------------------
# Tests for issue_time (real on-disk TSRs, openssl run locally – no network)
# ---------------------------------------------------------------------------

def test_issue_time_real_tsr():
    """
    issue_time on PREREGISTRATION.md with the committed TSRs must return
    2026-09-27 11:24:12 UTC.
    """
    assert PREREG.exists(), "PREREGISTRATION.md missing"
    ts = issue_time(PREREG)
    assert ts == EXPECTED_TS


def test_issue_time_missing_tsr(tmp_path):
    """When no TSRs exist, issue_time returns None."""
    dummy = tmp_path / "dummy.txt"
    dummy.write_text("hello")
    assert issue_time(dummy) is None


def test_issue_time_tampered_file(tmp_path):
    """A tampered file must fail verification → issue_time returns None."""
    tampered = tmp_path / "tampered.md"
    tampered.write_bytes(PREREG.read_bytes() + b"\ntampered!\n")

    # Copy real TSRs next to tampered file
    (tmp_path / "tampered.md.freetsa.tsr").write_bytes(FREETSA_TSR.read_bytes())
    (tmp_path / "tampered.md.digicert.tsr").write_bytes(DIGICERT_TSR.read_bytes())

    ts = issue_time(tampered)
    assert ts is None


# ---------------------------------------------------------------------------
# Tests for freeze_file (monkeypatched – no network)
# ---------------------------------------------------------------------------

def _make_fake_tsr() -> bytes:
    """Return a minimal DER-encoded TSR (just enough bytes to write)."""
    return b"\x30\x00"  # empty SEQUENCE


@patch("swcast.freeze.issue_time")
@patch("swcast.freeze._ots_stamp")
@patch("swcast.freeze._http_post")
def test_freeze_file_writes_sha256_and_tsrs(mock_post, mock_ots, mock_issue_time, tmp_path):
    """freeze_file writes .sha256, .freetsa.tsr, .digicert.tsr."""
    target = tmp_path / "output.json"
    target.write_text('{"foo": 1}')
    expected_digest = hashlib.sha256(target.read_bytes()).hexdigest()

    # Fake TSR response (content doesn't need to be valid for this test)
    mock_post.return_value = _make_fake_tsr()
    mock_issue_time.return_value = EXPECTED_TS

    freeze_file(target)

    sha256_file = tmp_path / "output.json.sha256"
    assert sha256_file.exists()
    content = sha256_file.read_text()
    assert expected_digest in content
    assert "output.json" in content

    assert (tmp_path / "output.json.freetsa.tsr").exists()
    assert (tmp_path / "output.json.digicert.tsr").exists()


@patch("swcast.freeze.issue_time")
@patch("swcast.freeze._ots_stamp")
@patch("swcast.freeze._http_post")
def test_freeze_file_ots_failure_is_warning(mock_post, mock_ots, mock_issue_time, tmp_path):
    """OTS failure must not raise – only a warning."""
    target = tmp_path / "data.txt"
    target.write_text("some data")
    mock_post.return_value = _make_fake_tsr()
    mock_issue_time.return_value = EXPECTED_TS
    mock_ots.side_effect = FileNotFoundError("ots not found")

    # Must NOT raise
    freeze_file(target)


@patch("swcast.freeze.issue_time")
@patch("swcast.freeze._ots_stamp")
@patch("swcast.freeze._http_post")
def test_freeze_file_one_tsa_fails(mock_post, mock_ots, mock_issue_time, tmp_path):
    """If one TSA fails but the other succeeds and verifies, no exception is raised."""
    target = tmp_path / "data.txt"
    target.write_text("data")
    mock_issue_time.return_value = EXPECTED_TS

    call_count = 0

    def side_effect(url, data, content_type, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("FreeTSA unavailable")
        return _make_fake_tsr()

    mock_post.side_effect = side_effect

    freeze_file(target)  # must not raise
    assert call_count == 2


@patch("swcast.freeze._ots_stamp")
@patch("swcast.freeze._http_post")
def test_freeze_file_both_tsas_fail_raises(mock_post, mock_ots, tmp_path):
    """If both TSAs fail, RuntimeError is raised."""
    target = tmp_path / "data.txt"
    target.write_text("data")
    mock_post.side_effect = OSError("network error")

    with pytest.raises(RuntimeError, match="Both TSA requests failed"):
        freeze_file(target)


@patch("swcast.freeze.issue_time")
@patch("swcast.freeze._ots_stamp")
@patch("swcast.freeze._http_post")
def test_freeze_file_rejected_token_raises(mock_post, mock_ots, mock_issue_time, tmp_path):
    """
    A TSA can answer HTTP 200 with a rejected/invalid token. freeze_file must
    not treat that as success: it calls issue_time and raises if nothing
    verified, instead of silently leaving unverifiable .tsr files behind.
    """
    target = tmp_path / "data.txt"
    target.write_text("data")
    mock_post.return_value = _make_fake_tsr()
    mock_issue_time.return_value = None  # neither token could be verified

    with pytest.raises(RuntimeError, match="No TSA token could be verified"):
        freeze_file(target)
    mock_ots.assert_not_called()


@patch("swcast.freeze.issue_time")
@patch("swcast.freeze._ots_stamp")
@patch("swcast.freeze._http_post")
def test_freeze_file_deletes_stale_tsr_before_requesting(mock_post, mock_ots, mock_issue_time, tmp_path):
    """A leftover .tsr from a prior partial run must not survive a failed refetch."""
    target = tmp_path / "data.txt"
    target.write_text("data")

    stale = tmp_path / "data.txt.freetsa.tsr"
    stale.write_bytes(b"\x30\x00\xff\xff")  # stale/corrupt token from a prior run

    mock_issue_time.return_value = EXPECTED_TS

    def side_effect(url, data, content_type, **kw):
        if "freetsa" in url:
            raise OSError("FreeTSA unavailable")
        return _make_fake_tsr()

    mock_post.side_effect = side_effect

    freeze_file(target)

    assert not stale.exists()


def test_freeze_file_missing_file():
    """freeze_file raises FileNotFoundError for non-existent path."""
    with pytest.raises(FileNotFoundError):
        freeze_file("/nonexistent/path/file.txt")

"""Tests for swcast.net.get_with_retry – no real network, no real sleeping."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from swcast.net import get_with_retry


def _resp(status_code=200):
    r = MagicMock()
    r.status_code = status_code
    return r


@patch("requests.get")
def test_succeeds_first_try_no_retry(mock_get):
    mock_get.return_value = _resp(200)
    sleep = MagicMock()

    resp = get_with_retry("http://x", timeout=5, sleep=sleep)

    assert resp.status_code == 200
    mock_get.assert_called_once()
    sleep.assert_not_called()


@patch("requests.get")
def test_retries_on_timeout_then_succeeds(mock_get):
    mock_get.side_effect = [requests.exceptions.Timeout("timed out"), _resp(200)]
    sleep = MagicMock()

    resp = get_with_retry("http://x", timeout=5, sleep=sleep)

    assert resp.status_code == 200
    assert mock_get.call_count == 2
    sleep.assert_called_once_with(10)  # first backoff


@patch("requests.get")
def test_retries_on_connection_error_then_succeeds(mock_get):
    mock_get.side_effect = [requests.exceptions.ConnectionError("refused"), _resp(200)]
    sleep = MagicMock()

    resp = get_with_retry("http://x", sleep=sleep)

    assert resp.status_code == 200
    assert mock_get.call_count == 2


@patch("requests.get")
def test_retries_on_5xx_then_succeeds(mock_get):
    mock_get.side_effect = [_resp(503), _resp(200)]
    sleep = MagicMock()

    resp = get_with_retry("http://x", sleep=sleep)

    assert resp.status_code == 200
    assert mock_get.call_count == 2
    sleep.assert_called_once_with(10)


@patch("requests.get")
def test_does_not_retry_on_4xx(mock_get):
    mock_get.return_value = _resp(404)
    sleep = MagicMock()

    resp = get_with_retry("http://x", sleep=sleep)

    assert resp.status_code == 404
    mock_get.assert_called_once()
    sleep.assert_not_called()


@patch("requests.get")
def test_uses_exact_backoff_sequence_10_30_90(mock_get):
    mock_get.side_effect = [
        requests.exceptions.Timeout("t1"),
        requests.exceptions.Timeout("t2"),
        requests.exceptions.Timeout("t3"),
        _resp(200),
    ]
    sleep = MagicMock()

    resp = get_with_retry("http://x", sleep=sleep)

    assert resp.status_code == 200
    assert mock_get.call_count == 4
    assert [c.args[0] for c in sleep.call_args_list] == [10, 30, 90]


@patch("requests.get")
def test_raises_after_4_failed_attempts_on_timeout(mock_get):
    mock_get.side_effect = requests.exceptions.Timeout("still down")
    sleep = MagicMock()

    with pytest.raises(requests.exceptions.Timeout):
        get_with_retry("http://x", sleep=sleep)

    assert mock_get.call_count == 4
    assert sleep.call_count == 3


@patch("requests.get")
def test_returns_5xx_response_after_exhausting_retries(mock_get):
    mock_get.return_value = _resp(500)
    sleep = MagicMock()

    resp = get_with_retry("http://x", sleep=sleep)  # caller's raise_for_status() will raise

    assert resp.status_code == 500
    assert mock_get.call_count == 4


@patch("requests.post")
def test_post_dispatches_to_requests_post(mock_post):
    mock_post.return_value = _resp(200)
    sleep = MagicMock()

    resp = get_with_retry("http://x", method="POST", data=b"abc", sleep=sleep)

    assert resp.status_code == 200
    mock_post.assert_called_once_with("http://x", data=b"abc")

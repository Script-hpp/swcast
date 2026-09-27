"""
net.py – shared retry wrapper for HTTP calls (get_with_retry).

Used by every network fetch EXCEPT the FTP-based historical RSGA warehouse
download (fetch_historical_rsga uses urllib.request.urlopen directly, since
requests can't do ftp:// — see fetch/swpc.py):
  - GFZ nowcast/definitive Kp (fetch/kp.py)
  - SWPC rtsw live solar wind (fetch/solarwind.py)
  - SWPC live products: solar_probabilities, Kp forecast, daypre, sgarf
    (fetch/swpc.py)
  - RFC-3161 TSA POST requests (freeze.py)

Reason: a live run on GitHub Actions saw a 30s ConnectTimeout against
kp.gfz.de, while the same endpoint answered locally in 0.1-0.3s at the same
time — a sporadic network blip between the runner and GFZ, not GFZ actually
being down. The daily run gets exactly one shot at each day (PREREGISTRATION
§6); it must not lose that shot to a transient timeout.
"""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

# Wait 10s / 30s / 90s between attempts -> 4 attempts total.
DEFAULT_BACKOFFS = (10, 30, 90)


def get_with_retry(
    url: str,
    method: str = "GET",
    backoffs: tuple[float, ...] = DEFAULT_BACKOFFS,
    sleep=time.sleep,
    **kwargs,
) -> requests.Response:
    """
    requests.get/requests.post(url, **kwargs) depending on `method`, retried
    on timeouts, connection errors, and HTTP 5xx only. A 4xx is a
    client-side problem a retry can't fix, so it is returned immediately
    (the caller's own .raise_for_status() handles it as usual).

    Dispatches to requests.get/requests.post (rather than requests.request)
    so call sites and their tests can keep mocking `requests.get`/`.post`
    directly.

    `sleep` is injectable for tests; production code never passes it.
    """
    request_fn = getattr(requests, method.lower())
    attempts = len(backoffs) + 1

    for attempt in range(attempts):
        is_last = attempt == attempts - 1
        try:
            resp = request_fn(url, **kwargs)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if is_last:
                raise
            wait = backoffs[attempt]
            logger.warning(
                "get_with_retry: attempt %d/%d for %s %s failed (%s); retrying in %ds",
                attempt + 1, attempts, method, url, exc, wait,
            )
            sleep(wait)
            continue

        if resp.status_code >= 500:
            if is_last:
                return resp  # caller's raise_for_status() will raise on this
            wait = backoffs[attempt]
            logger.warning(
                "get_with_retry: attempt %d/%d for %s %s got HTTP %d; retrying in %ds",
                attempt + 1, attempts, method, url, resp.status_code, wait,
            )
            sleep(wait)
            continue

        return resp

    raise AssertionError("unreachable")  # loop always returns or raises above

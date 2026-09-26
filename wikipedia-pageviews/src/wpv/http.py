"""HTTP access to Wikimedia APIs with a persistent SQLite cache.

Pageviews for completed months never change, so those responses are cached
forever; anything touching the current month (or search/Wikidata lookups)
gets a TTL. This makes follow-up questions ("now add Slovak", "show 5 years")
cost only the requests that are actually new.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import requests

# Wikimedia's User-Agent policy asks for a way to contact the tool's operator.
DEFAULT_CONTACT = "https://github.com/nick-mad/wikipedia-pageviews-skill"
USER_AGENT = (
    "wikipedia-pageviews-skill/0.1 "
    f"(+{os.environ.get('WPV_CONTACT', DEFAULT_CONTACT)}) python-requests"
)

FOREVER = None  # ttl marker: never expires


class NotFound(Exception):
    """The API answered 404 (e.g. an article with no views in the range)."""


def cache_dir() -> Path:
    base = os.environ.get("WPV_CACHE_DIR") or os.path.join(
        os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
        "wikipedia-pageviews",
    )
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


class Client:
    def __init__(self, cache_path: Path | None = None, offline: bool = False):
        self.cache_path = cache_path or cache_dir() / "cache.sqlite"
        self.offline = offline
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.cache_path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS responses ("
            " url TEXT PRIMARY KEY, status INTEGER, body TEXT,"
            " fetched_at REAL, expires_at REAL)"
        )
        self._db.commit()
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self.stats = {"cache_hits": 0, "network": 0}

    def _cached(self, url: str):
        with self._lock:
            row = self._db.execute(
                "SELECT status, body, expires_at FROM responses WHERE url = ?", (url,)
            ).fetchone()
        if row is None:
            return None
        status, body, expires_at = row
        if expires_at is not None and expires_at < time.time() and not self.offline:
            return None
        return status, body

    def _store(self, url: str, status: int, body: str, ttl: float | None):
        expires = None if ttl is FOREVER else time.time() + ttl
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?)",
                (url, status, body, time.time(), expires),
            )
            self._db.commit()

    def get_json(self, url: str, ttl: float | None = 7 * 86400) -> dict:
        """GET a JSON document. Raises NotFound on 404 (404s are cached too)."""
        hit = self._cached(url)
        if hit is not None:
            self.stats["cache_hits"] += 1
            status, body = hit
        else:
            if self.offline:
                raise RuntimeError(f"offline mode and not cached: {url}")
            status, body = self._fetch(url)
            self.stats["network"] += 1
            if status in (200, 404):
                self._store(url, status, body, ttl)
        if status == 404:
            raise NotFound(url)
        return json.loads(body)

    def _fetch(self, url: str) -> tuple[int, str]:
        delay = 1.0
        for attempt in range(5):
            try:
                resp = self._session.get(url, timeout=30)
            except requests.RequestException as exc:
                if attempt == 4:
                    raise RuntimeError(f"network error for {url}: {exc}") from exc
            else:
                if resp.status_code in (200, 404):
                    return resp.status_code, resp.text
                if resp.status_code not in (429, 500, 502, 503, 504):
                    raise RuntimeError(
                        f"HTTP {resp.status_code} for {url}: {resp.text[:200]}"
                    )
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, float(retry_after))
            time.sleep(delay)
            delay *= 2
        raise RuntimeError(f"giving up after retries: {url}")

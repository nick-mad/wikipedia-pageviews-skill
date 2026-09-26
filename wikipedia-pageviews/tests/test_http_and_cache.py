"""Network layer: retries, caching of immutable months, cheap follow-up queries."""

import datetime as dt
import json
from pathlib import Path

import pytest

from wpv import analysis, http

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, status, text="{}", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


def test_retries_on_429_then_succeeds(tmp_path, monkeypatch):
    client = http.Client(tmp_path / "c.sqlite")
    replies = iter([FakeResponse(429, headers={"Retry-After": "1"}),
                    FakeResponse(503), FakeResponse(200, '{"ok": 1}')])
    monkeypatch.setattr(client._session, "get", lambda url, timeout: next(replies))
    sleeps = []
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    assert client.get_json("https://example.org/x") == {"ok": 1}
    assert sleeps == [1.0, 2.0]  # Retry-After honoured, then exponential backoff


def test_gives_up_on_permanent_error(tmp_path, monkeypatch):
    client = http.Client(tmp_path / "c.sqlite")
    monkeypatch.setattr(client._session, "get", lambda url, timeout: FakeResponse(400, "bad"))
    with pytest.raises(RuntimeError, match="HTTP 400"):
        client.get_json("https://example.org/x")


def test_completed_months_are_cached_forever(tmp_path, monkeypatch):
    client = http.Client(tmp_path / "c.sqlite")
    calls = []
    monkeypatch.setattr(client._session, "get",
                        lambda url, timeout: calls.append(url) or FakeResponse(200, '{"a": 1}'))
    client.get_json("https://example.org/old", ttl=http.FOREVER)
    monkeypatch.setattr(http.time, "time", lambda: 10 ** 12)  # far future
    client.get_json("https://example.org/old", ttl=http.FOREVER)
    assert len(calls) == 1


def test_adding_a_language_only_fetches_the_new_language(tmp_path, monkeypatch):
    """'Now add Czech' after a Polish-only analysis must not refetch Polish data."""
    recorded = {r["url"]: r for r in json.loads(
        (FIXTURES / "intermittent_fasting_pl_cs.json").read_text())}
    fetched = []

    def fake_fetch(self, url):
        fetched.append(url)
        r = recorded[url]
        return r["status"], json.dumps(r["body"], ensure_ascii=False)

    monkeypatch.setattr(http.Client, "_fetch", fake_fetch)
    client = http.Client(tmp_path / "c.sqlite")
    topic = analysis.parse_topic("IF=Q1666254,pl:Głodówka lecznicza")
    period = (dt.date(2024, 9, 1), dt.date(2026, 8, 31))

    analysis.build(client, [topic], ["pl"], *period)
    first = set(fetched)
    fetched.clear()
    analysis.build(client, [topic], ["pl", "cs"], *period)
    second = set(fetched)

    assert first and second
    assert not first & second  # nothing fetched twice
    pageview_urls = [u for u in second if "/pageviews/" in u]
    assert pageview_urls and all("cs.wikipedia" in u for u in pageview_urls)

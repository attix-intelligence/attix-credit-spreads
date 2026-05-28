"""Tests for shared.tradealgo_client.TradeAlgoClient.

Covers: header construction, retry on 429 / 5xx, JSON-not-zip wire format,
intrinsic-date inference, atomic cache write, from_cache offline read,
DataFetchError on permanent failure.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from shared.exceptions import DataFetchError
from shared.tradealgo_client import TradeAlgoClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _fake_snapshot(snap_date: str = "2026-05-27") -> dict:
    """Minimal but shape-correct snapshot bundle for unit tests."""
    return {
        "live-options/snapshot.json": {
            "date": f"{snap_date}T00:00:00.000Z",
            "call_count": 100, "put_count": 80, "flow_sentiment": 0.55,
        },
        "movement/darkflow-large.json": {
            "trending_up": [
                {
                    "ticker": "META", "multiplier": "1.96",
                    "dollar_value": "6903451023.0", "has_options": True,
                    "options": {
                        "date": f"{snap_date}T00:00:00.000Z",
                        "call_flow": 0.79, "flow_sentiment": 0.79,
                        "put_to_call": 0.26, "call_total_prem": 12345,
                        "put_total_prem": 678,
                    },
                    "ats": {"compared": {"day_dollar_volume": 145.6}},
                    "perf": 4.2, "market_cap": "1500000000000",
                    "last_price": 612.5,
                },
            ],
            "trending_down": [],
        },
        "movement/darkflow-medium.json": {"trending_up": [], "trending_down": []},
        "movement/darkflow-small.json":  {"trending_up": [], "trending_down": []},
    }


def _mock_response(status: int = 200, json_body: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.headers = {"content-type": "application/json"}
    resp.text = json.dumps(json_body) if json_body is not None else ""
    resp.json.return_value = json_body if json_body is not None else {}
    return resp


# ---------------------------------------------------------------------------
# Headers + auth
# ---------------------------------------------------------------------------

class TestHeaders:
    def test_headers_have_required_keys(self, tmp_path):
        c = TradeAlgoClient(api_key="K123", cache_dir=tmp_path)
        h = c._headers()
        assert h["x-api-key"] == "K123"
        assert h["x-auth-provider"] == "apikey"
        assert "user-agent" in h and h["user-agent"]

    def test_missing_key_raises_on_fetch(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TRADEALGO_API_KEY", raising=False)
        c = TradeAlgoClient(api_key="", cache_dir=tmp_path)
        with pytest.raises(DataFetchError, match="not configured"):
            c.fetch_snapshot()

    def test_env_var_is_picked_up(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TRADEALGO_API_KEY", "from-env")
        c = TradeAlgoClient(cache_dir=tmp_path)
        assert c._headers()["x-api-key"] == "from-env"


# ---------------------------------------------------------------------------
# Fetch success path
# ---------------------------------------------------------------------------

class TestFetchSnapshot:
    def test_get_200_returns_parsed_dict(self, tmp_path):
        body = _fake_snapshot()
        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        with patch.object(c._session, "request",
                          return_value=_mock_response(200, body)) as req:
            data = c.fetch_snapshot()
        assert data == body
        kwargs = req.call_args.kwargs
        assert kwargs["method"] == "GET"
        assert kwargs["url"].endswith("/reports/snapshot")

    def test_writes_atomic_cache(self, tmp_path):
        body = _fake_snapshot("2026-05-27")
        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        with patch.object(c._session, "request",
                          return_value=_mock_response(200, body)):
            c.fetch_snapshot()
        path = tmp_path / "2026-05-27" / "snapshot.json"
        assert path.exists()
        # No leftover .tmp
        assert not list(tmp_path.rglob("*.tmp"))
        # Roundtrip equivalence
        with path.open() as f:
            assert json.load(f) == body

    def test_returns_cached_when_today_exists_and_no_force(self, tmp_path, monkeypatch):
        # Stub today→ 2026-05-27 so cache is "today"
        from shared import tradealgo_client as mod
        monkeypatch.setattr(mod, "_today_utc", lambda: date(2026, 5, 27))
        cached_path = tmp_path / "2026-05-27" / "snapshot.json"
        cached_path.parent.mkdir(parents=True)
        body_cached = {"cached": True}
        cached_path.write_text(json.dumps(body_cached))

        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        with patch.object(c._session, "request") as req:
            data = c.fetch_snapshot()
        assert data == body_cached
        req.assert_not_called()

    def test_force_refresh_skips_cache(self, tmp_path, monkeypatch):
        from shared import tradealgo_client as mod
        monkeypatch.setattr(mod, "_today_utc", lambda: date(2026, 5, 27))
        cached_path = tmp_path / "2026-05-27" / "snapshot.json"
        cached_path.parent.mkdir(parents=True)
        cached_path.write_text(json.dumps({"cached": True}))

        body_new = _fake_snapshot("2026-05-27")
        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        with patch.object(c._session, "request",
                          return_value=_mock_response(200, body_new)) as req:
            data = c.fetch_snapshot(force_refresh=True)
        assert data == body_new
        req.assert_called_once()


# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------

class TestRetries:
    def test_429_then_200_recovers(self, tmp_path, monkeypatch):
        # No sleep in tests
        monkeypatch.setattr("shared.tradealgo_client.time.sleep", lambda *_: None)
        body = _fake_snapshot()
        seq = [_mock_response(429, {"error": "throttled"}), _mock_response(200, body)]
        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        with patch.object(c._session, "request", side_effect=seq) as req:
            data = c.fetch_snapshot()
        assert data == body
        assert req.call_count == 2

    def test_5xx_exhausts_then_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shared.tradealgo_client.time.sleep", lambda *_: None)
        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        with patch.object(c._session, "request",
                          return_value=_mock_response(503, {"e": "down"})):
            with pytest.raises(DataFetchError, match="HTTP 503"):
                c.fetch_snapshot()

    def test_transport_error_then_recovers(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shared.tradealgo_client.time.sleep", lambda *_: None)
        body = _fake_snapshot()
        seq = [requests.ConnectionError("boom"), _mock_response(200, body)]
        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        with patch.object(c._session, "request", side_effect=seq):
            data = c.fetch_snapshot()
        assert data == body

    def test_non_retryable_4xx_raises_immediately(self, tmp_path, monkeypatch):
        monkeypatch.setattr("shared.tradealgo_client.time.sleep", lambda *_: None)
        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        with patch.object(c._session, "request",
                          return_value=_mock_response(403, {"e": "no"})) as req:
            with pytest.raises(DataFetchError, match="HTTP 403"):
                c.fetch_snapshot()
        # No retry on 403
        assert req.call_count == 1


# ---------------------------------------------------------------------------
# POST trigger_refresh
# ---------------------------------------------------------------------------

class TestTriggerRefresh:
    def test_post_returns_ack(self, tmp_path):
        ack = {"status": "ok", "files": 31, "sizeBytes": 679638}
        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        with patch.object(c._session, "request",
                          return_value=_mock_response(200, ack)) as req:
            out = c.trigger_refresh()
        assert out == ack
        assert req.call_args.kwargs["method"] == "POST"


# ---------------------------------------------------------------------------
# from_cache classmethod
# ---------------------------------------------------------------------------

class TestFromCache:
    def test_reads_existing_cache(self, tmp_path):
        path = tmp_path / "2026-05-27" / "snapshot.json"
        path.parent.mkdir()
        body = {"hello": "world"}
        path.write_text(json.dumps(body))
        assert TradeAlgoClient.from_cache("2026-05-27", cache_dir=tmp_path) == body

    def test_missing_cache_raises_filenotfound(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            TradeAlgoClient.from_cache("2025-01-01", cache_dir=tmp_path)

    def test_accepts_date_object(self, tmp_path):
        path = tmp_path / "2026-05-27" / "snapshot.json"
        path.parent.mkdir()
        path.write_text("{}")
        assert TradeAlgoClient.from_cache(date(2026, 5, 27), cache_dir=tmp_path) == {}


# ---------------------------------------------------------------------------
# Date inference
# ---------------------------------------------------------------------------

class TestDateInference:
    def test_infers_from_live_options(self, tmp_path):
        body = _fake_snapshot("2026-04-15")
        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        with patch.object(c._session, "request",
                          return_value=_mock_response(200, body)):
            c.fetch_snapshot()
        assert (tmp_path / "2026-04-15" / "snapshot.json").exists()

    def test_falls_back_to_today_when_dateless(self, tmp_path, monkeypatch):
        from shared import tradealgo_client as mod
        monkeypatch.setattr(mod, "_today_utc", lambda: date(2026, 1, 1))
        body = {"misc/other.json": {"no": "date"}}
        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        with patch.object(c._session, "request",
                          return_value=_mock_response(200, body)):
            c.fetch_snapshot()
        assert (tmp_path / "2026-01-01" / "snapshot.json").exists()


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------

class TestResponseValidation:
    def test_non_json_body_raises(self, tmp_path):
        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        bad = MagicMock(spec=requests.Response)
        bad.status_code = 200
        bad.headers = {"content-type": "application/zip"}
        bad.json.side_effect = ValueError("not json")
        bad.text = "PK\x03\x04..."
        with patch.object(c._session, "request", return_value=bad):
            with pytest.raises(DataFetchError, match="not JSON"):
                c.fetch_snapshot()

    def test_list_top_level_rejected(self, tmp_path):
        c = TradeAlgoClient(api_key="K", cache_dir=tmp_path)
        with patch.object(c._session, "request",
                          return_value=_mock_response(200, ["unexpected"])):
            with pytest.raises(DataFetchError, match="unexpected top-level"):
                c.fetch_snapshot()

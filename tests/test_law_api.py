"""Tests for the law-api client (degradation contract + response normalization)."""

from __future__ import annotations

import httpx
import pytest

from src.law_api import client as law_api


def _mock(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://gw.test/v1")


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(law_api, "LAW_SEARCH_ENABLED", True)
    monkeypatch.setattr(law_api, "LAW_API_KEY", "test-key")
    monkeypatch.setattr(law_api, "LAW_API_MIN_INTERVAL", "0")
    monkeypatch.setattr(law_api, "LAW_API_MIN_INTERVAL", 0)


def test_disabled_means_no_requests(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"hits": []})

    monkeypatch.setattr(law_api, "LAW_SEARCH_ENABLED", False)
    assert law_api.search("x", client=_mock(handler)) == []
    assert law_api.get_law("1", client=_mock(handler)) is None
    assert calls == []


def test_search_flat_hits_with_key_header(enabled):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("apikey")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"hits": [
            {"law_id": "1048577", "title": "中华人民共和国民法典",
             "chunk_text": "抚养费…", "law_status": "有效", "score": 0.9},
        ]})

    hits = law_api.search("民法典 抚养费", client=_mock(handler))
    assert seen["auth"] == "test-key"
    assert seen["url"].endswith("/v1/search")
    assert hits == [{"law_id": "1048577", "title": "中华人民共和国民法典",
                     "chunk_text": "抚养费…", "law_status": "有效", "score": 0.9}]


def test_search_payload_nested_hits(enabled):
    def handler(request):
        return httpx.Response(200, json={"results": [
            {"score": 0.8, "payload": {"law_id": 7, "title": "旅游法",
                                       "chunk_text": "第五十七条…", "law_status": None}},
        ]})

    hits = law_api.search("旅游", client=_mock(handler))
    assert hits[0]["law_id"] == "7"  # numeric-looking ids preserved as strings
    assert hits[0]["chunk_text"].startswith("第五十七条")


def test_search_degrades_on_401_429_and_network(enabled, caplog):
    def unauthorized(request):
        return httpx.Response(401, text='{"message":"missing key"}')

    def throttled(request):
        return httpx.Response(429, text="rate limited")

    assert law_api.search("q", client=_mock(unauthorized)) == []
    assert law_api.search("q", client=_mock(throttled)) == []

    real_get = httpx.Client.send

    def boom(self, request, **kw):
        raise httpx.ConnectError("gateway down")

    monkey = httpx.Client
    try:
        httpx.Client.send = boom
        assert law_api.search("q", client=httpx.Client(base_url="https://gw.test")) == []
    finally:
        httpx.Client.send = real_get
    assert any("law-api search" in r.message for r in caplog.records)


def test_get_law_full_text_and_status(enabled):
    def handler(request):
        assert request.url.path.endswith("/laws/42")
        return httpx.Response(200, json={
            "law_id": "42", "title": "中华人民共和国民法典",
            "law_status": "有效", "content": "第一条 …\n第二条 …"})

    law = law_api.get_law("42", client=_mock(handler))
    assert law == {"law_id": "42", "title": "中华人民共和国民法典",
                   "status": "有效", "full_text": "第一条 …\n第二条 …"}


def test_get_law_unexpected_shape_degrades(enabled, caplog):
    def handler(request):
        return httpx.Response(200, json={"unexpected": True})

    assert law_api.get_law("42", client=_mock(handler)) is None
    assert any("laws/42 parse" in r.message for r in caplog.records)


def test_smoke_pass_and_fail(enabled, caplog):
    def good(request):
        return httpx.Response(200, json={"hits": [
            {"law_id": "9", "title": "解释", "chunk_text": "…抚养费…", "law_status": "有效"}]})

    def empty(request):
        return httpx.Response(200, json={"hits": []})

    assert law_api.smoke(client=_mock(good)) is True
    assert law_api.smoke(client=_mock(empty)) is False
    assert any("smoke check failed" in r.message for r in caplog.records)


def test_first_use_smoke_runs_once_and_caches(enabled, monkeypatch):
    law_api.reset_first_use_smoke()
    calls = []

    def fake_smoke():
        calls.append(1)
        return True

    monkeypatch.setattr(law_api, "smoke", fake_smoke)
    assert law_api.first_use_smoke() is True
    assert law_api.first_use_smoke() is True
    assert calls == [1]  # second call served from the cached verdict

    law_api.reset_first_use_smoke()

    def failing_smoke():
        calls.append(2)
        return False

    monkeypatch.setattr(law_api, "smoke", failing_smoke)
    assert law_api.first_use_smoke() is False
    law_api.reset_first_use_smoke()

"""Tests for authentication middleware."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock


@pytest.fixture
def client():
    """Create test client."""
    from fd_coding_law_bench_mcp.api.main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the lru_cache on get_settings so per-test patches take effect."""
    from fd_coding_law_bench_mcp.api import config
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def _make_settings(api_key_enabled, api_keys=None):
    """Build a lightweight settings stub matching APISettings fields."""
    from types import SimpleNamespace
    return SimpleNamespace(
        api_key_enabled=api_key_enabled,
        api_keys=api_keys,
        public_endpoints=["/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"],
    )


class TestAPIKeyAuthentication:
    """Tests for API key authentication middleware."""

    def test_auth_disabled_health_accessible(self, client):
        """Test health endpoint accessible when auth disabled (default)."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_auth_disabled_docs_accessible(self, client):
        """Test docs endpoint accessible when auth disabled."""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_auth_enabled_missing_key(self, client):
        """Test 401 when auth enabled but no API key provided."""
        with patch(
            "fd_coding_law_bench_mcp.api.middleware.get_settings",
            return_value=_make_settings(True, ["valid-key"]),
        ):
            # Health endpoint should still be accessible (public)
            assert client.get("/health").status_code == 200

            # Contract endpoint should require auth
            response = client.post(
                "/contracts/content",
                json={"contract_type": "sale"},
            )
            assert response.status_code == 401

    def test_auth_enabled_invalid_key(self, client):
        """Test 403 when auth enabled with invalid API key."""
        with patch(
            "fd_coding_law_bench_mcp.api.middleware.get_settings",
            return_value=_make_settings(True, ["valid-key"]),
        ):
            response = client.post(
                "/contracts/content",
                json={"contract_type": "sale"},
                headers={"X-API-Key": "invalid-key"},
            )
            assert response.status_code == 403

    def test_auth_enabled_valid_key(self, client):
        """Test successful request with valid API key."""
        mock_result = {
            "trace_id": "test",
            "contract_type": "sale",
            "format": "markdown",
            "body_text": "contract",
            "slots": [],
            "instructions": [],
            "law_refs": [],
            "tags_used": {},
        }
        with patch(
            "fd_coding_law_bench_mcp.api.middleware.get_settings",
            return_value=_make_settings(True, ["valid-key"]),
        ), patch(
            "fd_coding_law_bench_mcp.api.routes.contracts.contract_content",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = client.post(
                "/contracts/content",
                json={"contract_type": "sale"},
                headers={"X-API-Key": "valid-key"},
            )
            assert response.status_code == 200

    def test_auth_enabled_public_endpoints_bypass(self, client):
        """Test public endpoints bypass authentication."""
        with patch(
            "fd_coding_law_bench_mcp.api.middleware.get_settings",
            return_value=_make_settings(True, ["valid-key"]),
        ):
            # These should all work without API key
            assert client.get("/health").status_code == 200
            assert client.get("/docs").status_code == 200

    def test_auth_disabled_all_endpoints_accessible(self, client):
        """Test all endpoints accessible when auth disabled."""
        with patch(
            "fd_coding_law_bench_mcp.api.middleware.get_settings",
            return_value=_make_settings(False, None),
        ):
            # Contract endpoint should be accessible without key
            mock_result = {
                "trace_id": "test",
                "contract_type": "sale",
                "format": "markdown",
                "body_text": "contract",
                "slots": [],
                "instructions": [],
                "law_refs": [],
                "tags_used": {},
            }
            with patch(
                "fd_coding_law_bench_mcp.api.routes.contracts.contract_content",
                new_callable=AsyncMock,
                return_value=mock_result,
            ):
                response = client.post(
                    "/contracts/content",
                    json={"contract_type": "sale"},
                )
                assert response.status_code == 200

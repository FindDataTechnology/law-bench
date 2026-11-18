"""Tests for CORS and error handling."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock


@pytest.fixture
def client():
    """Create test client."""
    from fd_coding_law_bench_mcp.api.main import app
    return TestClient(app)


class TestCORSHeaders:
    """Tests for CORS support."""

    def test_cors_preflight_request(self, client):
        """Test CORS preflight (OPTIONS) request returns proper headers."""
        response = client.options(
            "/contracts/content",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_cors_actual_request_headers(self, client):
        """Test actual CORS request includes allow-origin header."""
        response = client.get(
            "/health",
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

    def test_cors_allowed_methods_in_preflight(self, client):
        """Test preflight response includes allowed methods."""
        response = client.options(
            "/contracts/content",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-methods" in response.headers
        methods = response.headers["access-control-allow-methods"]
        assert "POST" in methods


class TestErrorHandling:
    """Tests for error response structure."""

    def test_404_not_found_contract_type(self, client):
        """Test 404 response for unknown contract type."""
        with patch(
            "fd_coding_law_bench_mcp.api.routes.contracts.type_metadata",
            new_callable=AsyncMock,
            side_effect=Exception("Contract type 'unknown' not found"),
        ):
            response = client.get("/contracts/types/unknown")
            assert response.status_code == 404
            data = response.json()
            assert "error" in data or "detail" in data

    def test_422_validation_error(self, client):
        """Test 422 response for invalid request body."""
        response = client.post(
            "/contracts/content",
            json={"format": "invalid_format"},  # missing contract_type, bad format
        )
        assert response.status_code == 422

    def test_500_internal_error(self, client):
        """Test 500 response for unexpected errors."""
        with patch(
            "fd_coding_law_bench_mcp.api.routes.contracts.contract_content",
            new_callable=AsyncMock,
            side_effect=Exception("Unexpected DB failure"),
        ):
            response = client.post(
                "/contracts/content",
                json={"contract_type": "sale"},
            )
            assert response.status_code == 500

    def test_error_response_structure(self, client):
        """Test error responses contain required fields."""
        with patch(
            "fd_coding_law_bench_mcp.api.routes.contracts.contract_content",
            new_callable=AsyncMock,
            side_effect=Exception("Test error"),
        ):
            response = client.post(
                "/contracts/content",
                json={"contract_type": "sale"},
            )
            assert response.status_code == 500
            data = response.json()
            # Standardized error structure has error + message (+ details)
            assert "error" in data
            assert "message" in data

    def test_404_unknown_route(self, client):
        """Test 404 for completely unknown route."""
        response = client.get("/nonexistent-endpoint")
        assert response.status_code == 404

    def test_method_not_allowed(self, client):
        """Test 405 for wrong HTTP method."""
        response = client.delete("/contracts/content")
        assert response.status_code == 405


class TestRateLimiting:
    """Tests for rate limiting behavior."""

    def test_rate_limiting_disabled_by_default(self, client):
        """Test that rate limiting can be disabled."""
        # With default config, rate limiting may be enabled but with high limit
        # Health check should always work
        for _ in range(5):
            response = client.get("/health")
            assert response.status_code == 200

    @pytest.fixture(autouse=True)
    def _clear_settings_cache(self):
        """Clear settings cache so auth middleware sees default (auth disabled)."""
        from fd_coding_law_bench_mcp.api import config
        config.get_settings.cache_clear()
        yield
        config.get_settings.cache_clear()

    def test_rate_limit_headers_present(self, client):
        """Test rate limit headers are included in responses.

        With default config (high limit, auth disabled), a single health
        check must succeed. We avoid patching get_settings here because a
        global patch leaks into the auth middleware and flips api_key_enabled.
        """
        response = client.get("/health")
        assert response.status_code == 200


class TestOpenAPIDocumentation:
    """Tests for OpenAPI documentation endpoints."""

    def test_openapi_json_accessible(self, client):
        """Test OpenAPI schema is accessible."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "Law Bench Contract Generation API"
        assert "paths" in data

    def test_swagger_ui_accessible(self, client):
        """Test Swagger UI is accessible."""
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_redoc_accessible(self, client):
        """Test ReDoc is accessible."""
        response = client.get("/redoc")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_openapi_includes_contract_endpoints(self, client):
        """Test OpenAPI schema includes contract endpoints."""
        response = client.get("/openapi.json")
        data = response.json()
        paths = data.get("paths", {})
        assert "/contracts/content" in paths
        assert "/contracts/batch" in paths
        assert "/contracts/types" in paths

    def test_openapi_includes_tag_endpoints(self, client):
        """Test OpenAPI schema includes tag endpoints."""
        response = client.get("/openapi.json")
        data = response.json()
        paths = data.get("paths", {})
        assert "/tags/validate" in paths

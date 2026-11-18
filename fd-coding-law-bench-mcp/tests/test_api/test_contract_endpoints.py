"""Integration tests for contract endpoints with mocked DB."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture
def client():
    """Create test client with mocked dependencies."""
    from fd_coding_law_bench_mcp.api.main import app
    return TestClient(app)


@pytest.fixture
def mock_contract_content():
    """Mock the MCP contract_content tool."""
    mock_result = {
        "trace_id": "test-trace",
        "contract_type": "sale",
        "format": "markdown",
        "body_text": "## 当事人\n\n甲方：{{party_a}}",
        "slots": ["party_a", "party_b"],
        "instructions": [{"name": "party_a", "label": "甲方名称"}],
        "law_refs": [{"name": "民法典", "category": "statute"}],
        "tags_used": {"scenario": "农产品买卖", "stance": "balanced"},
    }
    with patch(
        "fd_coding_law_bench_mcp.api.routes.contracts.contract_content",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock:
        yield mock


@pytest.fixture
def mock_contract_batch():
    """Mock the MCP contract_generate_batch tool."""
    mock_result = {
        "trace_id": "batch-trace",
        "contract_type": "sale",
        "total_requested": 2,
        "success_count": 2,
        "failure_count": 0,
        "results": [
            {
                "success": True,
                "tags": {"scenario": "农产品买卖", "stance": "pro_a"},
                "body_text": "contract 1",
                "slots": [],
                "instructions": [],
                "law_refs": [],
                "tags_used": {},
            },
            {
                "success": True,
                "tags": {"scenario": "消费品零售", "stance": "balanced"},
                "body_text": "contract 2",
                "slots": [],
                "instructions": [],
                "law_refs": [],
                "tags_used": {},
            },
        ],
        "combinatorial_warning": False,
    }
    with patch(
        "fd_coding_law_bench_mcp.api.routes.contracts.contract_generate_batch",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock:
        yield mock


@pytest.fixture
def mock_catalog():
    """Mock the MCP contract_type_catalog tool."""
    mock_result = [
        {
            "key": "sale",
            "zh_name": "买卖合同",
            "slot_count": 12,
            "total_base_clauses": 10,
            "total_tagged_clauses": 5,
            "total_custom_clauses": 3,
            "has_scenarios": True,
        },
        {
            "key": "lease",
            "zh_name": "租赁合同",
            "slot_count": 12,
            "total_base_clauses": 8,
            "total_tagged_clauses": 2,
            "total_custom_clauses": 1,
            "has_scenarios": True,
        },
    ]
    with patch(
        "fd_coding_law_bench_mcp.api.routes.contracts.contract_type_catalog",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock:
        yield mock


@pytest.fixture
def mock_type_metadata():
    """Mock the MCP type_metadata tool."""
    mock_result = {
        "key": "sale",
        "zh_name": "买卖合同",
        "slot_count": 12,
        "universal_dims": {"stance": ["pro_a", "pro_b", "balanced"]},
        "type_specific_dims": {"risk_transfer_node": ["on_delivery"]},
        "scenarios": [
            {
                "name": "农产品买卖",
                "clause_count": 3,
                "has_tagged_clauses": True,
                "example_clause_ids": [1, 2, 3],
            }
        ],
        "assembly_ready": True,
    }
    with patch(
        "fd_coding_law_bench_mcp.api.routes.contracts.type_metadata",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock:
        yield mock


class TestContractContentEndpoint:
    """Tests for POST /contracts/content."""

    def test_content_markdown_success(self, client, mock_contract_content):
        """Test successful markdown content generation."""
        response = client.post(
            "/contracts/content",
            json={
                "contract_type": "sale",
                "tags": {"scenario": "农产品买卖", "stance": "balanced"},
                "format": "markdown",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["contract_type"] == "sale"
        assert data["format"] == "markdown"
        assert "body_text" in data
        assert "party_a" in data["slots"]

    def test_content_missing_contract_type(self, client, mock_contract_content):
        """Test 422 when contract_type is missing."""
        response = client.post("/contracts/content", json={})
        assert response.status_code == 422

    def test_content_invalid_format(self, client, mock_contract_content):
        """Test 422 when format is invalid."""
        response = client.post(
            "/contracts/content",
            json={"contract_type": "sale", "format": "invalid"},
        )
        assert response.status_code == 422

    def test_content_internal_error(self, client):
        """Test 500 when MCP tool raises exception."""
        with patch(
            "fd_coding_law_bench_mcp.api.routes.contracts.contract_content",
            new_callable=AsyncMock,
            side_effect=Exception("DB connection failed"),
        ):
            response = client.post(
                "/contracts/content",
                json={"contract_type": "sale"},
            )
            assert response.status_code == 500


class TestContractBatchEndpoint:
    """Tests for POST /contracts/batch."""

    def test_batch_explicit_combinations(self, client, mock_contract_batch):
        """Test batch with explicit tag combinations."""
        response = client.post(
            "/contracts/batch",
            json={
                "contract_type": "sale",
                "tag_combinations": [
                    {"scenario": "农产品买卖", "stance": "pro_a"},
                    {"scenario": "消费品零售", "stance": "balanced"},
                ],
                "max_concurrent": 2,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success_count"] == 2
        assert data["failure_count"] == 0
        assert len(data["results"]) == 2

    def test_batch_enumerate_all(self, client, mock_contract_batch):
        """Test batch with auto-enumeration."""
        response = client.post(
            "/contracts/batch",
            json={
                "contract_type": "sale",
                "enumerate_all": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_requested"] == 2

    def test_batch_missing_contract_type(self, client, mock_contract_batch):
        """Test 422 when contract_type missing."""
        response = client.post("/contracts/batch", json={})
        assert response.status_code == 422

    def test_batch_invalid_max_concurrent(self, client, mock_contract_batch):
        """Test 422 when max_concurrent out of bounds."""
        response = client.post(
            "/contracts/batch",
            json={"contract_type": "sale", "max_concurrent": 100},
        )
        assert response.status_code == 422

    def test_batch_partial_failure(self, client):
        """Test batch with partial failures."""
        mock_result = {
            "trace_id": "partial-trace",
            "contract_type": "sale",
            "total_requested": 2,
            "success_count": 1,
            "failure_count": 1,
            "results": [
                {
                    "success": True,
                    "tags": {"scenario": "农产品买卖"},
                    "body_text": "success",
                    "slots": [],
                    "instructions": [],
                    "law_refs": [],
                    "tags_used": {},
                },
                {
                    "success": False,
                    "tags": {"scenario": "invalid"},
                    "error": {
                        "type": "CoherenceError",
                        "message": "Missing required slot",
                        "details": {},
                    },
                },
            ],
            "combinatorial_warning": False,
        }
        with patch(
            "fd_coding_law_bench_mcp.api.routes.contracts.contract_generate_batch",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = client.post(
                "/contracts/batch",
                json={
                    "contract_type": "sale",
                    "tag_combinations": [
                        {"scenario": "农产品买卖"},
                        {"scenario": "invalid"},
                    ],
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success_count"] == 1
            assert data["failure_count"] == 1
            assert data["results"][1]["success"] is False


class TestContractTypeCatalogEndpoint:
    """Tests for GET /contracts/types."""

    def test_list_types_success(self, client, mock_catalog):
        """Test successful catalog listing."""
        response = client.get("/contracts/types")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["types"][0]["key"] == "sale"

    def test_list_types_error(self, client):
        """Test 500 when catalog tool fails."""
        with patch(
            "fd_coding_law_bench_mcp.api.routes.contracts.contract_type_catalog",
            new_callable=AsyncMock,
            side_effect=Exception("DB error"),
        ):
            response = client.get("/contracts/types")
            assert response.status_code == 500


class TestTypeMetadataEndpoint:
    """Tests for GET /contracts/types/{type}."""

    def test_metadata_success(self, client, mock_type_metadata):
        """Test successful metadata retrieval."""
        response = client.get("/contracts/types/sale")
        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "sale"
        assert data["zh_name"] == "买卖合同"
        assert len(data["scenarios"]) == 1

    def test_metadata_not_found(self, client):
        """Test 404 when contract type not found."""
        with patch(
            "fd_coding_law_bench_mcp.api.routes.contracts.type_metadata",
            new_callable=AsyncMock,
            side_effect=Exception("Contract type 'unknown' not found"),
        ):
            response = client.get("/contracts/types/unknown")
            assert response.status_code == 404

    def test_metadata_internal_error(self, client):
        """Test 500 when metadata tool fails."""
        with patch(
            "fd_coding_law_bench_mcp.api.routes.contracts.type_metadata",
            new_callable=AsyncMock,
            side_effect=Exception("Unexpected DB error"),
        ):
            response = client.get("/contracts/types/sale")
            assert response.status_code == 500


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_check(self, client):
        """Test health check returns healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

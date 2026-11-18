"""Unit tests for Pydantic schema validation."""

import pytest
from pydantic import ValidationError

from fd_coding_law_bench_mcp.api.schemas import (
    ContractBatchRequest,
    ContractContentRequest,
    ContractContentResponse,
    ErrorResponse,
    TagValidateRequest,
    TagValidateResponse,
    TypeMetadataResponse,
)


class TestContractContentRequest:
    """Tests for ContractContentRequest schema."""

    def test_minimal_valid_request(self):
        """Test request with only required fields."""
        req = ContractContentRequest(contract_type="sale")
        assert req.contract_type == "sale"
        assert req.format == "markdown"  # default
        assert req.tags is None
        assert req.include_current_tags is False

    def test_full_valid_request(self):
        """Test request with all fields populated."""
        req = ContractContentRequest(
            contract_type="sale",
            tags={"scenario": "农产品买卖", "stance": "balanced"},
            format="docx",
            include_current_tags=True,
            trace_id="test-trace-123",
        )
        assert req.contract_type == "sale"
        assert req.tags["scenario"] == "农产品买卖"
        assert req.format == "docx"
        assert req.include_current_tags is True
        assert req.trace_id == "test-trace-123"

    def test_invalid_format_value(self):
        """Test that invalid format value raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ContractContentRequest(contract_type="sale", format="invalid")
        assert "format" in str(exc_info.value)

    def test_missing_contract_type(self):
        """Test that missing contract_type raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ContractContentRequest()
        assert "contract_type" in str(exc_info.value)


class TestContractBatchRequest:
    """Tests for ContractBatchRequest schema."""

    def test_minimal_valid_request(self):
        """Test request with only required field."""
        req = ContractBatchRequest(contract_type="sale")
        assert req.contract_type == "sale"
        assert req.tag_combinations is None
        assert req.enumerate_all is False
        assert req.max_concurrent == 5  # default

    def test_max_concurrent_bounds(self):
        """Test max_concurrent must be between 1 and 20."""
        # Valid values
        req = ContractBatchRequest(contract_type="sale", max_concurrent=1)
        assert req.max_concurrent == 1
        req = ContractBatchRequest(contract_type="sale", max_concurrent=20)
        assert req.max_concurrent == 20

        # Invalid: too low
        with pytest.raises(ValidationError):
            ContractBatchRequest(contract_type="sale", max_concurrent=0)

        # Invalid: too high
        with pytest.raises(ValidationError):
            ContractBatchRequest(contract_type="sale", max_concurrent=21)

    def test_enumerate_all_with_combinations(self):
        """Test enumerate_all=True with tag_combinations provided."""
        req = ContractBatchRequest(
            contract_type="sale",
            enumerate_all=True,
            tag_combinations=[{"stance": "pro_a"}],
        )
        assert req.enumerate_all is True
        assert len(req.tag_combinations) == 1


class TestErrorResponse:
    """Tests for ErrorResponse schema."""

    def test_minimal_error(self):
        """Test error with required fields only."""
        err = ErrorResponse(error="NotFoundError", message="Contract not found")
        assert err.error == "NotFoundError"
        assert err.message == "Contract not found"
        assert err.details is None
        assert err.trace_id is None

    def test_full_error(self):
        """Test error with all fields."""
        err = ErrorResponse(
            error="ValidationError",
            message="Invalid tag value",
            details={"field": "stance", "value": "invalid"},
            trace_id="trace-456",
        )
        assert err.error == "ValidationError"
        assert err.details["field"] == "stance"
        assert err.trace_id == "trace-456"

    def test_error_serialization(self):
        """Test error serialization excludes None fields."""
        err = ErrorResponse(error="TestError", message="Test message")
        serialized = err.model_dump(exclude_none=True)
        assert "details" not in serialized
        assert "trace_id" not in serialized
        assert serialized["error"] == "TestError"


class TestTagValidateRequest:
    """Tests for TagValidateRequest schema."""

    def test_valid_request(self):
        """Test valid tag validation request."""
        req = TagValidateRequest(
            tags={"stance": "pro_a", "scenario": "农产品买卖"},
            contract_type="sale",
        )
        assert req.tags["stance"] == "pro_a"
        assert req.contract_type == "sale"

    def test_optional_contract_type(self):
        """Test that contract_type is optional."""
        req = TagValidateRequest(tags={"stance": "pro_a"})
        assert req.contract_type is None

    def test_missing_tags_raises_error(self):
        """Test that missing tags raises ValidationError."""
        with pytest.raises(ValidationError):
            TagValidateRequest()


class TestTagValidateResponse:
    """Tests for TagValidateResponse schema."""

    def test_valid_response(self):
        """Test valid tag validation response."""
        resp = TagValidateResponse(
            valid=True,
            cleaned_tags={"stance": "pro_a"},
            errors=[],
        )
        assert resp.valid is True
        assert resp.cleaned_tags["stance"] == "pro_a"

    def test_invalid_response_with_errors(self):
        """Test invalid response with error messages."""
        resp = TagValidateResponse(
            valid=False,
            cleaned_tags={},
            errors=["Invalid value for stance: invalid"],
        )
        assert resp.valid is False
        assert len(resp.errors) == 1


class TestContractContentResponse:
    """Tests for ContractContentResponse schema."""

    def test_full_response(self):
        """Test full contract content response."""
        resp = ContractContentResponse(
            trace_id="trace-789",
            contract_type="sale",
            format="markdown",
            body_text="## 当事人\n\n甲方：{{party_a}}",
            slots=["party_a", "party_b"],
            instructions=[{"name": "party_a", "label": "甲方"}],
            law_refs=[{"name": "民法典", "category": "statute"}],
            tags_used={"scenario": "农产品买卖"},
        )
        assert resp.contract_type == "sale"
        assert resp.format == "markdown"
        assert "{{party_a}}" in resp.body_text
        assert len(resp.slots) == 2
        assert resp.docx_path is None  # default None for markdown format

    def test_response_with_file_paths(self):
        """Test response includes file paths when format includes files."""
        resp = ContractContentResponse(
            trace_id="trace-file",
            contract_type="sale",
            format="both",
            body_text="contract body",
            slots=[],
            instructions=[],
            law_refs=[],
            tags_used={},
            docx_path="/tmp/sale.docx",
            pdf_path="/tmp/sale.pdf",
        )
        assert resp.docx_path == "/tmp/sale.docx"
        assert resp.pdf_path == "/tmp/sale.pdf"


class TestTypeMetadataResponse:
    """Tests for TypeMetadataResponse schema."""

    def test_full_metadata_response(self):
        """Test full type metadata response."""
        resp = TypeMetadataResponse(
            key="sale",
            zh_name="买卖合同",
            slot_count=12,
            universal_dims={"stance": ["pro_a", "pro_b", "balanced"]},
            type_specific_dims={"risk_transfer_node": ["on_delivery"]},
            scenarios=[{
                "name": "农产品买卖",
                "clause_count": 3,
                "has_tagged_clauses": True,
                "example_clause_ids": [1, 2, 3],
            }],
            assembly_ready=True,
        )
        assert resp.key == "sale"
        assert resp.zh_name == "买卖合同"
        assert resp.slot_count == 12
        assert resp.scenarios[0].name == "农产品买卖"
        assert resp.assembly_ready is True

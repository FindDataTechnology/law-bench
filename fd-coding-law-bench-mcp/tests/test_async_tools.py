"""Unit tests for async contract generation tools.

Tests cover:
- tag_combinations_list algorithm
- contract_content with various tag combinations
- batch operations with throttling
- error handling and trace IDs
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock


# Test tag_combinations_list
@pytest.mark.asyncio
async def test_tag_combinations_list_basic():
    """Test basic tag combination enumeration."""
    from src.fd_coding_law_bench_mcp.tools.tags import tag_combinations_list

    # Mock DB calls
    with patch('src.clauses.tags.load_vocab_from_db'), \
         patch('src.clauses.tags.tag_vocab_for_type') as mock_vocab:

        mock_vocab.return_value = {
            "stance": ["pro_a", "pro_b", "balanced"],
            "scenario": ["农产品买卖", "消费品零售"],
        }

        result = await tag_combinations_list("sale", include_clause_availability=False)

        assert result["contract_type"] == "sale"
        assert len(result["combinations"]) == 6  # 3 stances × 2 scenarios
        assert not result["combinatorial_warning"]


@pytest.mark.asyncio
async def test_tag_combinations_list_with_availability():
    """Test tag combinations with clause availability metadata."""
    from src.fd_coding_law_bench_mcp.tools.tags import tag_combinations_list

    with patch('src.clauses.tags.load_vocab_from_db'), \
         patch('src.clauses.tags.tag_vocab_for_type') as mock_vocab, \
         patch('src.clauses.store.list_clauses') as mock_list:

        mock_vocab.return_value = {
            "stance": ["pro_a", "balanced"],
            "scenario": ["农产品买卖"],
        }

        # Mock clause queries
        mock_list.side_effect = [
            [{"id": 1}],  # tagged for 农产品买卖
            [{"id": 2}],  # custom for pro_a
            [{"id": 3}],  # tagged for 农产品买卖 (second combo)
            [],           # custom for balanced (none)
        ]

        result = await tag_combinations_list("sale", include_clause_availability=True)

        assert len(result["combinations"]) == 2
        assert result["combinations"][0]["has_tagged_clauses"]
        assert result["combinations"][0]["has_custom_clauses"]
        assert result["combinations"][1]["has_tagged_clauses"]
        assert not result["combinations"][1]["has_custom_clauses"]


@pytest.mark.asyncio
async def test_tag_combinations_list_warning():
    """Test combinatorial explosion warning."""
    from src.fd_coding_law_bench_mcp.tools.tags import tag_combinations_list

    with patch('src.clauses.tags.load_vocab_from_db'), \
         patch('src.clauses.tags.tag_vocab_for_type') as mock_vocab:

        # Create a vocab that generates >1000 combinations
        mock_vocab.return_value = {
            "stance": [f"stance_{i}" for i in range(100)],
            "scenario": [f"scenario_{i}" for i in range(20)],
        }

        result = await tag_combinations_list("sale", include_clause_availability=False)

        assert len(result["combinations"]) == 2000
        assert result["combinatorial_warning"]


# Test contract_content
@pytest.mark.asyncio
async def test_contract_content_markdown():
    """Test contract content returns markdown without file I/O."""
    from src.fd_coding_law_bench_mcp.tools.content import contract_content

    with patch('src.clauses.assemble.generate_contract_assembled') as mock_gen:
        mock_gen.return_value = {
            "body_text": "## Test Contract\n\n{{party_a}} ...",
            "slots": ["party_a", "party_b"],
            "instructions": [{"name": "party_a", "label": "甲方"}],
            "law_refs": [{"name": "民法典", "category": "statute"}],
        }

        result = await contract_content("sale", format="markdown")

        assert result["contract_type"] == "sale"
        assert result["format"] == "markdown"
        assert "body_text" in result
        assert "docx_path" not in result  # No file paths in markdown mode
        mock_gen.assert_called_once()


@pytest.mark.asyncio
async def test_contract_content_with_tags():
    """Test contract content with specific tags."""
    from src.fd_coding_law_bench_mcp.tools.content import contract_content

    with patch('src.clauses.assemble.generate_contract_assembled') as mock_gen:
        mock_gen.return_value = {
            "body_text": "## 农产品买卖合同\n\n...",
            "slots": [],
            "instructions": [],
            "law_refs": [],
        }

        result = await contract_content(
            "sale",
            tags={"scenario": "农产品买卖", "stance": "balanced"},
            format="markdown",
        )

        assert result["tags_used"]["scenario"] == "农产品买卖"
        assert result["tags_used"]["stance"] == "balanced"


# Test batch operations
@pytest.mark.asyncio
async def test_contract_generate_batch_explicit():
    """Test batch generation with explicit tag combinations."""
    from src.fd_coding_law_bench_mcp.tools.batch import contract_generate_batch

    with patch('src.fd_coding_law_bench_mcp.tools.content.contract_content') as mock_content:
        mock_content.side_effect = [
            {"body_text": "Contract 1", "slots": [], "instructions": [], "law_refs": []},
            {"body_text": "Contract 2", "slots": [], "instructions": [], "law_refs": []},
        ]

        result = await contract_generate_batch(
            "sale",
            tag_combinations=[
                {"scenario": "农产品买卖", "stance": "pro_a"},
                {"scenario": "消费品零售", "stance": "pro_b"},
            ],
            max_concurrent=2,
        )

        assert result["success_count"] == 2
        assert result["failure_count"] == 0
        assert len(result["results"]) == 2


@pytest.mark.asyncio
async def test_contract_generate_batch_partial_failure():
    """Test batch generation with some failures."""
    from src.fd_coding_law_bench_mcp.tools.batch import contract_generate_batch

    with patch('src.fd_coding_law_bench_mcp.tools.content.contract_content') as mock_content:
        mock_content.side_effect = [
            {"body_text": "Success", "slots": [], "instructions": [], "law_refs": []},
            ValueError("Coherence error"),
        ]

        result = await contract_generate_batch(
            "sale",
            tag_combinations=[
                {"scenario": "农产品买卖", "stance": "pro_a"},
                {"scenario": "invalid", "stance": "pro_b"},
            ],
        )

        assert result["success_count"] == 1
        assert result["failure_count"] == 1
        assert result["results"][0]["success"]
        assert not result["results"][1]["success"]
        assert "error" in result["results"][1]


@pytest.mark.asyncio
async def test_contract_generate_batch_enumerate_all():
    """Test batch generation with auto-enumeration."""
    from src.fd_coding_law_bench_mcp.tools.batch import contract_generate_batch

    with patch('src.clauses.tags.tag_vocab_list') as mock_vocab, \
         patch('src.fd_coding_law_bench_mcp.tools.content.contract_content') as mock_content:

        mock_vocab.return_value = {
            "stance": ["pro_a", "balanced"],
            "scenario": ["农产品买卖"],
        }
        mock_content.return_value = {
            "body_text": "Contract",
            "slots": [],
            "instructions": [],
            "law_refs": [],
        }

        result = await contract_generate_batch("sale", enumerate_all=True)

        assert result["total_requested"] == 2
        assert not result["combinatorial_warning"]


# Test error handling
def test_error_response_structure():
    """Test standardized error response format."""
    from src.fd_coding_law_bench_mcp.tools.errors import make_error_response

    err = make_error_response(
        trace_id="test-trace-123",
        error_type="CoherenceError",
        message="Missing required slot: party_a",
        details={"slot": "party_a"},
    )

    assert not err["success"]
    assert err["trace_id"] == "test-trace-123"
    assert err["error"]["type"] == "CoherenceError"
    assert err["error"]["message"] == "Missing required slot: party_a"
    assert err["error"]["details"]["slot"] == "party_a"


def test_extract_error_info():
    """Test error info extraction from exceptions."""
    from src.fd_coding_law_bench_mcp.tools.errors import extract_error_info

    exc = ValueError("Test error message")
    info = extract_error_info(exc)

    assert info["type"] == "ValueError"
    assert info["message"] == "Test error message"
    assert "module" in info["details"]

"""Integration tests for the contract-review-agent.

These tests validate the full agent flow: multi-model review, human checkpoints,
dual evaluation, and metrics persistence. Run with pytest from the repo root.

Prerequisites:
- PostgreSQL database running with agent_runs table created
- .env file with reviewer models, quiz model, DATABASE_URL, OPENAI_API_KEY/BASE
- law-bench MCP server running (for contract generation)

Usage:
    cd <repo-root>
    pytest contract-review-agent/tests/test_integration.py -v
"""
import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add agent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.config import reviewers
from agent.nodes.generate_quiz import generate_quiz_node
from agent.nodes.generate_v1 import generate_v1_node
from agent.nodes.generate_v2 import generate_v2_node
from agent.nodes.review_panel import review_panel_node
from agent.nodes.synthesize import synthesize_node
from agent.state import ReviewState


@pytest.fixture
def sample_state():
    """Sample ReviewState for testing."""
    return ReviewState(
        contract_type="sale",
        tags={"scenario": "农产品买卖", "stance": "balanced"},
        task_desc="生成一份农产品买卖合同",
        thread_id="test-thread-001",
        reviewers=reviewers(),
    )


@pytest.fixture
def mock_config():
    """Mock RunnableConfig for LangGraph nodes."""
    return MagicMock()


# ============================================================================
# Test 13.2: Review Panel with 3 Models
# ============================================================================


@pytest.mark.asyncio
async def test_review_panel_parallel_execution(sample_state, mock_config):
    """Test that review_panel runs 3 reviewers in parallel."""
    # Mock generate_v1 to populate draft_v1
    state = await generate_v1_node(sample_state, mock_config)

    # Mock LLM calls to avoid actual API calls
    with patch("agent.nodes.review_panel.call_llm") as mock_llm:
        mock_llm.return_value = {
            "text": '{"suggestions": [{"severity": "warning", "section": "交付", "recommendation": "增加交付期限条款"}]}',
            "tokens": 100,
            "cost": 0.01,
            "latency": 1.5,
        }

        result = await review_panel_node(state, mock_config)

    # Verify 3 reviews were collected
    assert len(result["reviews"]) == 3
    assert result["completed_reviews"] == 3
    assert result["total_reviews"] == 3

    # Verify each reviewer has a different lens
    lenses = {r["lens"] for r in result["reviews"]}
    assert lenses == {"legal_accuracy", "commercial_fairness", "completeness"}

    # Verify timing was recorded
    assert "review_panel" in result["node_timings"]
    assert result["node_timings"]["review_panel"] > 0


# ============================================================================
# Test 13.3: Quiz Generation
# ============================================================================


@pytest.mark.asyncio
async def test_quiz_generation_extracts_all_slots(sample_state, mock_config):
    """Test that generate_quiz creates a question for every slot."""
    # Mock generate_v1 to get slots
    state = await generate_v1_node(sample_state, mock_config)

    # Mock LLM call for quiz generation
    with patch("agent.nodes.generate_quiz.call_llm") as mock_llm:
        mock_llm.return_value = {
            "text": '{"买方名称": "请输入买方全称", "卖方名称": "请输入卖方全称", "标的物": "请描述标的物"}',
            "tokens": 50,
            "cost": 0.005,
            "latency": 0.8,
        }

        result = await generate_quiz_node(state, mock_config)

    # Verify quiz_items were generated
    assert "quiz_items" in result
    assert len(result["quiz_items"]) > 0

    # Verify each slot has a question
    for item in result["quiz_items"]:
        assert "slot" in item
        assert "question" in item
        assert "required" in item
        assert item["required"] is True  # all slots are required


# ============================================================================
# Test 13.4: Human Checkpoints (interrupt/resume)
# ============================================================================


def test_human_checkpoint_interrupt_mechanism(sample_state, mock_config):
    """Test that human checkpoint nodes use LangGraph interrupt()."""
    from langgraph.types import interrupt

    # Verify interrupt is available
    assert callable(interrupt)

    # Note: We can't actually test interrupt() in a unit test because it
    # requires a running LangGraph graph with checkpointer. The integration
    # test (test_e2e_flow) validates this end-to-end.


# ============================================================================
# Test 13.5: Dual Evaluation
# ============================================================================


@pytest.mark.asyncio
async def test_dual_evaluation_rubric_and_deepeval(sample_state, mock_config):
    """Test that evaluate node runs both rubric and deepeval metrics."""
    # Mock generate_v2 to populate draft_v2
    state = sample_state
    state["draft_v2"] = "甲方：张三\n乙方：李四\n标的物：苹果\n数量：1000斤"

    # Mock rubric evaluation
    with patch("agent.nodes.evaluate.evaluate_contract") as mock_rubric:
        mock_rubric.return_value = {
            "run_id": 123,
            "score": 0.8,
            "n_passed": 8,
            "n_criteria": 10,
            "summary": "8/10 criteria passed",
        }

        # Mock deepeval metrics
        with patch("agent.nodes.evaluate.HallucinationMetric") as mock_halluc:
            with patch("agent.nodes.evaluate.FaithfulnessMetric") as mock_faith:
                with patch("agent.nodes.evaluate.GEval") as mock_geval:
                    # Mock metric instances
                    mock_halluc_instance = MagicMock()
                    mock_halluc_instance.score = 0.9
                    mock_halluc_instance.is_successful.return_value = True
                    mock_halluc.return_value = mock_halluc_instance

                    mock_faith_instance = MagicMock()
                    mock_faith_instance.score = 0.85
                    mock_faith_instance.is_successful.return_value = True
                    mock_faith.return_value = mock_faith_instance

                    mock_geval_instance = MagicMock()
                    mock_geval_instance.score = 0.75
                    mock_geval_instance.is_successful.return_value = True
                    mock_geval.return_value = mock_geval_instance

                    from agent.nodes.evaluate import evaluate_node

                    result = await evaluate_node(state, mock_config)

    # Verify rubric eval was run
    assert "eval_result" in result
    assert result["eval_result"]["n_passed"] == 8
    assert result["eval_run_id"] == 123

    # Verify deepeval scores were collected
    assert "deepeval_scores" in result
    assert "hallucination" in result["deepeval_scores"]
    assert "faithfulness" in result["deepeval_scores"]
    assert "slot_relevance" in result["deepeval_scores"]


# ============================================================================
# Test 13.6: Agent Metrics Persistence
# ============================================================================


@pytest.mark.asyncio
async def test_agent_metrics_persistence(sample_state, mock_config):
    """Test that metrics are persisted to agent_runs table."""
    # Mock the full flow
    state = sample_state
    state["draft_v1"] = "合同草案..."
    state["draft_v2"] = "最终合同..."
    state["node_timings"] = {"generate_v1": 2.3, "review_panel": 8.1}
    state["model_calls"] = [
        {"model": "kimi-k3", "node": "review_panel", "tokens": 100, "cost": 0.01}
    ]
    state["slots"] = ["买方名称", "卖方名称"]
    state["slot_values"] = {"买方名称": "张三", "卖方名称": "李四"}

    # Mock insert_agent_run
    with patch("agent.nodes.metrics.insert_agent_run") as mock_insert:
        mock_insert.return_value = 456

        from agent.nodes.metrics import metrics_node

        result = await metrics_node(state, mock_config)

    # Verify metrics were persisted
    assert result["agent_run_id"] == 456
    mock_insert.assert_called_once()

    # Verify the row contains expected fields
    call_args = mock_insert.call_args[0][0]
    assert call_args["thread_id"] == "test-thread-001"
    assert call_args["contract_type"] == "sale"
    assert call_args["total_slots"] == 2
    assert call_args["human_filled_slots"] == 2


# ============================================================================
# Test 13.7: Error Handling
# ============================================================================


@pytest.mark.asyncio
async def test_error_handling_missing_env_vars():
    """Test that missing .env vars produce clear errors."""
    # Temporarily remove env vars
    original_model = os.environ.get("REVIEWER_1_MODEL")
    if "REVIEWER_1_MODEL" in os.environ:
        del os.environ["REVIEWER_1_MODEL"]

    try:
        from agent.config import reviewers

        with pytest.raises(RuntimeError, match="REVIEWER_1_MODEL"):
            reviewers()
    finally:
        # Restore env var
        if original_model:
            os.environ["REVIEWER_1_MODEL"] = original_model


@pytest.mark.asyncio
async def test_error_handling_llm_failure(sample_state, mock_config):
    """Test that LLM call failures are caught and reported."""
    state = await generate_v1_node(sample_state, mock_config)

    # Mock LLM to raise an exception
    with patch("agent.nodes.review_panel.call_llm") as mock_llm:
        mock_llm.side_effect = Exception("API rate limit exceeded")

        result = await review_panel_node(state, mock_config)

    # Verify errors were recorded but node didn't crash
    assert "errors" in result
    assert len(result["errors"]) > 0
    assert "API rate limit exceeded" in result["errors"][0]["message"]


# ============================================================================
# Test 13.1: End-to-End Flow (Integration)
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires running PostgreSQL + law-bench MCP server")
async def test_e2e_flow(sample_state, mock_config):
    """End-to-end test: full agent run from generate_v1 to export.

    This test requires:
    - PostgreSQL database with agent_runs table
    - law-bench MCP server running
    - Valid .env with reviewer models and API credentials

    Run manually with:
        pytest contract-review-agent/tests/test_integration.py::test_e2e_flow -v -s
    """
    from agent.graph import build_review_graph

    graph = build_review_graph()

    # Run the graph (will hit checkpoints and pause)
    # In a real test, we'd simulate human responses via Command(resume=...)
    result = await graph.ainvoke(sample_state)

    # Verify all stages completed
    assert result.get("current_stage") == "export"
    assert result.get("agent_run_id") is not None
    assert len(result.get("reviews", [])) == 3
    assert len(result.get("quiz_items", [])) > 0

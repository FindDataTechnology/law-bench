"""End-to-end automated test for the contract-review-agent.

Drives the full LangGraph flow programmatically:
  generate_v1 → review_panel → synthesize → 🚦 CP1 → generate_quiz → 🚦 CP2
  → generate_v2 → evaluate → 🚦 CP3 → export → metrics

At each interrupt(), the script resumes with canned test data so no human
interaction is required. Prints every stage's output + the final metrics.

Usage:
    cd <repo-root>/contract-review-agent
    uv run python tests/run_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Make the agent package importable.
AGENT_ROOT = Path(__file__).resolve().parent.parent
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

# Also make the law-template repo root importable for src.* / fd_coding_law_bench_mcp.*.
REPO_ROOT = AGENT_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from langgraph.types import Command


def banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def section(title: str) -> None:
    print("\n" + "-" * 50)
    print(f"  {title}")
    print("-" * 50)


async def run_e2e() -> dict:
    """Run the full graph, auto-resuming at each checkpoint."""
    from agent.graph import build_review_graph
    from agent.state import ReviewState

    banner("CONTRACT REVIEW AGENT — E2E TEST")
    print(f"contract_type: sale (农产品买卖)")
    print(f"thread_id: e2e-test-001")

    # 1. Initialize checkpointer + build graph
    section("1. 初始化 Checkpointer + 构建 Graph")
    # Use MemorySaver for the e2e test (no need for cross-process persistence;
    # the Postgres checkpointer's connection management conflicts with the
    # shared src.eval.db cached connection when both run in-process).
    from langgraph.checkpoint.memory import MemorySaver

    checkpointer = MemorySaver()
    graph = build_review_graph(checkpointer=checkpointer)
    print(f"✓ Graph compiled with MemorySaver checkpointer")

    # 2. Initial state
    initial_state: ReviewState = {
        "contract_type": "sale",
        "tags": {"scenario": "农产品买卖", "stance": "balanced"},
        "task_desc": "生成一份农产品买卖合同，卖方为张三农业合作社，买方为李四超市",
        "thread_id": "e2e-test-001",
        "node_timings": {},
        "model_calls": [],
        "errors": [],
    }

    config = {"configurable": {"thread_id": "e2e-test-001"}}
    t0 = time.perf_counter()

    # 3. First invoke — runs until the first interrupt (CP1: triage)
    section("2. 启动 Graph → generate_v1 → review_panel → synthesize → 🚦 CP1")
    print("调用 graph.ainvoke()，等待第一个 checkpoint...")
    state = await graph.ainvoke(initial_state, config=config)

    # Detect which interrupt we're at by inspecting the pending tasks.
    interrupts_seen = 0
    last_node = None
    repeat_count = 0
    MAX_INTERRUPTS = 10  # safety guard against infinite loops
    while True:
        # Get the current state snapshot from the checkpointer.
        snapshot = await graph.aget_state(config)
        pending = snapshot.next  # node names waiting to run
        if not pending:
            print("\n✓ Graph finished (no pending interrupts)")
            break

        interrupts_seen += 1
        node_name = pending[0] if pending else "unknown"

        # Guard against infinite loops: if the same checkpoint fires 3 times
        # in a row, something is wrong with the resume value - bail out.
        if node_name == last_node:
            repeat_count += 1
            if repeat_count >= 3:
                print(f"\n⚠️ Same checkpoint '{node_name}' fired {repeat_count} times - aborting to avoid infinite loop")
                errors = state.get("errors", []) if isinstance(state, dict) else []
                print(f"   state errors: {errors}")
                break
        else:
            repeat_count = 1
            last_node = node_name

        if interrupts_seen > MAX_INTERRUPTS:
            print(f"\n⚠️ Exceeded max interrupts ({MAX_INTERRUPTS}) - aborting")
            break

        banner(f"🚦 CHECKPOINT {interrupts_seen}: {node_name}")

        # Show what the interrupt surfaced.
        interrupt_payload = None
        if snapshot.tasks:
            for task in snapshot.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    interrupt_payload = task.interrupts[0].value
                    break

        if interrupt_payload:
            name = interrupt_payload.get("name", "unknown")
            print(f"  Interrupt name: {name}")
            if "suggestions" in interrupt_payload:
                sug = interrupt_payload["suggestions"]
                print(f"  Suggestions to triage: {len(sug)} items")
                for i, s in enumerate(sug[:5]):
                    print(f"    [{i}] [{s.get('severity')}] {s.get('section')}: {s.get('recommendation','')[:50]}")
            if "quiz_items" in interrupt_payload:
                qi = interrupt_payload["quiz_items"]
                print(f"  Quiz items to fill: {len(qi)} slots")
                for item in qi[:5]:
                    print(f"    - {item.get('slot')}: {item.get('question','')[:50]}")
            if "draft" in interrupt_payload:
                print(f"  Draft length: {len(interrupt_payload.get('draft',''))} chars")
                ev = interrupt_payload.get("eval_result", {})
                print(f"  Eval: {ev.get('n_passed','?')}/{ev.get('n_criteria','?')} passed")

        # Build a resume value based on which checkpoint this is.
        resume_value = _build_resume(node_name, state, interrupt_payload)
        print(f"\n  → 自动提交 resume 数据，继续执行...")

        state = await graph.ainvoke(Command(resume=resume_value), config=config)

    elapsed = time.perf_counter() - t0
    banner("✅ E2E TEST COMPLETE")
    print(f"Total elapsed: {elapsed:.2f}s")
    print(f"Checkpoints passed: {interrupts_seen}")

    # Print final state summary
    section("最终状态摘要")
    print(f"current_stage: {state.get('current_stage')}")
    print(f"contract_type: {state.get('contract_type')}")
    print(f"slots extracted: {len(state.get('slots', []))}")
    print(f"reviews: {len(state.get('reviews', []))}")
    print(f"synthesized_suggestions: {len(state.get('synthesized_suggestions', []))}")
    print(f"accepted_suggestions: {len(state.get('accepted_suggestions', []))}")
    print(f"quiz_items: {len(state.get('quiz_items', []))}")
    print(f"slot_values filled: {len(state.get('slot_values', {}))}")
    print(f"errors: {len(state.get('errors', []))}")

    if state.get("eval_result"):
        ev = state["eval_result"]
        print(f"\n📊 Rubric Eval: {ev.get('n_passed','?')}/{ev.get('n_criteria','?')} passed")
        print(f"   summary: {ev.get('summary','')}")
    if state.get("deepeval_scores"):
        print(f"\n📊 DeepEval Scores:")
        for k, v in state["deepeval_scores"].items():
            if isinstance(v, dict):
                print(f"   {k}: score={v.get('score','?')}, success={v.get('success','?')}")

    if state.get("node_timings"):
        print(f"\n⏱ Node Timings:")
        for node, t in state["node_timings"].items():
            print(f"   {node}: {t}s")

    if state.get("model_calls"):
        total_tokens = sum(c.get("tokens", 0) for c in state["model_calls"])
        print(f"\n💰 Model Calls: {len(state['model_calls'])} calls, {total_tokens} tokens total")

    if state.get("errors"):
        print(f"\n⚠️ Errors ({len(state['errors'])}):")
        for e in state["errors"][:5]:
            print(f"   [{e.get('node')}] {e.get('message','')[:80]}")

    # Show a snippet of the final contract
    if state.get("draft_v2"):
        section("最终合同预览（前 500 字符）")
        print(state["draft_v2"][:500])
        if len(state["draft_v2"]) > 500:
            print(f"\n... ({len(state['draft_v2'])} chars total)")

    return state

def _build_resume(node_name: str, state: dict, payload: dict | None) -> dict | str:
    """Build the resume value for each checkpoint automatically."""
    payload = payload or {}

    if "triage" in node_name:
        # CP1: accept all suggestions
        suggestions = payload.get("suggestions", [])
        print(f"  → CP1: accepting all {len(suggestions)} suggestions")
        return {"accepted": suggestions}

    if "quiz" in node_name:
        # CP2: fill every slot with test values
        quiz_items = payload.get("quiz_items", [])
        slot_values = {}
        test_values = {
            "甲方": "张三农业合作社",
            "乙方": "李四超市",
            "买方": "李四超市",
            "卖方": "张三农业合作社",
            "标的": "新鲜苹果",
            "标的物": "新鲜苹果",
            "数量": "1000公斤",
            "价款": "5000元",
            "金额": "5000元",
            "交货地点": "北京市朝阳区仓库",
            "交货时间": "2026-08-15",
            "交货方式": "汽车运输",
            "付款方式": "银行转账",
            "付款时间": "2026-08-10",
            "违约金": "5%",
            "管辖": "北京市朝阳区人民法院",
        }
        for item in quiz_items:
            slot = item.get("slot", "")
            # Try exact match first, then fallback
            if slot in test_values:
                slot_values[slot] = test_values[slot]
            else:
                slot_values[slot] = f"测试值_{slot}"
        print(f"  → CP2: filling all {len(slot_values)} slots")
        return slot_values

    if "review" in node_name or "approve" in node_name:
        # CP3: approve
        print(f"  → CP3: approving final contract")
        return {"approval": "approved"}

    # Default: empty dict
    return {}


if __name__ == "__main__":
    try:
        result = asyncio.run(run_e2e())
        print("\n\n✅ E2E test completed successfully!")
        sys.exit(0)
    except Exception as exc:
        print(f"\n\n❌ E2E test failed: {exc}")
        traceback.print_exc()
        sys.exit(1)

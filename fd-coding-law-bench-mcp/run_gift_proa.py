#!/usr/bin/env python3
"""Run pipeline for gift pro_a stance (low-scoring case #287)"""

import asyncio
import sys
import os

# Add the project to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.fd_coding_law_bench_mcp.tools.pipeline import pipeline_run


async def main():
    """Execute the pipeline with specified parameters."""

    params = {
        "contract_type": "gift",
        "stance": "pro_a",
        "tags": {},
        "rubric": "contract_gift_v1",
        "max_iterations": 3,
        "task_desc": "Generate a gift contract with pro_a stance",
        "temperature": 0.0,
    }

    print("=" * 60)
    print("Starting Pipeline Run")
    print("=" * 60)
    print(f"Contract Type: {params['contract_type']}")
    print(f"Stance: {params['stance']}")
    print(f"Tags: {params['tags']}")
    print(f"Rubric: {params['rubric']}")
    print(f"Max Iterations: {params['max_iterations']}")
    print(f"Task Description: {params['task_desc']}")
    print(f"Temperature: {params['temperature']}")
    print("=" * 60)
    print()

    try:
        result = await pipeline_run(**params)

        print("=" * 60)
        print("PIPELINE RUN COMPLETE")
        print("=" * 60)
        print()
        print("RESULTS:")
        print(f"  1. Pipeline Run ID: {result.get('pipeline_run_id')}")
        print(f"  2. Final Score: {result.get('n_passed')}/{result.get('n_criteria')} ({result.get('score', 0)/result.get('max_score', 1)*100:.1f}%)")
        print(f"  3. Iterations Completed: {result.get('iteration')}")
        print(f"  4. All Pass: {result.get('all_pass')}")
        print()

        if result.get('actions_taken'):
            print("ACTIONS TAKEN:")
            for action in result.get('actions_taken', []):
                print(f"    - {action}")
            print()

        if result.get('recommendations'):
            print("RECOMMENDATIONS:")
            for rec in result.get('recommendations', []):
                print(f"    - {rec}")
            print()

        if result.get('summary'):
            print("SUMMARY:")
            print(f"    {result['summary']}")
            print()

        # Print criteria results if available
        if result.get('criteria_results'):
            print("CRITERIA RESULTS:")
            for crit in result.get('criteria_results', []):
                status = "✓ PASS" if crit.get('pass') else "✗ FAIL"
                score_info = crit.get('score', f"{crit.get('passed_score', 0)}/{crit.get('total_score', 0)}")
                print(f"    [{status}] {score_info}: {crit.get('name', 'N/A')}")
            print()

        print("=" * 60)
        print("RUN COMPLETED SUCCESSFULLY")
        print("=" * 60)

        return result

    except Exception as e:
        print("=" * 60)
        print("ERROR OCCURRED DURING PIPELINE RUN")
        print("=" * 60)
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Message: {str(e)}")
        import traceback
        traceback.print_exc()
        print("=" * 60)
        raise


if __name__ == "__main__":
    asyncio.run(main())

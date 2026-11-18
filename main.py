#!/usr/bin/env python3
"""
Chinese Contract Drafting Multi-Agent System
Usage: python main.py "帮我起草一份..." [output.md]
If an output file is specified, the final draft will be saved to that file.
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from src.crew import ContractDraftingCrew
from src.settings import DRAFTING_REQUIRED_VARS


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Draft a Chinese contract from a natural-language request.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Example: python main.py "起草一份服务协议，甲方是科技公司，乙方是个人顾问" output.md',
    )
    ap.add_argument(
        "request",
        help='The contract drafting request (quote multi-word requests).',
    )
    ap.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Optional output file path; the final draft is saved here if given.",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    # Parse first so --help and usage errors work without env configured.
    args = _build_parser().parse_args(argv)
    user_request = args.request
    output_file = args.output

    # Load environment variables from .env, then check required vars.
    load_dotenv()
    missing = [v for v in DRAFTING_REQUIRED_VARS if v not in os.environ]
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        print("Please copy .env.example to .env and fill in the values.")
        return 1

    print(f"\n用户需求: {user_request}\n")
    if output_file:
        print(f"输出文件: {output_file}\n")
    print("=" * 60)

    # Create crew and kickoff
    crew = ContractDraftingCrew().crew()
    result = crew.kickoff(inputs={"user_request": user_request})

    print("\n" + "=" * 60)
    print("\n最终合同草案:\n")
    print(result.raw)

    # Save to file if requested
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(result.raw)
        print(f"\n✅ 已保存至: {output_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

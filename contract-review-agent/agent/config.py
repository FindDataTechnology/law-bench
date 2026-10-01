"""Runtime configuration loaded from .env — reviewer models/lenses/names.

Kept separate from api.config (which covers server/infra settings) because the
graph nodes need reviewer configs at import time, before the FastAPI app boots.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

VALID_LENSES = {"legal_accuracy", "commercial_fairness", "completeness"}


class ReviewerConfigError(RuntimeError):
    """Raised when .env is missing required reviewer fields."""


def _reviewer(idx: int) -> dict:
    prefix = f"REVIEWER_{idx}"
    model = os.environ.get(f"{prefix}_MODEL")
    lens = os.environ.get(f"{prefix}_LENS")
    name = os.environ.get(f"{prefix}_NAME") or f"Reviewer {idx}"
    missing = [
        var
        for var, val in [
            (f"{prefix}_MODEL", model),
            (f"{prefix}_LENS", lens),
        ]
        if not val
    ]
    if missing:
        raise ReviewerConfigError(
            f"Missing required env vars for reviewer {idx}: {', '.join(missing)}. "
            "Copy .env.example -> .env and fill them in."
        )
    if lens not in VALID_LENSES:
        raise ReviewerConfigError(
            f"REVIEWER_{idx}_LENS={lens!r} is invalid; use one of {sorted(VALID_LENSES)}."
        )
    return {"name": name, "model": model, "lens": lens}


def reviewers() -> list[dict]:
    """Load all reviewer configs (REVIEWER_1..N). Returns at least 3 reviewers."""
    out = []
    for idx in range(1, 4):  # require the canonical 3
        out.append(_reviewer(idx))
    # allow extra reviewers if configured
    idx = 4
    while True:
        if not os.environ.get(f"REVIEWER_{idx}_MODEL"):
            break
        out.append(_reviewer(idx))
        idx += 1
    return out


def quiz_model() -> str:
    m = os.environ.get("QUIZ_MODEL")
    if not m:
        raise ReviewerConfigError(
            "QUIZ_MODEL is not set; copy .env.example -> .env and fill it in."
        )
    return m

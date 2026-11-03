"""Backward-compat shim: implementation lives at ``packs.legal.law_catalog.remediate``."""

from packs.legal.law_catalog.remediate import (
    REPO_ROOT,
    SNAPSHOT_ROOT,
    apply_batch,
    plan_batch,
    record_no_action,
    rollback_batch,
    verify_batch,
)

__all__ = [
    "REPO_ROOT",
    "SNAPSHOT_ROOT",
    "plan_batch",
    "apply_batch",
    "record_no_action",
    "rollback_batch",
    "verify_batch",
]

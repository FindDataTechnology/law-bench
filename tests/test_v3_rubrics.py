"""Tests for v3 rubric seeding (optimized evaluation criteria)."""

from __future__ import annotations

import pytest

from src.eval.rubric_crud import get_rubric_detail, list_rubrics_with_counts
from src.contracts.classification import NAMED_CONTRACTS, UNNAMED_CONTRACTS


ALL_TYPES = list(NAMED_CONTRACTS.keys()) + list(UNNAMED_CONTRACTS.keys())


@pytest.fixture(autouse=True, scope="module")
def _require_v3_catalog():
    """Skip unless the active DB has a seeded v3 rubric catalog.

    These are integration tests against a catalog DB pre-seeded with v2 + v3
    rubrics (``scripts/seed_v3_rubrics.py``). The hermetic per-session test DB
    (see ``conftest._session_db_name``) only seeds harbor/local rubrics, so no
    v3 rubrics exist there and every assertion would fail. Skip rather than
    report ~60 false failures; run this module in isolation against the dev
    catalog to exercise it.
    """
    try:
        rubrics = list_rubrics_with_counts()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"v3 catalog unavailable: {exc}")
    if not any(r["name"].endswith("_v3") for r in rubrics):
        pytest.skip("no v3 rubrics seeded in active DB (run scripts/seed_v3_rubrics.py)")


class TestV3RubricExistence:
    """Verify v3 rubrics exist for all 41 contract types."""

    @pytest.mark.parametrize("contract_type", sorted(ALL_TYPES))
    def test_v3_rubric_exists(self, contract_type):
        v3_name = f"contract_{contract_type}_v3"
        detail = get_rubric_detail(v3_name)
        assert detail is not None, f"{v3_name} not found"
        assert detail["name"] == v3_name
        assert detail["context"] == "contract"
        assert "优化判定版" in detail["description"]

    def test_v3_rubric_count(self):
        rubrics = list_rubrics_with_counts()
        v3 = [r for r in rubrics if r["name"].endswith("_v3")]
        assert len(v3) == 41, f"Expected 41 v3 rubrics, got {len(v3)}"


class TestV3OptimizedGuidance:
    """Verify v3 has optimized (lenient) guidance for common criteria."""

    def test_governing_law_accepts_recitals(self):
        detail = get_rubric_detail("contract_sale_v3")
        gov = next(c for c in detail["criteria"] if c["name"] == "governing_law_present")
        guidance = gov["guidance"]
        # v3 should accept law references in any section (not just dedicated clause)
        assert "鉴于" in guidance or "任何部分" in guidance, (
            f"governing_law_present guidance not optimized: {guidance}"
        )

    def test_legal_citation_accepts_no_article_numbers(self):
        detail = get_rubric_detail("contract_sale_v3")
        cit = next(c for c in detail["criteria"] if c["name"] == "legal_citation_accuracy")
        guidance = cit["guidance"]
        # v3 should accept law names without exact article numbers
        assert "无论是否标注" in guidance or "名称真实存在" in guidance, (
            f"legal_citation_accuracy guidance not optimized: {guidance}"
        )

    def test_legal_basis_accepts_general_references(self):
        detail = get_rubric_detail("contract_sale_v3")
        basis = next(c for c in detail["criteria"] if c["name"] == "legal_basis_citation")
        guidance = basis["guidance"]
        # v3 should accept general references like "民法典及相关司法解释"
        assert "泛化引用" in guidance or "包括" in guidance, (
            f"legal_basis_citation guidance not optimized: {guidance}"
        )

    def test_clause_completeness_allows_one_missing(self):
        detail = get_rubric_detail("contract_sale_v3")
        comp = next(c for c in detail["criteria"] if c["name"] == "clause_completeness")
        guidance = comp["guidance"]
        # v3 should allow one missing clause
        assert "超过一项" in guidance or "至少包括" in guidance, (
            f"clause_completeness guidance not optimized: {guidance}"
        )

    def test_party_identification_accepts_placeholders(self):
        detail = get_rubric_detail("contract_sale_v3")
        party = next(c for c in detail["criteria"] if c["name"] == "party_identification")
        guidance = party["guidance"]
        # v3 should accept placeholders with role labels
        assert "占位符" in guidance or "角色" in guidance, (
            f"party_identification guidance not optimized: {guidance}"
        )


class TestV3TypeSpecificCriteria:
    """Verify v3 preserves type-specific criteria from v2."""

    @pytest.mark.parametrize("contract_type", ["sale", "employment", "insurance", "ppp_project"])
    def test_type_specific_criteria_preserved(self, contract_type):
        v2 = get_rubric_detail(f"contract_{contract_type}_v2")
        v3 = get_rubric_detail(f"contract_{contract_type}_v3")

        v2_specific = {c["name"] for c in v2["criteria"]} - {
            "party_identification", "governing_law_present",
            "clause_completeness", "legal_citation_accuracy", "legal_basis_citation"
        }
        v3_names = {c["name"] for c in v3["criteria"]}

        # All v2 type-specific criteria should be in v3
        for name in v2_specific:
            assert name in v3_names, f"{contract_type}: type-specific criterion '{name}' missing from v3"

    def test_v3_has_legal_basis_citation(self):
        detail = get_rubric_detail("contract_sale_v3")
        names = {c["name"] for c in detail["criteria"]}
        assert "legal_basis_citation" in names

    def test_v3_criteria_count_matches_v2(self):
        """v3 should have the same number of criteria as v2 (4 base + type-specific + 1 legal_basis)."""
        for ct in ["sale", "lease", "employment"]:
            v2 = get_rubric_detail(f"contract_{ct}_v2")
            v3 = get_rubric_detail(f"contract_{ct}_v3")
            assert len(v3["criteria"]) == len(v2["criteria"]), (
                f"{ct}: v2 has {len(v2['criteria'])} criteria, v3 has {len(v3['criteria'])}"
            )


class TestV3Idempotency:
    """Verify v3 seeding is idempotent (re-running doesn't duplicate)."""

    def test_v3_rubric_names_unique(self):
        rubrics = list_rubrics_with_counts()
        v3_names = [r["name"] for r in rubrics if r["name"].endswith("_v3")]
        assert len(v3_names) == len(set(v3_names)), "Duplicate v3 rubric names found"

    def test_v3_criteria_names_unique_per_rubric(self):
        detail = get_rubric_detail("contract_sale_v3")
        names = [c["name"] for c in detail["criteria"]]
        assert len(names) == len(set(names)), "Duplicate criterion names in v3 rubric"

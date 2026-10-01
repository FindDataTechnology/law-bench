"""Tests for contract type classification (named vs unnamed contracts)."""

from __future__ import annotations

import pytest

from src.contracts.classification import (
    CIVIL_CODE_CHAPTERS,
    NAMED_CONTRACTS,
    UNNAMED_CONTRACTS,
    classify_contract,
    get_civil_code_chapter,
    get_zh_name,
    is_named_contract,
    is_unnamed_contract,
    list_all_contracts,
    list_named_contracts,
    list_unnamed_contracts,
)


class TestNamedContractClassification:
    """Tests for Civil Code named contract classification."""

    @pytest.mark.parametrize("contract_type", sorted(NAMED_CONTRACTS.keys()))
    def test_named_contract_identified(self, contract_type):
        assert is_named_contract(contract_type) is True
        assert is_unnamed_contract(contract_type) is False

    def test_sale_is_named_contract(self):
        assert classify_contract("sale") == "named_contract"

    def test_lease_is_named_contract(self):
        assert classify_contract("lease") == "named_contract"

    def test_loan_is_named_contract(self):
        assert classify_contract("loan") == "named_contract"

    def test_partnership_is_named_contract(self):
        assert classify_contract("partnership") == "named_contract"

    def test_named_contract_count(self):
        assert len(NAMED_CONTRACTS) == 19


class TestUnnamedContractClassification:
    """Tests for unnamed contract classification."""

    @pytest.mark.parametrize("contract_type", sorted(UNNAMED_CONTRACTS.keys()))
    def test_unnamed_contract_identified(self, contract_type):
        assert is_unnamed_contract(contract_type) is True
        assert is_named_contract(contract_type) is False

    def test_company_formation_is_unnamed(self):
        assert classify_contract("company_formation") == "unnamed_contract"

    def test_employment_is_unnamed(self):
        assert classify_contract("employment") == "unnamed_contract"

    def test_insurance_is_unnamed(self):
        assert classify_contract("insurance") == "unnamed_contract"

    def test_ppp_project_is_unnamed(self):
        assert classify_contract("ppp_project") == "unnamed_contract"

    def test_unnamed_contract_count(self):
        assert len(UNNAMED_CONTRACTS) == 22


class TestUnknownContractType:
    """Tests for unknown contract types."""

    def test_unknown_type_defaults_to_unnamed(self):
        # Unknown types default to unnamed (flexible evaluation)
        assert classify_contract("totally_unknown_type") == "unnamed_contract"

    def test_unknown_type_not_named(self):
        assert is_named_contract("totally_unknown_type") is False

    def test_unknown_type_not_unnamed(self):
        assert is_unnamed_contract("totally_unknown_type") is False

    def test_unknown_type_zh_name_is_none(self):
        assert get_zh_name("totally_unknown_type") is None


class TestCivilCodeChapterMapping:
    """Tests for Civil Code chapter mapping."""

    def test_sale_chapter(self):
        chapter = get_civil_code_chapter("sale")
        assert chapter is not None
        assert chapter[0] == 9  # Chapter 9
        assert chapter[1] == "买卖合同"
        assert chapter[2] == (595, 647)

    def test_partnership_chapter(self):
        chapter = get_civil_code_chapter("partnership")
        assert chapter is not None
        assert chapter[0] == 27  # Chapter 27
        assert chapter[2] == (967, 978)

    def test_unnamed_contract_has_no_chapter(self):
        assert get_civil_code_chapter("company_formation") is None
        assert get_civil_code_chapter("employment") is None

    def test_all_named_contracts_have_chapters(self):
        for ct in NAMED_CONTRACTS:
            assert get_civil_code_chapter(ct) is not None, f"{ct} missing chapter"

    def test_chapter_count_matches_named(self):
        assert len(CIVIL_CODE_CHAPTERS) == 19


class TestContractListing:
    """Tests for contract listing functions."""

    def test_list_named_contracts(self):
        named = list_named_contracts()
        assert len(named) == 19
        assert "sale" in named
        assert "lease" in named

    def test_list_unnamed_contracts(self):
        unnamed = list_unnamed_contracts()
        assert len(unnamed) == 22
        assert "company_formation" in unnamed
        assert "employment" in unnamed

    def test_list_all_contracts(self):
        all_contracts = list_all_contracts()
        assert len(all_contracts) == 41

    def test_no_overlap_between_named_and_unnamed(self):
        named = set(list_named_contracts())
        unnamed = set(list_unnamed_contracts())
        assert named.isdisjoint(unnamed)

    def test_all_contracts_is_union(self):
        named = set(list_named_contracts())
        unnamed = set(list_unnamed_contracts())
        all_c = set(list_all_contracts())
        assert all_c == named | unnamed


class TestZhNameLookup:
    """Tests for Chinese name lookup."""

    def test_sale_zh_name(self):
        assert get_zh_name("sale") == "买卖合同"

    def test_company_formation_zh_name(self):
        assert get_zh_name("company_formation") == "公司设立合同"

    def test_insurance_zh_name(self):
        assert get_zh_name("insurance") == "保险合同"

    def test_unknown_zh_name(self):
        assert get_zh_name("unknown") is None

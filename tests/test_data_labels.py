"""Render tests for data-label localization (machine keys -> Chinese display).

Covers the prompts/rubrics/compare list & detail pages rendering localized
labels and display titles in zh (and en), with raw-key fallback for unknown or
user-authored values. Also asserts the JSON API still returns raw machine keys
(localization is presentation-only) and that the client bootstrap
(``window.__LABELS__``) is on the page so ``app.js`` can localize the matrix.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.eval.store import ensure_schema as ensure_store_schema

_NOW = "2026-01-01T00:00:00+00:00"


def _prompt(db, name, contract_type="sale", purpose="drafting",
            prompt_type="baseline", description="d"):
    db.execute(
        "INSERT INTO prompts (name, contract_type, purpose, content, source, "
        "prompt_type, description, created_at) VALUES (%s, %s, %s, 'c', 'local', %s, %s, %s)",
        (name, contract_type, purpose, prompt_type, description, _NOW),
    )
    db.commit()


def _rubric(db, name, context="contract", source="local"):
    db.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description, "
        "created_at) VALUES (%s, %s, %s, NULL, 'd', %s)",
        (name, context, source, _NOW),
    )
    db.commit()


def _compare(db, contract_type="sale", rubric_name="contract_sale_v1",
             gen_mode="drafter-only"):
    ensure_store_schema(db)  # creates compare_runs table (idempotent)
    db.execute(
        "INSERT INTO compare_runs (label, contract_type, rubric_name, task_desc, "
        "gen_mode, n_drafts, created_at) VALUES ('test', %s, %s, 't', %s, 1, %s)",
        (contract_type, rubric_name, gen_mode, _NOW),
    )
    db.commit()


# --- prompts list / detail -------------------------------------------------- #


def test_prompts_list_localized_zh(app_client: TestClient, seeded_db: Path):
    _prompt(seeded_db, "draft_sale")
    html = app_client.get("/prompts?lang=zh").text
    assert "<strong>买卖合同起草</strong>" in html      # display title
    assert "<code>买卖合同</code>" in html              # contract_type label
    assert "<code>起草</code>" in html                  # purpose label
    assert "基线" in html                               # prompt_type label (badge)
    assert "/prompts/draft_sale" in html               # machine name stays the URL


def test_prompts_list_localized_en(app_client: TestClient, seeded_db: Path):
    _prompt(seeded_db, "draft_sale")
    html = app_client.get("/prompts?lang=en").text
    assert "<strong>Sale Drafting</strong>" in html
    assert "<code>Sale</code>" in html
    assert "<code>Drafting</code>" in html
    assert "Baseline" in html


def test_prompts_list_unknown_value_falls_back(app_client: TestClient, seeded_db: Path):
    _prompt(seeded_db, "my_prompt", contract_type="custom_type", prompt_type="weird")
    html = app_client.get("/prompts?lang=zh").text
    # raw keys pass through unchanged (no blank, no crash)
    assert "my_prompt" in html
    assert "<code>custom_type</code>" in html
    assert "weird" in html


def test_prompt_detail_localized_zh(app_client: TestClient, seeded_db: Path):
    _prompt(seeded_db, "draft_loan", contract_type="loan")
    html = app_client.get("/prompts/draft_loan?lang=zh").text
    assert "借款合同起草" in html           # heading + <title>
    assert "<code>借款合同</code>" in html   # contract_type
    assert "<code>起草</code>" in html       # purpose


# --- rubrics list / detail -------------------------------------------------- #


def test_rubrics_list_localized_zh(app_client: TestClient, seeded_db: Path):
    _rubric(seeded_db, "contract_sale_v1")
    html = app_client.get("/rubrics?lang=zh").text
    assert "<strong>买卖合同评价规则 v1</strong>" in html
    assert "/rubrics/contract_sale_v1" in html
    assert "<code>合同</code>" in html          # context label


def test_rubrics_list_localized_en(app_client: TestClient, seeded_db: Path):
    _rubric(seeded_db, "contract_sale_v1")
    html = app_client.get("/rubrics?lang=en").text
    assert "<strong>Sale Rubric v1</strong>" in html
    assert "<code>Contract</code>" in html


def test_rubrics_list_fixture_rubrics_fall_back(app_client: TestClient):
    # h_rubric / l_rubric don't match the seed convention -> raw names shown
    html = app_client.get("/rubrics?lang=zh").text
    assert "h_rubric" in html
    assert "l_rubric" in html
    # but their contexts are still localized (check -> 检查, contract -> 合同)
    assert "<code>检查</code>" in html
    assert "<code>合同</code>" in html


def test_rubric_detail_localized_zh(app_client: TestClient, seeded_db: Path):
    _rubric(seeded_db, "contract_lease_v1")
    html = app_client.get("/rubrics/contract_lease_v1?lang=zh").text
    assert "租赁合同评价规则" in html
    assert "<code>合同</code>" in html


# --- compare list ----------------------------------------------------------- #


def test_compare_list_localized_zh(app_client: TestClient, seeded_db: Path):
    _compare(seeded_db)
    html = app_client.get("/compare?lang=zh").text
    assert "<code>买卖合同</code>" in html                # contract_type
    assert "<code>买卖合同评价规则 v1</code>" in html         # rubric_name title
    assert "<code>仅起草</code>" in html                   # gen_mode


def test_compare_list_localized_en(app_client: TestClient, seeded_db: Path):
    _compare(seeded_db)
    html = app_client.get("/compare?lang=en").text
    assert "<code>Sale</code>" in html
    assert "<code>Sale Rubric v1</code>" in html
    assert "<code>Drafter-only</code>" in html


# --- API stays machine-readable -------------------------------------------- #


def test_api_prompts_returns_raw_keys(app_client: TestClient, seeded_db: Path):
    _prompt(seeded_db, "draft_sale")
    data = app_client.get("/api/prompts?lang=zh").json()
    p = next(x for x in data if x["name"] == "draft_sale")
    assert p["contract_type"] == "sale"      # raw machine key, not 买卖合同
    assert p["purpose"] == "drafting"


# --- client bootstrap (app.js drinks window.__LABELS__) ------------------- #


def test_labels_bootstrap_present_zh(app_client: TestClient):
    # app.js localizes the matrix meta via window.__LABELS__; the zh catalog
    # (incl. contract_type -> 买卖合同) must be bootstrapped on the page.
    html = app_client.get("/compare/1?lang=zh").text
    assert "window.__LABELS__" in html
    assert "买卖合同" in html


def test_labels_bootstrap_present_en(app_client: TestClient):
    html = app_client.get("/compare/1?lang=en").text
    assert "window.__LABELS__" in html
    assert '"Sale"' in html


def test_app_js_has_label_helpers_and_degradation_guard():
    # Smoke test: the client helpers + graceful-degradation guard exist. There
    # is no JS runner in this project; the helper arithmetic mirrors the Python
    # label_for / title_for_* which are unit-tested in test_i18n.py.
    js = (Path(__file__).resolve().parents[1] / "src" / "web" / "static" / "app.js").read_text()
    assert "window.__LABELS__" in js
    assert "function labelFor(" in js
    assert "function titleForPrompt(" in js
    assert "function titleForRubric(" in js
    assert "labelFor('contract_type'" in js          # meta line uses it
    assert "|| {}" in js                              # graceful-degradation guard

"""Tests for the evaluation-rules web UI's multi-locale (zh/en) layer.

Covers: catalog parity (zh/en expose identical key sets), per-request locale
resolution (``?lang`` > cookie > default ``zh``; ``Accept-Language`` is
ignored), the language switcher, localized table headers / ``<html lang>``,
key-based flash messages with interpolation, and that every key referenced by
``app.js`` exists in both catalogs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from src.web.i18n import (
    CRITERION_I18N,
    DEFAULT,
    LABELS,
    LOCALES,
    SUPPORTED,
    criterion_for,
    label_catalog_parity,
    label_for,
    resolve_locale,
    source_label,
    title_for_prompt,
    title_for_rubric,
    translate,
)

# Keys referenced by static/app.js (must exist in both catalogs so the
# client-rendered matrix and criterion-row template localize, degrading to
# the English fallback otherwise).
APP_JS_KEYS = [
    "crit_row.new", "crit_row.remove", "crit_row.name",
    "crit_row.name_placeholder", "crit_row.description", "crit_row.guidance",
    "matrix.select_min", "matrix.running", "matrix.error", "matrix.meta",
    "matrix.headline", "matrix.legend_multi", "matrix.legend_single",
    "matrix.criterion", "matrix.pass", "matrix.fail", "matrix.view_draft",
    "matrix.no_reasoning", "matrix.draft_title", "matrix.loading",
    "matrix.empty_draft", "matrix.not_found", "matrix.error_loading",
]


def _leaf_keys(d, prefix=""):
    out = set()
    for k, v in d.items():
        p = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out |= _leaf_keys(v, p)
        else:
            out.add(p)
    return out


def _flash_q(response):
    return parse_qs(urlparse(response.headers["location"]).query)


# --- catalog ---------------------------------------------------------------- #


def test_supported_and_default():
    assert SUPPORTED == ("zh", "en")
    assert DEFAULT == "zh"


def test_catalog_parity_zh_en():
    zh, en = _leaf_keys(LOCALES["zh"]), _leaf_keys(LOCALES["en"])
    assert zh == en, f"zh-only={zh - en} en-only={en - zh}"


def test_app_js_keys_exist_in_both_catalogs():
    for locale in ("zh", "en"):
        for key in APP_JS_KEYS:
            assert translate(LOCALES[locale], key) != key, f"{locale} missing {key}"


def test_translate_passthrough_on_unknown_key():
    # dynamic error text (not a catalog key) falls through unchanged
    assert translate(LOCALES["zh"], "not.a.real.key") == "not.a.real.key"


def test_translate_interpolation():
    assert translate(LOCALES["en"], "flash.prompt_deleted", name="p1") == "Prompt 'p1' deleted."
    assert translate(LOCALES["zh"], "flash.prompt_deleted", name="p1") == "提示词「p1」已删除。"


def test_translate_stray_braces_do_not_raise_on_passthrough():
    # a passthrough string with a stray brace must not raise (no .format applied)
    assert translate(LOCALES["en"], "boom { unbalanced") == "boom { unbalanced"


# --- data-label catalog (machine keys -> display labels) ------------------ #


def test_label_catalog_parity_zh_en():
    assert label_catalog_parity() is True
    for kind in LABELS["zh"]:
        assert set(LABELS["zh"][kind]) == set(LABELS["en"][kind]), kind


# 19 《民法典》 typical named contract types + 22 practical (中国合同分类法
# Part 2, non-overlapping) types. The catalog MUST contain exactly the union of
# these two sets, in both zh and en - asserting the seed scripts and the label
# catalog stay in lockstep.
CIVIL_CODE_TYPES = {
    "sale", "utilities_supply", "gift", "loan", "guarantee", "lease",
    "financing_lease", "factoring", "work", "construction", "transport",
    "technology", "bailment", "warehousing", "entrustment",
    "property_service", "brokerage", "intermediation", "partnership",
}
PRACTICAL_TYPES = {
    "company_formation", "equity_transfer", "capital_increase",
    "merger_acquisition", "equity_incentive", "vam_agreement",
    "equity_holding_in_trust", "real_estate_sale", "real_estate_lease",
    "employment", "labor_dispatch", "ip_license", "franchise",
    "real_estate_development", "insurance", "trust", "private_equity_fund",
    "software_development", "film_production", "talent_agency",
    "ppp_project", "tourism_service",
}


def test_label_catalog_has_all_seeded_contract_types():
    expected = CIVIL_CODE_TYPES | PRACTICAL_TYPES
    for locale in ("zh", "en"):
        assert set(LABELS[locale]["contract_type"]) == expected, locale
    # guard against a silent duplicate of a 民法典 type sneaking into practical
    assert CIVIL_CODE_TYPES.isdisjoint(PRACTICAL_TYPES)


def test_label_for_known_and_unknown():
    assert label_for("contract_type", "sale", "zh") == "买卖合同"
    assert label_for("contract_type", "sale", "en") == "Sale"
    assert label_for("purpose", "drafting", "zh") == "起草"
    assert label_for("mode", "drafter-only", "zh") == "仅起草"
    assert label_for("context", "check", "zh") == "检查"
    assert label_for("prompt_type", "baseline", "zh") == "基线"
    assert label_for("prompt_type", "law-refined", "zh") == "法律精修"
    assert label_for("prompt_type", "law-refined", "en") == "Law-refined"
    # unknown value -> raw passthrough
    assert label_for("contract_type", "custom_type", "zh") == "custom_type"
    # unknown kind -> raw passthrough
    assert label_for("nope", "sale", "zh") == "sale"
    # default locale is zh
    assert label_for("contract_type", "sale") == "买卖合同"


def test_title_for_prompt_seeded_and_fallback():
    assert title_for_prompt("draft_sale", "zh") == "买卖合同起草"
    assert title_for_prompt("draft_sale", "en") == "Sale Drafting"
    assert title_for_prompt("draft_financing_lease", "zh") == "融资租赁合同起草"
    # _vN variant suffix disambiguates the law-refined variant from baseline.
    assert title_for_prompt("draft_sale_v2", "zh") == "买卖合同起草 v2"
    assert title_for_prompt("draft_sale_v2", "en") == "Sale Drafting v2"
    # non-conforming name -> raw
    assert title_for_prompt("my_custom", "zh") == "my_custom"
    # pattern match but unknown type key -> raw
    assert title_for_prompt("draft_custom", "zh") == "draft_custom"
    # user-authored Chinese name passes through
    assert title_for_prompt("我的提示词", "zh") == "我的提示词"


def test_title_for_rubric_seeded_and_fallback():
    assert title_for_rubric("contract_sale_v1", "zh") == "买卖合同评价规则 v1"
    assert title_for_rubric("contract_lease_v1", "en") == "Lease Rubric v1"
    assert title_for_rubric("contract_financing_lease_v1", "zh") == "融资租赁合同评价规则 v1"
    assert title_for_rubric("contract_sale_v2", "zh") == "买卖合同评价规则 v2"
    # non-conforming name -> raw (the fixture's seeded test rubrics)
    assert title_for_rubric("l_rubric", "zh") == "l_rubric"
    assert title_for_rubric("h_rubric", "zh") == "h_rubric"
    # user-authored Chinese name passes through
    assert title_for_rubric("我的规则", "zh") == "我的规则"


# --- seeded criterion-content + rubric-source localization ----------------- #

HARBOR_SEED_DIR = Path(__file__).resolve().parents[1] / "src" / "eval" / "seed" / "harbor"


def _harbor_criterion_names() -> set[str]:
    """Every criterion ``name`` declared in the harbor seed TOMLs."""
    import tomllib

    names: set[str] = set()
    for toml in ("task_quality.toml", "trial_behavior.toml"):
        with open(HARBOR_SEED_DIR / toml, "rb") as f:
            for c in tomllib.load(f).get("criteria", []):
                names.add(c["name"])
    return names


def test_criterion_i18n_covers_all_harbor_seeds():
    # Every harbor-seeded criterion name MUST have a zh translation, so a new
    # seed criterion can't silently leak English on the rubric detail page.
    names = _harbor_criterion_names()
    assert names  # sanity: the seed files actually contributed names
    zh = CRITERION_I18N.get("zh", {})
    for name in names:
        assert name in zh, f"missing zh criterion i18n for {name!r}"
        for field in ("title", "description", "guidance"):
            assert zh[name].get(field), f"empty {field!r} for criterion {name!r}"


REPO_ROOT = Path(__file__).resolve().parents[1]


def _contract_criterion_names() -> set[str]:
    """Every criterion ``name`` declared in the contract rubric seed script."""
    import importlib.util

    scripts = REPO_ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location(
            "seed_contract_rubrics", scripts / "seed_contract_rubrics.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        sys.path.pop(0)
    names: set[str] = set()
    for c in m.BASE_CRITERIA:
        names.add(c["name"])
    for r in m.RUBRICS:
        for c in r["criteria"]:
            names.add(c["name"])
    return names


def test_criterion_i18n_titles_cover_all_contract_seeds():
    # Every contract-seeded criterion name MUST have a zh title, so a new seed
    # criterion can't silently leak its snake_case name as the heading.
    names = _contract_criterion_names()
    assert names  # sanity
    zh = CRITERION_I18N.get("zh", {})
    for name in names:
        assert name in zh, f"missing zh criterion i18n for {name!r}"
        assert zh[name].get("title"), f"empty title for criterion {name!r}"


def test_criterion_for_seeded_zh_and_fallback():
    # zh locale + seeded name -> localized field
    assert criterion_for("behavior_in_task_description", "title", "zh") == "测试行为在任务说明中描述"
    assert (
        criterion_for("typos", "description", "zh")
        == "是否存在任何拼写错误。请仔细查看文件名和变量名，因为这些可能难以发现。"
    )
    # default locale is zh
    assert criterion_for("typos", "title") == "拼写错误"
    # fallback returned for unknown name / en locale / unknown field
    assert criterion_for("unknown_criterion", "title", "zh", fallback="raw") == "raw"
    assert criterion_for("behavior_in_task_description", "title", "en", fallback="raw") == "raw"
    assert criterion_for("behavior_in_task_description", "nope", "zh", fallback="raw") == "raw"
    # no fallback -> empty string (never raises)
    assert criterion_for("unknown_criterion", "title", "zh") == ""


def test_source_label_local_harbor_and_unknown():
    assert source_label("local", "zh") == "本地"
    assert source_label("local", "en") == "local"
    assert source_label("harbor:v0.4.2", "zh") == "Harbor v0.4.2"
    assert source_label("harbor:v0.4.2", "en") == "Harbor v0.4.2"
    assert source_label("harbor:unknown", "zh") == "Harbor"
    assert source_label("import:foo", "zh") == "import:foo"
    assert source_label(None, "zh") == ""
    # default locale is zh
    assert source_label("local") == "本地"


# --- locale resolution (end-to-end via middleware) ------------------------- #


def test_default_locale_is_zh(app_client: TestClient):
    r = app_client.get("/rubrics", follow_redirects=False)
    assert "lang=zh" in r.headers.get("set-cookie", "")


def test_query_param_overrides_cookie(app_client: TestClient):
    app_client.get("/rubrics?lang=en")          # set cookie to en
    r = app_client.get("/rubrics?lang=zh")       # explicit zh wins
    assert "lang=zh" in r.headers.get("set-cookie", "")


def test_cookie_honored_without_query(app_client: TestClient):
    app_client.get("/rubrics?lang=en")           # persist en
    r = app_client.get("/rubrics")               # no ?lang -> cookie wins
    assert "lang=en" in r.headers.get("set-cookie", "")


def test_unknown_locale_falls_back_to_default(app_client: TestClient):
    r = app_client.get("/rubrics?lang=fr")
    assert "lang=zh" in r.headers.get("set-cookie", "")


def test_accept_language_ignored_defaults_to_zh(app_client: TestClient):
    # Accept-Language is deliberately not consulted; first visit is always zh,
    # even when the browser advertises English.
    r = app_client.get("/rubrics", headers={"accept-language": "en-US,en;q=0.9"})
    assert "lang=zh" in r.headers.get("set-cookie", "")


def test_accept_language_unsupported_ignored(app_client: TestClient):
    # an unsupported Accept-Language is also ignored -> zh default
    r = app_client.get("/rubrics", headers={"accept-language": "fr-FR"})
    assert "lang=zh" in r.headers.get("set-cookie", "")


# --- localized rendering ---------------------------------------------------- #


def test_html_lang_attribute(app_client: TestClient):
    assert '<html lang="zh">' in app_client.get("/rubrics?lang=zh").text
    assert '<html lang="en">' in app_client.get("/rubrics?lang=en").text


def test_table_header_localized(app_client: TestClient):
    assert "<th>名称</th>" in app_client.get("/rubrics?lang=zh").text
    assert "<th>Name</th>" in app_client.get("/rubrics?lang=en").text


def test_locale_bootstrap_present(app_client: TestClient):
    # app.js drinks from window.__LOCALE__; the zh catalog must be on the page
    r = app_client.get("/compare/1?lang=zh")
    assert "window.__LOCALE__" in r.text
    assert '"criterion": "评分项"' in r.text


def test_switcher_marks_active_locale(app_client: TestClient):
    zh = app_client.get("/rubrics?lang=zh").text
    assert 'href="/rubrics?lang=en"' in zh
    assert 'lang=zh" aria-current="true"' in zh
    en = app_client.get("/rubrics?lang=en").text
    assert 'lang=en" aria-current="true"' in en


def test_rubric_detail_localizes_zh(app_client: TestClient, seeded_db):
    # Add a seeded-name criterion to the harbor rubric so the zh catalog kicks in.
    h_id = seeded_db.execute(
        "SELECT id FROM rubrics WHERE name = 'h_rubric'"
    ).fetchone()["id"]
    seeded_db.execute(
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "VALUES (%s, 'behavior_in_task_description', 'English desc', 'English guidance', 5)",
        (h_id,),
    )
    seeded_db.commit()

    # Harbor detail page in zh: criterion content localized, source labeled,
    # and the raw source string nowhere on the page.
    h = app_client.get("/rubrics/h_rubric?lang=zh").text
    assert "测试脚本所检查的全部行为是否都在任务说明中描述" in h  # zh description
    assert "English desc" not in h                              # stored English not shown
    assert "Harbor v0.20.0" in h                                # localized source label
    assert "harbor:v0.20.0" not in h                            # raw source not leaked

    # en locale: criterion content falls back to the stored English text.
    h_en = app_client.get("/rubrics/h_rubric?lang=en").text
    assert "English desc" in h_en
    assert "测试脚本所检查的全部行为是否都在任务说明中描述" not in h_en

    # Local detail page in zh: add-criterion placeholder localized, source 本地.
    l = app_client.get("/rubrics/l_rubric?lang=zh").text
    assert "如：party_identification" in l                       # zh placeholder
    assert "e.g. party_identification" not in l                 # English placeholder gone
    assert "本地" in l                                           # localized source label


def test_contract_criterion_title_and_guidance_localized(app_client: TestClient, seeded_db):
    # A contract criterion (seeded name + PASS if/FAIL if guidance) on a local
    # rubric: zh title rendered from the catalog, guidance tokens localized.
    l_id = seeded_db.execute(
        "SELECT id FROM rubrics WHERE name = 'l_rubric'"
    ).fetchone()["id"]
    seeded_db.execute(
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "VALUES (%s, 'party_identification', '是否清晰识别全部合同主体？', "
        "'PASS if 每一方均以完整法律主体名称列明；FAIL if 任一主体未列明。', 9)",
        (l_id,),
    )
    seeded_db.commit()

    zh = app_client.get("/rubrics/l_rubric?lang=zh").text
    # zh title rendered from the catalog, not the snake_case name, as the heading.
    assert "合同主体识别" in zh
    # read-only guidance display localized to 通过条件 / 不通过条件. (The inline
    # edit form keeps the raw stored "PASS if …" for editing, so we assert the
    # localized tokens are present rather than that the raw tokens are absent.)
    assert "通过条件：每一方均以完整法律主体名称列明" in zh
    assert "不通过条件：任一主体未列明" in zh

    # en locale: title falls back to the raw name; guidance left untouched.
    en = app_client.get("/rubrics/l_rubric?lang=en").text
    assert "party_identification" in en
    assert "PASS if" in en


# --- flash messages: keys + interpolation ----------------------------------- #


def test_static_flash_emits_key_and_renders_zh(app_client: TestClient):
    r = app_client.post(
        "/rubrics",
        data={"name": "r_i18n", "context": "contract", "description": "d"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    q = _flash_q(r)
    assert q["msg"][0] == "flash.rubric_created"
    assert "err" not in q
    page = app_client.get(r.headers["location"], follow_redirects=True)
    assert "规则已创建" in page.text


def test_interpolated_flash_renders_both_locales(app_client: TestClient):
    app_client.post(
        "/prompts",
        data={
            "name": "p_del", "contract_type": "sale", "purpose": "drafting",
            "content": "x",
        },
        follow_redirects=False,
    )
    r = app_client.post("/prompts/p_del/delete", follow_redirects=False)
    assert r.status_code == 303
    q = _flash_q(r)
    assert q["msg"][0] == "flash.prompt_deleted"
    assert q["name"][0] == "p_del"
    loc = r.headers["location"]
    sep = "&" if "?" in loc else "?"
    en = app_client.get(loc + sep + "lang=en", follow_redirects=True).text
    assert "deleted" in en and "p_del" in en
    zh = app_client.get(loc + sep + "lang=zh", follow_redirects=True).text
    assert "提示词「p_del」已删除" in zh


def test_resolve_locale_unit():
    # direct unit check of the resolver precedence (no HTTP)
    from starlette.requests import Request

    def req(query="", cookie=None, accept=None):
        scope = {"type": "http", "headers": [], "query_string": query.encode()}
        if cookie:
            scope["headers"].append((b"cookie", f"lang={cookie}".encode()))
        if accept:
            scope["headers"].append((b"accept-language", accept.encode()))
        return Request(scope)

    assert resolve_locale(req("lang=en"))[0] == "en"
    assert resolve_locale(req("", cookie="en"))[0] == "en"
    assert resolve_locale(req("", accept="en-US,en;q=0.9"))[0] == "zh"  # ignored -> default
    assert resolve_locale(req("lang=fr"))[0] == "zh"          # unknown -> default
    assert resolve_locale(req(""))[0] == "zh"                 # nothing -> default

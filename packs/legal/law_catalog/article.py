"""Article-level citation resolution: "民法典第1085条" → (law_id, 条文文本).

Parser ported from law-rag-pipeline ``cluster/law-query-api.js``
(``parseCitation``/``cnToInt``/``intToCn``, reference copy at
``scripts/dev/_ref_law-query-api.js``) — the citation SYNTAX is the original
behavior; the RESOLUTION data source is replaced: Qdrant chunk scrolling is
swapped for the batch-1 name-resolution ladder + law-api full-text retrieval.

Outcomes are distinct (never conflated):
  resolved          - law matched, article located
  unresolved_name   - the law-name hint failed the catalog resolution ladder
  fetch_failed      - law matched but law-api full text unavailable
  out_of_range      - law fetched but has no such article number

law_id values from law-api are opaque strings; joins against the integer
catalog replica convert to str at this boundary only.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from src.eval.db import connect, now_iso

from . import store
from .resolve import LawCatalogIndex, normalize_name

logger = logging.getLogger("law_catalog.article")

# --- numeral conversion (ported from law-query-api.js) -----------------------

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_to_int(s: str) -> Optional[int]:
    """Chinese-numeral (or arabic) string → int; ported behavior, incl. 一百五=105."""
    if s.isdigit():
        return int(s)
    total = section = num = 0
    for ch in s:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch == "十":
            section += (num or 1) * 10
            num = 0
        elif ch == "百":
            section += (num or 1) * 100
            num = 0
        elif ch == "千":
            section += (num or 1) * 1000
            num = 0
        elif ch == "万":
            section = (section + num) * 10000
            num = 0
            total += section
            section = 0
        else:
            return None
    return total + section + num


def int_to_cn(n: int) -> str:
    """Arabic → Chinese numeral as statutes write them (1085 → 一千零八十五)."""
    digits = "零一二三四五六七八九"
    if n == 0:
        return "零"
    units = ["", "十", "百", "千"]
    s = ""
    zero = False
    for i, ch in enumerate(str(n)):
        d = int(ch)
        pos = len(str(n)) - 1 - i
        if d == 0:
            zero = True
            continue
        if zero:
            s += "零"
            zero = False
        s += digits[d] + units[pos]
    return s[1:] if s.startswith("一十") else s


# --- citation parsing ---------------------------------------------------------

# law hint = up to 16 CJK/latin/《》 chars before 第X条; article in arabic or
# chinese numerals; optional 款/项 sub-parts preserved as raw strings.
_CITE_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z《》〈〉]{2,16}?)"
    r"第([0-9零一二三四五六七八九十百千]+)条"
    r"(第[0-9零一二三四五六七八九十百千]+[款项])?"
)
_LEADING_VERBS = re.compile(r".*(查询|看看|找|搜|检索)")
# Contract self-references ("本合同第十条", "如违反本协议第七条") cite the
# contract's own clauses, not a statute — they must never reach the law
# resolution ladder.
_SELF_REF = re.compile(r"(本合同|本协议|本合同条款|本细则|本办法)")
# leading prepositions ("根据民法典" → "民法典") — the JS original relied on the
# semantic-search fallback to absorb these; our hint goes straight to the name
# ladder, so they must be stripped here.
_LEADING_PREPS = re.compile(r"^(?:根据|依据|依照|按照|遵照|按|适用于?|其中)+")
_BRACKET = re.compile(r"[《〈]([^》〉]+)[》〉]")


def _clean_hint(raw: str) -> str:
    """Extract the law name from the captured pre-第X条 text.

    Bracketed text wins verbatim (《中华人民共和国民法典》 — never blind-strip
    connectors, they eat 和 out of 共和国); bare hints get leading verbs,
    prepositions, and connector chars stripped ("依据的关于保险法" → "保险法").
    """
    bracketed = _BRACKET.search(raw)
    if bracketed:
        return bracketed.group(1).strip()
    hint = _LEADING_VERBS.sub("", raw)
    hint = _LEADING_PREPS.sub("", hint)
    return hint.lstrip("的关于及和与").strip()


@dataclass
class ArticleCite:
    raw: str
    law_hint: str
    article: int
    sub_parts: list[str] = field(default_factory=list)
    span: tuple[int, int] = (0, 0)


def parse_citations(text: str) -> list[ArticleCite]:
    """All distinct article citations in ``text``, in first-occurrence order."""
    out: list[ArticleCite] = []
    seen: set[tuple[str, int]] = set()
    for m in _CITE_RE.finditer(text):
        article = cn_to_int(m.group(2))
        if not article or article > 9999:
            continue
        hint = _clean_hint(m.group(1))
        if len(hint) < 2:
            continue
        if _SELF_REF.search(m.group(1)):
            continue  # the contract citing its own clauses, not a statute
        raw = m.group(0)
        key = (hint, article)
        if key in seen:
            continue
        seen.add(key)
        subs = [m.group(3)] if m.group(3) else []
        out.append(ArticleCite(raw=raw, law_hint=hint, article=article,
                               sub_parts=subs, span=m.span()))
    return out


# --- article location ---------------------------------------------------------

def _article_anchor_re(article: int) -> re.Pattern:
    arabic = rf"^\s*第{article}条"
    chinese = rf"^\s*第{int_to_cn(article)}条"
    return re.compile(rf"(?:{arabic}|{chinese})")


def find_article(full_text: str, article: int) -> Optional[str]:
    """Locate 第<article>条 in the assembled law text (arabic or chinese anchor).

    Anchors must sit at a line start so mid-sentence references ("本法第X条")
    don't match; a leading page-footer dash is tolerated (extracted texts run
    "—７９—\\n—第六百七十三条", the footer dash landing on the anchor line), and
    so is a chapter heading glued to the first article of a chapter
    ("第二章 一般处置要求 第十条" — blank-line loss in extraction). The
    optional chapter prefix must not itself contain 第…条, so a mid-sentence
    reference after a chapter heading still cannot match.
    Returns the article's text (anchor → next anchor / end) or None when the
    number is beyond the statute's length (or the article is missing from the
    assembled text).
    """
    anchors = []
    for m in re.finditer(
        r"^\s*[—\-]?\s*(?:第[一二三四五六七八九十百千]+章[^\n第]{0,30}?)?\s*"
        # statute self-references ("本办法第十条") never start an article,
        # even when a chapter heading could otherwise absorb the lead-in
        r"(?<!本办法)(?<!本法)(?<!本条例)(?<!本规定)(?<!本细则)"
        r"(?P<anchor>第[0-9零一二三四五六七八九十百千]+条)",
        full_text, re.M,
    ):
        # the anchor is where the article begins (chapter-heading prefix
        # excluded from the article text)
        anchors.append((m.start("anchor"), m.group("anchor")))
    for i, (pos, label) in enumerate(anchors):
        num = cn_to_int(label[1:-1])
        if num == article:
            end = anchors[i + 1][0] if i + 1 < len(anchors) else len(full_text)
            return full_text[pos:end].strip()
    return None


def _hint_candidates(hint: str) -> list[str]:
    """The hint plus its right-anchored suffixes, longest first (cap 6).

    Clause bodies prefix law names with arbitrary text ("只引民法典",
    "本合同依据旅游法"); a suffix of the pre-第 text is the law name. The
    resolver runs candidates longest→shortest; junk prefixes fall away.
    """
    out = [hint]
    for i in range(1, max(len(hint) - 1, 1)):
        cand = hint[i:]
        if len(cand) >= 2:
            out.append(cand)
        if len(out) >= 6:
            break
    return out


class CachedIndex:
    """Name-resolution cache around :class:`LawCatalogIndex`.

    A corpus pass resolves the same handful of law names (民法典, 劳动合同法…)
    hundreds of times; every miss would otherwise re-run the trigram query.
    Cache key: normalized cited name.
    """

    def __init__(self, index: LawCatalogIndex) -> None:
        self._index = index
        self._cache: dict[str, dict] = {}

    def resolve(self, name: str, db=None) -> dict:
        key = normalize_name(name)
        if key not in self._cache:
            self._cache[key] = self._index.resolve(name, db=db)
        return self._cache[key]


# --- end-to-end resolution ----------------------------------------------------

_OUTCOMES = ("resolved", "unresolved_name", "fetch_failed", "out_of_range")


def resolve_article(cite: ArticleCite, index: LawCatalogIndex,
                    client=None, fetch_cache: Optional[dict] = None) -> dict:
    """Resolve one citation to (law_id, article ordinal, article text, status).

    Hint resolution tries suffix candidates longest→shortest but accepts only
    exact/alias matches for them (trigram on a junk suffix fragment would be a
    false positive); the full hint falls back to the complete ladder.
    ``fetch_cache`` (law_id_str → get_law result) lets a batch pass fetch each
    statute once; outcomes are distinct per ``_OUTCOMES``.
    """
    name_res = None
    for cand in _hint_candidates(cite.law_hint):
        res = index.resolve(cand)
        if res["resolved_via"] in ("exact", "alias") and res["law_id"] is not None:
            name_res = res
            break
    if name_res is None:
        name_res = index.resolve(cite.law_hint)
    if name_res["resolved_via"] == "unresolved" or name_res["law_id"] is None:
        return {"cite": cite, "outcome": "unresolved_name", "law_id": None,
                "article_text": None, "law_status": None}
    law_id = str(name_res["law_id"])  # opaque string at the law-api boundary
    cache = fetch_cache if fetch_cache is not None else {}
    if law_id not in cache:
        from src.law_api import client as law_api

        cache[law_id] = law_api.get_law(law_id, client=client)
    law = cache[law_id]
    if law is None or not law.get("full_text"):
        return {"cite": cite, "outcome": "fetch_failed", "law_id": law_id,
                "article_text": None,
                "law_status": law.get("status") if law else name_res["status"]}
    text = find_article(law["full_text"], cite.article)
    if text is None:
        return {"cite": cite, "outcome": "out_of_range", "law_id": law_id,
                "article_text": None, "law_status": law.get("status")}
    return {"cite": cite, "outcome": "resolved", "law_id": law_id,
            "article_text": text, "law_status": law.get("status")}


def resolve_all_article_citations(db=None, client=None) -> dict:
    """Re-runnable full pass: every article citation in clause bodies → link layer.

    Reads clause bodies (read-only), parses article citations, resolves each
    via :func:`resolve_article` (one full-text fetch per distinct law), and
    batch-upserts ``law_catalog.clause_article_refs`` (stale rows pruned).
    """
    conn = connect(db)
    try:
        clauses = conn.execute(
            "SELECT id, contract_type, body FROM clauses ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    index = CachedIndex(LawCatalogIndex(db=db))
    fetch_cache: dict[str, Optional[dict]] = {}
    rows: list[tuple] = []
    current: set[tuple] = set()
    outcomes = {o: 0 for o in _OUTCOMES}

    for c in clauses:
        cites = parse_citations(c["body"] or "")
        for cite in cites:
            current.add((c["id"], cite.raw, cite.article))
            res = resolve_article(cite, index, client=client, fetch_cache=fetch_cache)
            outcomes[res["outcome"]] += 1
            rows.append((c["id"], c["contract_type"], cite.raw, cite.article,
                         res["law_id"], res["article_text"], res["law_status"],
                         res["outcome"], now_iso()))

    _write_article_rows(rows, current, db=db)
    return {"clauses": len(clauses), "citations": len(rows),
            "distinct_laws_fetched": len(fetch_cache), "outcomes": outcomes}


def _write_article_rows(rows: list[tuple], current: set, db=None) -> None:
    conn = connect(db)
    try:
        store.ensure_schema(conn)
        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO law_catalog.clause_article_refs "
                    "(clause_id, contract_type, citation, article_ordinal, law_id, "
                    " article_text, law_status, outcome, resolved_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (clause_id, citation, article_ordinal) DO UPDATE SET "
                    "contract_type = EXCLUDED.contract_type, law_id = EXCLUDED.law_id, "
                    "article_text = EXCLUDED.article_text, law_status = EXCLUDED.law_status, "
                    "outcome = EXCLUDED.outcome, resolved_at = EXCLUDED.resolved_at",
                    rows,
                )
                cur.execute("DROP TABLE IF EXISTS _law_catalog_current_articles")
                cur.execute(
                    "CREATE TEMP TABLE _law_catalog_current_articles "
                    "(clause_id BIGINT, citation TEXT, article_ordinal INT) ON COMMIT DROP"
                )
                if current:
                    cur.executemany(
                        "INSERT INTO _law_catalog_current_articles "
                        "(clause_id, citation, article_ordinal) VALUES (%s, %s, %s)",
                        list(current),
                    )
                cur.execute(
                    "DELETE FROM law_catalog.clause_article_refs r "
                    "WHERE NOT EXISTS (SELECT 1 FROM clauses c WHERE c.id = r.clause_id) "
                    "OR NOT EXISTS (SELECT 1 FROM _law_catalog_current_articles t "
                    "WHERE t.clause_id = r.clause_id AND t.citation = r.citation "
                    "AND t.article_ordinal = r.article_ordinal)"
                )
        conn.commit()
    finally:
        conn.close()

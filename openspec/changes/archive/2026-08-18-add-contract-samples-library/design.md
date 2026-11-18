# Design: Contract Samples Library

## Context

The MinIO corpus (`contract_artifacts` table, 724 rows) is the single source of truth for generated contract samples. Each row carries: `id`, `contract_type`, `tags` (JSONB with `scenario`/`stance` keys, both NULL for the base variant), `body_text`, `body_hash`, `slot_count`, `created_at`. This design adds a read-only browsing layer — no writes, no generation, no slot logic.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    /samples (HTML page)                     │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Filter Form (GET, onchange auto-submit)               │ │
│  │  Type [sale▾] → Scenario [全部▾ 农产品买卖▾ ...]         │ │
│  │  Stance [全部▾ pro_a▾ balanced▾ pro_b▾]  [应用筛选]     │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Table (server-rendered, HTML <table>)                 │ │
│  │  #   Type    Scenario      Stance   Fields  Download   │ │
│  │  724 sale   农产品买卖    balanced  9      [d][p]       │ │
│  │  723 sale   NULL          pro_a    9      [d][p]       │ │
│  │  ...                                                   │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                             │
│  Pagination: ◀ 上一页  第 1/15 页  下一页 ▶  (共 724 条)      │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼ GET ?contract_type=&scenario=&stance=&limit=&offset=
┌─────────────────────────────────────────────────────────────┐
│              src/web/routes/samples.py                      │
│  - GET /samples (page route, include_in_schema=False)      │
│  - distinct_scenarios() / distinct_stances() for dropdowns │
│  - list_samples(limit/offset) for filtered rows            │
│  - Renders Jinja2 template                                  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼ SQL (psycopg)
┌─────────────────────────────────────────────────────────────┐
│         src/contracts/artifacts.py (service layer)          │
│  + distinct_scenarios(contract_type) → list[str]            │
│  + distinct_stances(contract_type) → list[str]              │
│  + list_samples(...) → tuple[list[dict], int]               │
│                                                              │
│  (existing untouched: list_artifacts, get_artifact,         │
│   generate_stored, download)                                │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼ StreamingResponse (reused, no new path)
┌─────────────────────────────────────────────────────────────┐
│  Existing: /api/contracts/artifacts/{id}/download?format=   │
│  - <a href> targets → browser triggers stream download      │
└─────────────────────────────────────────────────────────────┘
```

## Service Layer (`src/contracts/artifacts.py`)

Three new functions. All use the existing `_conn(db)` / connection-pool helper pattern already in the module — no new DB plumbing.

```python
def distinct_scenarios(contract_type: str, db: Any = None) -> list[str]:
    """Distinct non-null scenario values for one contract type.

    SELECT DISTINCT tags->>'scenario' FROM contract_artifacts
    WHERE contract_type = %s AND tags->>'scenario' IS NOT NULL
    ORDER BY 1;
    -- Returns ["农产品买卖", "钢材买卖", ...] — excludes base (NULL) rows.
    """

def distinct_stances(contract_type: str, db: Any = None) -> list[str]:
    """Distinct non-null stance values for one contract type.

    SELECT DISTINCT tags->>'stance' FROM contract_artifacts
    WHERE contract_type = %s AND tags->>'stance' IS NOT NULL
    ORDER BY 1;
    -- Returns ["pro_a", "balanced", "pro_b"] (whatever that type has).
    """

def list_samples(
    contract_type: str | None = None,
    scenario: str | None = None,        # None = no filter (includes base/NULL rows)
    stance: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Any = None,
) -> tuple[list[dict], int]:
    """Filtered + paginated artifact metadata (no body_text). Returns (rows, total).

    Dynamic WHERE built from non-None params:
      contract_type → WHERE contract_type = %s
      scenario      → AND tags->>'scenario' = %s   (excludes NULL base rows)
      stance        → AND tags->>'stance' = %s       (excludes NULL base rows)

    Rows query:
      SELECT id, contract_type, tags->>'scenario' AS scenario,
             tags->>'stance' AS stance, slot_count, created_at
      FROM contract_artifacts WHERE ... ORDER BY created_at DESC
      LIMIT %s OFFSET %s;

    Count query (same WHERE, no LIMIT/OFFSET):
      SELECT COUNT(*) FROM contract_artifacts WHERE ...;

    Row shape: {"id", "contract_type", "scenario", "stance",
                "slot_count", "created_at"}  (scenario/stance may be None)
    """
```

**Why split `list_samples` from `list_artifacts`** instead of extending the latter: `list_artifacts` is a public API-backed function with a stable `[dict]` return contract (used by `/api/contracts/artifacts`). Changing it to return a tuple would break that route. A separate function keeps the API stable and lets the page route get `(rows, total)` without a second round-trip pattern leaking into the API.

## Route Handler (`src/web/routes/samples.py`)

Mirrors `src/web/routes/pages.py` conventions: `Request`-based, `_templates.TemplateResponse`, `DbConn = Depends(get_db)`.

```python
from fastapi import APIRouter, Depends, Query, Request
from src.web.templating import templates as _templates
from src.web.models import DbConn, get_db
from src.web.routes.pages import list_contract_types  # reuse existing type list
from src.contracts.artifacts import (
    distinct_scenarios, distinct_stances, list_samples,
)

router = APIRouter(tags=["samples"])

@router.get("/samples", include_in_schema=False, name="page_samples")
def page_samples(
    request: Request,
    contract_type: str | None = Query(None),
    scenario: str | None = Query(None),
    stance: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: DbConn = Depends(get_db),
):
    all_types = list_contract_types(db=db)          # [{key, zh}, ...]
    scen_opts, stance_opts = [], []
    if contract_type:
        scen_opts = distinct_scenarios(contract_type, db=db)
        stance_opts = distinct_stances(contract_type, db=db)

    rows, total = list_samples(
        contract_type, scenario, stance, limit, offset, db=db
    )
    return _templates.TemplateResponse(request, "samples.html", {
        "all_types": all_types,
        "artifacts": rows,
        "total": total,
        "limit": limit, "offset": offset,
        "has_next": offset + limit < total,
        "has_prev": offset > 0,
        "selected_ct": contract_type,
        "selected_scenario": scenario,
        "selected_stance": stance,
        "scen_opts": scen_opts,
        "stance_opts": stance_opts,
    })
```

**Route-name dependency**: the template's `url_for('download_artifact_route', ...)` requires that the existing download route is registered with `name="download_artifact_route"`. This must be verified against `src/web/routes/contract_context.py` during implementation — if the actual name differs, either alias it or use the literal path string.

## Template (`src/web/templates/samples.html`)

```html
{% extends "base.html" %}
{% block title %}合同样本库{% endblock %}

{% block content %}
<div class="container">
  <h1>合同样本库</h1>

  <form method="GET" action="{{ url_for('page_samples') }}" class="filter-form">
    <div class="filter-group">
      <label>合同类型</label>
      <select name="contract_type" onchange="this.form.submit()">
        <option value="">全部类型</option>
        {% for ct in all_types %}
        <option value="{{ ct.key }}"
          {% if selected_ct == ct.key %}selected{% endif %}>{{ ct.zh }}</option>
        {% endfor %}
      </select>
    </div>

    <div class="filter-group">
      <label>业务场景</label>
      <select name="scenario" onchange="this.form.submit()">
        <option value="">全部场景</option>
        {% for s in scen_opts %}
        <option value="{{ s }}" {% if selected_scenario == s %}selected{% endif %}>{{ s }}</option>
        {% endfor %}
      </select>
    </div>

    <div class="filter-group">
      <label>立场</label>
      <select name="stance" onchange="this.form.submit()">
        <option value="">全部立场</option>
        {% for s in stance_opts %}
        <option value="{{ s }}" {% if selected_stance == s %}selected{% endif %}>{{ s }}</option>
        {% endfor %}
      </select>
    </div>

    <noscript><button type="submit">应用筛选</button></noscript>
  </form>

  <table class="data-table">
    <thead>
      <tr><th>#</th><th>合同类型</th><th>业务场景</th><th>立场</th><th>字段数</th><th>下载</th></tr>
    </thead>
    <tbody>
      {% for a in artifacts %}
      <tr>
        <td>{{ offset + loop.index }}</td>
        <td>{{ a.contract_type }}</td>
        <td>{% if a.scenario %}{{ a.scenario }}{% else %}—{% endif %}</td>
        <td>{% if a.stance %}{{ a.stance }}{% else %}—{% endif %}</td>
        <td>{{ a.slot_count }}</td>
        <td>
          <a href="{{ url_for('download_artifact_route', artifact_id=a.id, format='docx') }}" class="btn btn-sm">DOCX</a>
          <a href="{{ url_for('download_artifact_route', artifact_id=a.id, format='pdf') }}" class="btn btn-sm">PDF</a>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <div class="pagination">
    {% if has_prev %}
    <a href="?contract_type={{ selected_ct|urlencode }}&amp;scenario={{ selected_scenario|urlencode }}&amp;stance={{ selected_stance|urlencode }}&amp;limit={{ limit }}&amp;offset={{ offset - limit }}" class="btn btn-sm">◀ 上一页</a>
    {% endif %}
    <span class="page-info">第 {{ (offset // limit) + 1 }}/{{ ((total + limit - 1) // limit) }}页 (共 {{ total }}条)</span>
    {% if has_next %}
    <a href="?contract_type={{ selected_ct|urlencode }}&amp;scenario={{ selected_stance|urlencode }}&amp;stance={{ selected_stance|urlencode }}&amp;limit={{ limit }}&amp;offset={{ offset + limit }}" class="btn btn-sm">下一页 ▶</a>
    {% endif %}
  </div>
</div>
{% endblock %}
```

## Key Decisions

| Decision | Chosen | Rationale |
|---|---|---|
| Show layer | 724 artifacts (not 66 type masters) | User confirmed; these are the final downloadable products |
| Pagination backend vs frontend | Backend `LIMIT/OFFSET` | User confirmed; cheaper first paint, scales if corpus grows |
| Filter state model | Binary: "全部" (= no WHERE clause) \| specific value | User confirmed semantics; "全部" naturally includes base (NULL) rows |
| Scenario/stance options source | `SELECT DISTINCT` on `contract_artifacts` per type | Scenario is type-specific (not a global list); options reflect real data |
| New JSON API endpoint? | No — page is server-rendered | Minimal surface; no client needs an AJAX list endpoint |
| Download path | Reuse `/api/contracts/artifacts/{id}/download` | Existing `StreamingResponse` works as an `<a href>` target with no JS |
| Modify `list_artifacts()`? | No — add `list_samples()` separately | Keeps the existing API route's `[dict]` contract stable |
| Field-name expand/collapse | Pure-frontend JS toggle on an optional column | Nice-to-have; progressive enhancement, no server round-trip |

## NULL Handling (the one subtle point)

Base variants (no scenario, no stance) store `tags->>'scenario' = NULL` and `tags->>'stance' = NULL`. With the binary filter model:

- **"全部场景"** (`scenario=None`) → no `scenario` clause in WHERE → base rows included. ✓
- **Selecting "农产品买卖"** (`scenario='农产品买卖'`) → `WHERE tags->>'scenario' = '农产品买卖'` → base rows excluded. ✓

This is exactly the intended semantics: "全部" shows everything including base; a specific value narrows to that variant only. No `IS NULL` special-casing needed.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| `download_artifact_route` name mismatch in template `url_for` | Medium | Verify the actual route name in `contract_context.py` before wiring template; alias or use literal path if needed |
| `list_contract_types` import path / signature differs from assumption | Low | Check `pages.py` for the real helper; adjust import during implementation |
| Large `body_text` column accidentally pulled into list query | Medium | `list_samples` selects only metadata columns, never `body_text` — enforced in SQL projection |
| Scenario dropdown empty when type has only base variants (e.g. `mortgage`, `will`) | None (expected) | Dropdown shows only "全部场景"; user sees base rows — correct behavior |

## Acceptance Criteria

- `/samples` returns 200 and renders a paginated artifact table (default 50/page).
- Contract-type `<select>` is always populated with all 66 types; choosing one reloads and populates scenario/stance `<select>`s from that type's distinct values.
- Scenario/stance dropdowns show only "全部" until a contract type is chosen.
- Selecting a scenario or stance narrows the table; "全部" restores the full set (including base rows).
- DOCX/PDF `<a>` links trigger an immediate file download (browser-native, no JS).
- Pagination links carry all current filter params forward; no JS required.
- Service-layer tests cover: distinct sets per type, each filter combination, LIMIT/OFFSET boundary (first page, last page, past-end offset).
- No existing test regresses (additive change).

"""Project-wide configuration: paths and environment-variable contracts.

Single source of truth for the paths the rest of ``src/`` derives ad hoc:
the repo root, the evaluation-rules SQLite DB, the contract templates dir,
and the harbor extraction script. Also defines the required-env-var lists
used by the drafting crew and the evaluation judge, and the ``ConfigError``
raised when a required env var is missing.

Named ``settings.py`` (not ``config.py``) because ``src/config/`` already
exists as the CrewAI YAML data directory - a ``config.py`` file beside a
``config/`` package would be import-ambiguous.
"""

from __future__ import annotations

from pathlib import Path

# src/settings.py -> repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent

# SQLite DB shared by the evaluation engine and the web layer.
DEFAULT_DB = REPO_ROOT / "db" / "evaluation_rules.db"

# Seed contract templates loaded into the drafter's context.
TEMPLATES_DIR = REPO_ROOT / "templates"

# Harbor extraction script (single source of truth for the rubric schema).
EXTRACT_SCRIPT = REPO_ROOT / "scripts" / "extract_harbor_rules.py"

# LLM contract-template regeneration script (mode G): rewrites the global
# ``src/contracts/data/contracts.json`` 母版 bodies via the DRAFTER LLM.
GENERATE_TEMPLATES_SCRIPT = REPO_ROOT / "scripts" / "generate_contract_templates_llm.py"


class ConfigError(Exception):
    """A required environment variable is missing or misconfigured."""


# --------------------------------------------------------------------------- #
# Search / RAG service config (read from env; used by src/search/*)
# --------------------------------------------------------------------------- #

import os as _os
from urllib.parse import urlparse as _urlparse

from dotenv import load_dotenv as _load_dotenv

_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return _os.environ.get(key, default)


# PostgreSQL DSN (single source of truth for the relational layer).
DATABASE_URL = _env("database_url") or _env("DATABASE_URL")

# Embeddings via OpenRouter (OpenAI-compatible /embeddings endpoint).
OPENROUTER_API_BASE = _env("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY", "")
EMBEDDING_MODEL = _env("EMBEDDING_MODEL", "nvidia/nemotron-3-embed-1b:free")
EMBEDDING_DIMS = int(_env("EMBEDDING_DIMS", "2048"))

# Elasticsearch vector store.
ES_URL = _env("elastic_search_host", "")
ES_USER = _env("elastic_search_user", "elastic")
ES_PASSWORD = _env("elastic_search_pass", "")
SEARCH_INDEX_NAME = _env("SEARCH_INDEX_NAME", "contracts")

# 法规目录副本（law_catalog schema）名称解析的 trigram 相似度阈值。低于阈值
# 的模糊候选不自动命中，进人工复核队列（link-law-catalog-audit）。
# 0.65 按生产库首跑校准：≥1.0 是书名号变体（〈〉/<> vs 《》）的高价值命中；
# 0.45–0.63 区间全部是全国名→省级条例 / 实施细则→本体条例的假阳性。
LAW_TRGM_THRESHOLD = float(_env("LAW_TRGM_THRESHOLD", "0.65"))

# 法规库计量 API（law-api，APISIX key-auth + Lago 计量；integrate-law-semantic-search）。
# law-bench 保持"无向量"：模型/维度/Qdrant 全部在网关后面，这里只配端点与 key。
# key 为空或 LAW_SEARCH_ENABLED=false 时法规检索整体不启用、零请求。
LAW_API_BASE_URL = _env("LAW_API_BASE_URL", "https://law-api.finddatatech.cloud/v1")
LAW_API_KEY = _env("LAW_API_KEY", "")
LAW_SEARCH_ENABLED = _env("LAW_SEARCH_ENABLED", "").lower() in ("1", "true", "yes", "on")
# 相邻两次 law-api 请求的最小间隔（秒）：网关 10 r/s 限流，批量解析主动礼让。
LAW_API_MIN_INTERVAL = float(_env("LAW_API_MIN_INTERVAL", "0.12"))

# MinIO document source (S3-compatible). minio_host is a full URL; the reader
# wants host:port + a secure flag.
def _validated_minio_url(name: str, value: str) -> str:
    """Reject a non-empty MinIO endpoint that is not a full http(s) URL.

    urlparse("host.example.com") — no scheme — yields an EMPTY netloc, so an
    unvalidated value silently produced MINIO_ENDPOINT="" and every artifact
    upload/download failed per-request with RuntimeError instead of failing at
    boot (the 2026-08 file.token118.com incident). Empty passes through: an
    unset/empty minio_host falls back to the localhost default, and an empty
    MINIO_PUBLIC_HOST means "no public override".
    """
    if not value:
        return value
    parsed = _urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError(
            f"{name} must be a full URL with an http:// or https:// scheme "
            f"(e.g. https://file.example.com), got: {value!r}"
        )
    return value


_minio_host_full = _validated_minio_url(
    "minio_host", _env("minio_host", "") or "http://localhost:9000"
)
MINIO_SECURE = _minio_host_full.startswith("https")
MINIO_ENDPOINT = _urlparse(_minio_host_full).netloc  # host:port
MINIO_ACCESS_KEY = _env("minio_root_user", "")
MINIO_SECRET_KEY = _env("minio_root_password", "")
MINIO_BUCKET = _env("MINIO_BUCKET", "scraw-law-contracts")
MINIO_TEMPLATES_PREFIX = _env("MINIO_TEMPLATES_PREFIX", "templates/")
MINIO_DRAFTS_PREFIX = _env("MINIO_DRAFTS_PREFIX", "drafts/")
# Generated contract docx/pdf (artifacts) are stored under this prefix.
MINIO_ARTIFACTS_PREFIX = _env("MINIO_ARTIFACTS_PREFIX", "artifacts/")
# Slotted variant ({{slot}} tokens, fillable) stored under this prefix.
MINIO_ARTIFACTS_SLOTTED_PREFIX = _env("MINIO_ARTIFACTS_SLOTTED_PREFIX", "artifacts-slotted/")

# Public-pod MinIO override (task 5.2). When set (a full URL, e.g.
# ``http://china-minio:9000``), the artifact read/download path
# (``src/contracts/artifacts.py`` ``_client()``) streams from the China-local
# MinIO mirror instead of the origin, so ``GET /api/contracts/artifacts/{id}/download``
# and the ``/samples`` browse page serve China-local bytes with no per-request
# border crossing. Credentials come from the shared ``minio_root_user`` /
# ``minio_root_password`` env (on the public pod those are the China MinIO's
# creds), so only the endpoint host is overridden. When unset (origin), the
# public-host vars fall back to the origin ``MINIO_*`` values below so origin
# behavior is byte-for-byte unchanged.
_public_minio_host = _validated_minio_url("MINIO_PUBLIC_HOST", _env("MINIO_PUBLIC_HOST", ""))
MINIO_PUBLIC_ENDPOINT = (
    _urlparse(_public_minio_host).netloc if _public_minio_host else MINIO_ENDPOINT
)
MINIO_PUBLIC_SECURE = (
    _public_minio_host.startswith("https") if _public_minio_host else MINIO_SECURE
)

# CrewAI RAG retrieval tool toggle (on by default; degrades gracefully if off).
RAG_TOOL_ENABLED = _env("RAG_TOOL_ENABLED", "1") == "1"


# --------------------------------------------------------------------------- #
# Auth config (Phase 2 — Logto hybrid Cookie + APIKey)
# --------------------------------------------------------------------------- #
# Identity is fully delegated to a self-deployed Logto instance (OIDC). This
# project stores NO passwords and has NO local users table. Browser sessions
# use the OIDC authorization-code flow -> signed httpOnly cookie; programmatic
# callers use either a Logto-issued Bearer JWT (JWKS-validated) or a
# self-managed X-API-Key (salted hash in the ``api_keys`` table).

# Logto OIDC endpoint (base URL, e.g. https://logto.example.com). Trailing
# slash stripped so ``LOGTO_ENDPOINT + "/oidc/..."`` composes cleanly.
LOGTO_ENDPOINT = _env("LOGTO_ENDPOINT", "").rstrip("/")
LOGTO_CLIENT_ID = _env("LOGTO_CLIENT_ID", "")
LOGTO_CLIENT_SECRET = _env("LOGTO_CLIENT_SECRET", "")
# Absolute public URL the IdP redirects to after authorize (-> /auth/callback).
LOGTO_REDIRECT_URI = _env("LOGTO_REDIRECT_URI", "")
# Public base URL of this app (e.g. https://lawbench.example.com). Used only as
# the OIDC post-logout redirect target so the IdP can send the browser back here
# after ending its session. When empty, logout clears the cookie locally and
# redirects to "/" without calling the IdP end-session endpoint.
APP_BASE_URL = _env("APP_BASE_URL", "").rstrip("/")
# OIDC + API scopes requested at the authorize step. The API Resource permission
# scopes (``content:read``/``content:write``/``admin``) are required for RBAC —
# Logto returns only the subset the user's roles grant, and that intersection is
# the access token's ``scope`` claim the app authorizes on. Without requesting
# them, every token carries only identity scopes and the admission gate denies
# everyone in ``enforce`` mode.
LOGTO_SCOPES = _env(
    "LOGTO_SCOPES", "openid profile email content:read content:write admin"
).split()

# The Logto API Resource this app requests (the authorize ``resource=`` param and
# the audience the access token is minted for). Roles in Logto bundle this
# resource's permission scopes; the access token's ``scope`` claim is the app's
# authorization truth. When empty, no resource is requested and access-token
# audience falls back to the client_id (single-resource self-deploy only).
LOGTO_API_RESOURCE = _env("LOGTO_API_RESOURCE", "")

# Session cookie signing secret. MUST be a stable deploy secret — never
# auto-generated per restart; rotating it invalidates every live session and
# there is no key-rotation path here, so treat it as a permanent deploy secret.
AUTH_SESSION_SECRET = _env("AUTH_SESSION_SECRET", "")
# Session cookie lifetime in seconds (default: 7 days).
AUTH_SESSION_TTL = int(_env("AUTH_SESSION_TTL", str(7 * 24 * 3600)))
# Cookie attributes. AUTH_COOKIE_SECURE=0 allows http on localhost for dev;
# leave 1 in prod (Secure requires https). httpOnly + SameSite=Lax are fixed.
AUTH_COOKIE_NAME = _env("AUTH_COOKIE_NAME", "lawbench_session")
AUTH_COOKIE_SECURE = _env("AUTH_COOKIE_SECURE", "1") == "1"

# --- Admin assistant (CopilotKit runtime) ---------------------------------- #
# Base URL of the CopilotKit runtime the /copilotkit proxy forwards to
# (add-admin-copilot-assistant). In-cluster default target is
# http://copilot-runtime.law-bench.svc.cluster.local:3111. Unset = the
# assistant is disabled: the proxy answers 503 and the island is not served,
# instead of guessing a default that only resolves inside the cluster.
COPILOT_RUNTIME_URL = _env("COPILOT_RUNTIME_URL", "").rstrip("/")


# --- RBAC: permission scopes and login admission --------------------------- #
# Authorization is expressed as *scopes*, taken directly from the Logto access
# token's ``scope`` claim for the configured API Resource. There is no app-side
# role->scope table — Logto roles are permission bundles, so the Logto console is
# the single source of truth. These env vars configure who may sign in and the
# rollout mode. Read live (mirroring the DSN read in
# ``check_public_auth_config``) so tests and a rolling deploy can change them
# without an import-time rebind.


def admitted_scope_set() -> frozenset[str]:
    """Scopes that qualify an identity to hold a workbench session.

    A token whose ``scope`` claim intersects this set is admitted at
    ``/auth/callback``; otherwise it is denied (fail closed). Comma-separated
    env, defaulting to the full API Resource permission set.
    """
    raw = _env(
        "AUTH_ADMITTED_SCOPES",
        "content:read,content:write,admin",
    )
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def admission_mode() -> str:
    """``enforce`` (default) applies the admission gate; ``warn`` logs + admits.

    Anything other than ``warn`` is coerced to ``enforce`` — a typo must fail
    closed, never silently disable the gate.
    """
    mode = _env("AUTH_ADMISSION_MODE", "enforce").strip().lower()
    return "warn" if mode == "warn" else "enforce"

# Env vars that MUST be populated before the app serves any traffic. Checked
# fail-fast at startup in create_app() — a missing value means the process
# refuses to boot (fail closed: never run an open server). JWKS reachability
# is validated separately in the auth package (also fail-closed).
AUTH_REQUIRED_VARS = [
    "LOGTO_ENDPOINT",
    "LOGTO_CLIENT_ID",
    "LOGTO_CLIENT_SECRET",
    "LOGTO_REDIRECT_URI",
    "AUTH_SESSION_SECRET",
]


def check_auth_config() -> None:
    """Raise :class:`ConfigError` if any required auth env var is unset.

    Called from ``create_app()`` at startup so the process fails closed — no
    auth config, no server. Only checks *presence* of the values; reachability
    of the Logto endpoint / JWKS is validated in :mod:`src.web.auth.logto`.
    """
    missing = [name for name in AUTH_REQUIRED_VARS if not _env(name)]
    if missing:
        raise ConfigError(
            "Auth is not configured — refusing to start. "
            "Set these env vars: " + ", ".join(missing)
        )


# Env vars required by the public pod (China-facing read-only API). The public
# pod has NO Logto dependency — it resolves identity via X-API-Key against the
# replicated ``api_keys`` table and runs no browser OIDC flow — so the
# ``LOGTO_*`` vars are not required. ``AUTH_SESSION_SECRET`` is still required
# so the dormant cookie-signing path (reused by ``get_current_user``) does not
# fail open, and ``DATABASE_URL`` is required so the local replica can be
# reached. JWKS reachability is intentionally NOT checked: the China box cannot
# reliably reach ``auth.finddatatech.cloud`` across the border, and requiring that
# fetch at boot would CrashLoopBackOff the pod (the fragility the DNS block was
# added to avoid in the first place).
PUBLIC_AUTH_REQUIRED_VARS = [
    "AUTH_SESSION_SECRET",
]


def check_public_auth_config() -> None:
    """Raise :class:`ConfigError` if the public pod's required auth env is unset.

    Mirrors :func:`check_auth_config` but for the Logto-independent public pod:
    only ``AUTH_SESSION_SECRET`` is required (so the shared cookie-signing path
    does not fail open) plus a non-empty ``DATABASE_URL`` (the replica DSN).
    Does NOT call ``logto.verify_reachable()`` — the China box cannot reliably
    reach Logto's JWKS across the border. Preserves the origin's fail-closed
    posture: the public pod never runs as an open server even if its env is
    misconfigured.
    """
    missing = [name for name in PUBLIC_AUTH_REQUIRED_VARS if not _env(name)]
    if missing:
        raise ConfigError(
            "Public pod auth is not configured — refusing to start. "
            "Set these env vars: " + ", ".join(missing)
        )
    # Read the DSN live from env (not the module-level ``DATABASE_URL`` constant,
    # which is bound at import time and would be stale when a test fixture sets
    # ``database_url`` after import). Mirrors ``check_auth_config``'s live-read
    # pattern so the fail-closed check works in both prod and tests.
    if not (_env("database_url") or _env("DATABASE_URL")):
        raise ConfigError(
            "Public pod auth is not configured — refusing to start. "
            "Set the database_url env var (replica DSN)."
        )


# Read-only replica flag (env-driven, default "0"). Set to "1" on the China
# public pod so the best-effort ``last_used_at`` touch in ``verify_key`` is
# skipped entirely — the replica is read-only, so a per-request UPDATE would
# only log error noise against the standby. When unset/"0" (origin), the
# original best-effort write behavior is preserved. Bound at import time; tests
# that need to flip it monkeypatch ``src.web.auth.apikey.READONLY_REPLICA``
# directly.
READONLY_REPLICA = _env("READONLY_REPLICA", "0") == "1"


# Rate limiting (in-process token-bucket; the abuse half of "防止恶意调用").
# Env-gated so the middleware is active on the public pod (``RATE_LIMIT_ENABLED=1``)
# and dormant on the origin (default "0" -> the middleware is not registered at
# all, so origin behavior is byte-for-byte unchanged). A gateway-level limiter
# (Caddy ``rate_limit`` / Nginx ``limit_req``) in front of the pod is the
# preferred production posture; this in-process limiter is the fallback for the
# no-gateway case so an abusive caller is never unthrottled. Keyed per API-key
# prefix (or client IP for anonymous callers). Bound at import time; the
# middleware reads these module globals at registration/construction so tests
# flip them by monkeypatching ``src.web.rate_limit`` directly.
RATE_LIMIT_ENABLED = _env("RATE_LIMIT_ENABLED", "0") == "1"
RATE_LIMIT_RPS = float(_env("RATE_LIMIT_RPS", "10"))    # sustained tokens/sec refill
RATE_LIMIT_BURST = int(_env("RATE_LIMIT_BURST", "20"))  # bucket capacity (max burst)

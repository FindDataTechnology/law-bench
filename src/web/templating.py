"""Jinja2 templates singleton + per-request locale context processor.

Extracted from ``src/web/app.py`` so the HTML route modules can import the
``templates`` renderer without triggering a circular import (routes are now
included at ``app.py`` top level rather than lazily inside ``create_app()``).
The context processor injects the active locale + catalog + bound translators
into every render, so individual handlers do not thread them through.
"""

from __future__ import annotations

import json

from fastapi import Request
from fastapi.templating import Jinja2Templates

from ..settings import COPILOT_RUNTIME_URL, OFFICIAL_BENCH_URL
from .i18n import (
    DEFAULT,
    LABELS,
    LOCALES,
    criterion_for,
    label_for,
    source_label,
    title_for_prompt,
    title_for_rubric,
    translate,
)
from .paths import TEMPLATES_DIR


def _has_scope(user: object, scope: str) -> bool:
    """True iff ``user`` holds ``scope`` (``*`` is a wildcard).

    ``user`` is ``None`` whenever auth was bypassed — e.g. a test that overrides
    ``get_current_user`` without also setting ``request.state.user`` — so an
    unknown identity resolves to *no* scopes and the chrome hides
    permission-gated actions instead of guessing. Usability only; ``require_scope``
    on the route remains the authoritative check.
    """
    if user is None:
        return False
    scopes = getattr(user, "scopes", None) or []
    return "*" in scopes or scope in scopes


def _my_domains(request: Request) -> list[dict]:
    """Domains where the signed-in user holds an active membership (nav).

    Backs the permission-aware 「我的域」 navigation section (web-rbac delta
    scenario 「导航按域过滤」): a user must see ONLY domains they are a member
    of — non-members and anonymous users render zero domain entries. The
    context processor has no DB conn of its own, so this resolves through
    ``get_db`` lazily: Jinja calls it only when the chrome renders the section
    for a signed-in user, the result is cached on ``request.state`` per request,
    and ``get_db`` rides the process-wide cached connection (no per-request TCP
    churn). Fail-safe by contract: ANY failure (DB unavailable, no identity,
    import trouble) renders no domains rather than 500-ing the chrome — this is
    navigation sugar, never an enforcement point (``require_domain_role`` on the
    admin routes stays authoritative).
    """
    try:
        user = getattr(request.state, "user", None)
        sub = getattr(user, "sub", "") or ""
        if not sub:
            return []
        cached = getattr(request.state, "my_domains", None)
        if cached is not None:
            return cached
        from ..bench import workspaces  # local import: avoid import cycles
        from .deps import get_db  # local import: avoid import cycles

        domains = workspaces.list_domains(get_db(), user_id=sub)
        request.state.my_domains = domains
        return domains
    except Exception:  # noqa: BLE001 - the nav must never take the page down
        return []


def _locale_context(request: Request) -> dict:
    """Per-request Jinja context: active locale + catalog + a bound translator.

    ``request.state.lang``/``request.state.t`` are set by the locale middleware
    in ``app.create_app()``; this processor just exposes them (and a ``tr``
    helper for flash key lookup with interpolation) to every template render.
    """
    lang = getattr(request.state, "lang", DEFAULT)
    # The resolved identity (set by ``get_current_user``); ``None`` on exempt or
    # auth-bypassed renders. Drives the topbar login/logout affordance + scopes.
    user = getattr(request.state, "user", None)
    t = getattr(request.state, "t", None) or LOCALES[DEFAULT]
    labels = LABELS.get(lang) or LABELS[DEFAULT]
    return {
        "lang": lang,
        "t": t,
        # Pre-serialized for the window.__LOCALE__ bootstrap in base.html,
        # so we don't depend on a tojson filter being registered.
        "t_json": json.dumps(t, ensure_ascii=False),
        "tr": lambda key, **fmt: translate(t, key, **fmt),
        # Data-label localization (see spec `data-label-i18n`): the active
        # locale's label catalog + resolvers bound to this locale, so every
        # template can call label_for/title_for_* without threading lang through.
        # labels_json bootstraps window.__LABELS__ for app.js (matrix meta, etc.).
        "labels": labels,
        "labels_json": json.dumps(labels, ensure_ascii=False),
        "label_for": lambda kind, value: label_for(kind, value, lang),
        "title_for_prompt": lambda name: title_for_prompt(name, lang),
        "title_for_rubric": lambda name: title_for_rubric(name, lang),
        "source_label": lambda source: source_label(source, lang),
        "criterion_for": lambda name, field, fallback="": criterion_for(name, field, lang, fallback),
        # Auth identity (change `add-web-rbac-and-login-ui`): who's signed in,
        # plus a scope predicate the chrome uses to show/hide permission-gated actions.
        "user": user,
        "has_scope": lambda scope: _has_scope(user, scope),
        # My domains (change `add-ontology-template-and-workspaces`): a lazy
        # resolver so the 「我的域」 nav section only queries the DB when a
        # signed-in chrome actually renders it; returns [] on any failure.
        "my_domains": lambda: _my_domains(request),
        # The marketing site's bench page: the chrome's one "what is this?"
        # link (and the denied-login page's way back out). External, so the
        # template renders it with target=_blank/rel=noopener.
        "official_bench_url": OFFICIAL_BENCH_URL,
        # Admin assistant (change `add-admin-copilot-assistant`): the island is
        # served only to admin sessions AND only when a runtime is configured;
        # unset COPILOT_RUNTIME_URL means the assistant is disabled outright.
        "assistant_enabled": bool(COPILOT_RUNTIME_URL) and _has_scope(user, "admin"),
    }


# Jinja2 templates (lazily loaded at render time; dir created by create_app()).
templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
    context_processors=[_locale_context],
)

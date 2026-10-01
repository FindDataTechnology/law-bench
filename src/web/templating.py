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

from ..settings import COPILOT_RUNTIME_URL
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

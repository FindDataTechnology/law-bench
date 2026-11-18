"""Filesystem paths for the web layer (templates, static assets).

Centralized so ``app.py`` (mounts / mkdir) and ``templating.py`` (Jinja2
directory) resolve the same locations without each re-deriving them from
``__file__``. Keeping paths out of ``app.py`` also lets the HTML route modules
import the Jinja2 renderer (``templating.templates``) without pulling in the
FastAPI app object — which would otherwise be a circular import now that the
routers are included at module load rather than lazily inside ``create_app()``.
"""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = _HERE / "templates"
STATIC_DIR = _HERE / "static"

"""Server-side markdown rendering for the law_info web pages.

Uses ``markdown-it-py`` (already a transitive dependency via ``rich``; promoted
to a direct dependency because the law_info pages render bundled markdown to
HTML). The content is first-party bundled (not user input at runtime), so
default renderer options are acceptable. On any rendering error the raw text is
returned HTML-escaped so the page still renders.
"""

from __future__ import annotations

from markupsafe import Markup, escape

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"html": False}).enable("table")


def render_markdown(text: str | None) -> Markup:
    """Render ``text`` (markdown) to a safe HTML ``Markup``.

    Returns an empty ``Markup`` for ``None``/empty input. If the renderer
    raises, the raw text is returned HTML-escaped (safe), never re-rendered.
    """
    if not text:
        return Markup("")
    try:
        return Markup(_md.render(text))
    except Exception:
        return escape(text)

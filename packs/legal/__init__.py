"""Legal pack: the domain half of the kernel's extension points.

Importing anything under ``packs.legal`` runs this module first, so this is the
one place that registers what the *domain* contributes to the kernel:

- entity-key fold rules (``entity_keys``) — which spellings of a name are the
  same document, and which suffixes mark a different one;
- asset kinds (``asset_catalog``) — kept as an explicit import in the web layer
  because it registers only when a deployment actually shelves those assets.

Registering the key rules here rather than at the call site means extraction,
hand-written imports and any future reader all fold names the same way, and a
deployment that never imports the pack simply folds nothing (the safe default).
"""

from packs.legal import entity_keys  # noqa: F401  (registration side effect)

__all__ = ["entity_keys"]

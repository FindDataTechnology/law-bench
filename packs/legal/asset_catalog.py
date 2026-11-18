"""Legal pack asset catalog: which corpus assets this vertical can shelve.

The kernel (``src/bench/domain_assets``) owns the generic directory mechanics
(assign / unassign / list / orphan purge) and is domain-free by construction.
This module is the legal pack's half of that contract: the six asset kinds this
corpus exposes, how each one is keyed, and the i18n key naming it in the console.

Importing this module registers the providers with the kernel, so importing the
pack is all a deployment has to do:

============  =========================  ===================================
kind          asset table                key (display name)
============  =========================  ===================================
``rubric``    ``rubrics``                ``name`` (names are not unique in
                                         the table, so the relation is
                                         DISTINCT — the directory keys the
                                         rubric *name*, the identifier every
                                         ``eval_runs.rubric_name`` uses)
``prompt``    ``prompts``                ``name`` (UNIQUE)
``compare``   ``compare_runs``           ``id::text`` (``label`` is nullable
                                         and not unique, so only the id is a
                                         stable key; it is shown in the name)
``sample``    ``contract_artifacts``     ``body_hash`` (UNIQUE, content-
                                         addressed; the ``/samples`` corpus)
``clause``    ``clauses``                ``id::text`` (no slug exists; the
                                         upsert identity is
                                         source_path/section/body_hash and
                                         the row id survives it)
``law_info``  ``law_info``               ``contract_type`` (one directory
                                         entry stands for that type's
                                         law-info set across sources)
============  =========================  ===================================

Each relation projects exactly one row per key with two columns —
``asset_key`` and ``name`` — so the kernel can LEFT JOIN (``exists``) or
anti-join (the unassigned pool) without ever reading asset content or mutating
an asset.
"""

from __future__ import annotations

from src.bench.domain_assets import register_providers

#: One provider per kind, in the console's listing order. ``relation`` is a
#: self-contained SELECT of (asset_key, name); ``label_key`` names the kind in
#: the i18n catalog.
PROVIDERS: dict[str, dict] = {
    "rubric": {
        "relation": "SELECT DISTINCT name AS asset_key, name AS name FROM rubrics",
        "label_key": "bench_catalog.kind.rubric",
    },
    "prompt": {
        "relation": "SELECT name AS asset_key, name AS name FROM prompts",
        "label_key": "bench_catalog.kind.prompt",
    },
    "compare": {
        "relation": (
            "SELECT id::text AS asset_key, "
            "COALESCE(NULLIF(label, ''), 'compare #' || id::text) AS name "
            "FROM compare_runs"
        ),
        "label_key": "bench_catalog.kind.compare",
    },
    "sample": {
        "relation": (
            "SELECT body_hash AS asset_key, "
            "concat_ws(' · ', contract_type, scenario, stance) AS name "
            "FROM contract_artifacts"
        ),
        "label_key": "bench_catalog.kind.sample",
    },
    "clause": {
        "relation": (
            "SELECT id::text AS asset_key, "
            "concat_ws(' · ', contract_type, section) AS name FROM clauses"
        ),
        "label_key": "bench_catalog.kind.clause",
    },
    "law_info": {
        "relation": (
            "SELECT DISTINCT contract_type AS asset_key, contract_type AS name "
            "FROM law_info"
        ),
        "label_key": "bench_catalog.kind.law_info",
    },
}

register_providers(PROVIDERS)

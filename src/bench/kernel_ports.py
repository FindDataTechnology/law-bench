"""psycopg adapters for the six ontology-kernel ports.

The kernel owns the mechanisms (vocabulary gate, write-boundary folding, the
single write path with its paired event, manifests, proposals, the ledger). This
module is the *only* place that knows those mechanisms live in PostgreSQL tables
called ``knowledge_units`` / ``authoring_events`` / ``domain_proposals`` /
``ontology_publications``.

Transaction discipline: the kernel calls ``upsert`` then ``append`` once. Both
ports must be given a connection already inside a transaction — ``authoring``
opens ``conn.transaction()`` around the call, which is why every method here takes
the borrowed connection and never commits.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Optional, Sequence

from fd_ontology_kernel.contracts import (
    Consumer,
    Event,
    Proposal,
    Publication,
    PullEvent,
    Unit,
)
from fd_ontology_kernel.kernel import AdapterDeclaration, Kernel
from fd_ontology_kernel.vocab import Vocabulary

from . import store, templates, workspaces

#: This surface's declaration: kernel contract 1.0, key-addressed manifests.
DECLARATION = AdapterDeclaration(
    system="law-bench-internal",
    kernel_contract="1.0",
    manifest_shape=2,
)

EVENT_COLS = (
    "id, domain_id, unit_kind, unit_key, op, before, after, operator, via, created_at"
)


def _json(value: Any) -> Any:
    """JSONB columns come back as dicts from psycopg, but tolerate strings."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _field(row: Any, name: str, index: int) -> Any:
    """Read a column by name when the connection uses ``dict_row``, else by index.

    Tests and the web app open psycopg with ``row_factory=dict_row``; the CLI
    paths do not. Reading positionally crashes on one of them, so every access
    goes through here.
    """
    if isinstance(row, Mapping):
        return row.get(name)
    return row[index]


def unit_from_row(row: Mapping[str, Any]) -> Unit:
    """Stored row → kernel unit. ``namespace`` is the domain key (the scope).

    ``raw`` carries the row itself: this surface's event payload is the full row
    (id, namespace, timestamps), and a published contract must keep its shape.
    """
    return Unit(
        scope_id=row["namespace"],
        kind=row["kind"],
        external_key=row["external_key"],
        body=row.get("body") or "",
        tier=row.get("tier") or "raw",
        tags=_json(row.get("tags")) or {},
        attrs=_json(row.get("attrs")) or {},
        source_path=row.get("source_path"),
        provenance=_json(row.get("provenance")) or {},
        raw=dict(row),
    )


class ScopedDomains:
    """``scope_id``（即域键）→ 域行，按调用解析并缓存。

    内核每次调用都带 ``scope_id``；这一面的作用域**就是**域键。按调用解析而不是
    在构造期钉死一个域，是「一个连接服务多个域」的前提——这既是生产的真实形态，
    也是符合性套件要求的形态（一个沙箱要服务多个作用域）。

    ``seed`` 让已有调用方（``kernel_for(conn, domain=...)``）零变化：该域直接进缓存，
    首次调用不多一次查询。
    """

    def __init__(self, conn: Any, *, seed: Optional[Mapping[str, Any]] = None) -> None:
        self.conn = conn
        self._cache: dict[str, dict] = {}
        if seed is not None and seed.get("key"):
            self._cache[str(seed["key"])] = dict(seed)

    def get(self, scope_id: str) -> dict:
        key = str(scope_id)
        domain = self._cache.get(key)
        if domain is None:
            domain = workspaces.get_domain(self.conn, domain_key=key)
            if domain is None:
                raise ValueError(f"unknown scope（域键）{key!r}")
            self._cache[key] = domain
        return domain

    def domain_id(self, scope_id: str) -> int:
        return int(self.get(scope_id)["id"])

    def maybe_domain_id(self, scope_id: str) -> Optional[int]:
        """``domain_id`` 的**读路径**版本：未知作用域返回 ``None`` 而不是报错。

        写路径（``domain_id``）必须报错——拼错的域键不能静默造数据。读路径不同：
        「这个作用域没有事件」是实话，不是错误。符合性套件会先读一个还没写入过的
        作用域（``fold``/``list_live``），读路径报错会让「空」和「坏」混为一谈。
        """
        try:
            return self.domain_id(scope_id)
        except ValueError:
            return None

    def key_for_id(self, domain_id: int) -> str:
        """``domain_id`` → 域键（只按 id 决策的调用点用，如 merge/decide）。

        缓存里已有该 id 的域就直接用；否则按 id 查一次并记住。
        """
        for key, domain in self._cache.items():
            if int(domain["id"]) == int(domain_id):
                return key
        domain = workspaces.get_domain(self.conn, domain_id=int(domain_id))
        if domain is None:
            raise ValueError(f"unknown domain id {domain_id!r}")
        return str(self.remember(domain)["key"])

    def remember(self, domain: Mapping[str, Any]) -> dict:
        """把刚造的域放进缓存（沙箱按需造域用）。"""
        row = dict(domain)
        self._cache[str(row["key"])] = row
        return row


class PgUnitStore:
    """``UnitStore`` over ``knowledge_units``."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def get(self, *, scope_id: str, kind: str, external_key: str) -> Optional[Unit]:
        row = store.get_knowledge_unit(
            self.conn, kind=kind, external_key=external_key, namespace=scope_id
        )
        return unit_from_row(row) if row else None

    def upsert(self, unit: Unit) -> Unit:
        row = store.upsert_knowledge_unit(
            self.conn,
            kind=unit.kind,
            external_key=unit.external_key,
            body=unit.body,
            namespace=unit.scope_id,
            tags=dict(unit.tags or {}),
            attrs=dict(unit.attrs or {}),
            tier=unit.tier,
            source_path=unit.source_path,
            provenance=dict(unit.provenance or {}),
            commit=False,
        )
        return unit_from_row(row)

    def list_live(self, *, scope_id: str) -> list[Unit]:
        rows = store.list_knowledge_units(
            self.conn,
            namespace=scope_id,
            include_deleted=False,
            limit=store.MAX_LIST_UNITS,
        )
        return [unit_from_row(row) for row in rows]

    def live_key_kinds(self, *, scope_id: str) -> dict[str, str]:
        return {unit.external_key: unit.kind for unit in self.list_live(scope_id=scope_id)}

    def raw_count(self) -> int:
        """``knowledge_units`` 行数（跨作用域）。

        符合性套件用它做「打开账本前后不变」的判据——账本必须是纯投影，读它不能
        写库。跨作用域是故意的：一次投影若顺手回写了别的域，账本自检才算得出来。
        """
        row = self.conn.execute(
            "SELECT count(*) AS n FROM knowledge_units"
        ).fetchone()
        return int(_field(row, "n", 0) or 0) if row else 0


class PgEventJournal:
    """``EventJournal`` over ``authoring_events``.

    The table has no sequence column; ``seq`` stays ``None`` and the fold orders
    by ``(created_at, id)``, which is stable because ids are monotonic per insert.
    Fleet lineage columns do not exist here either, so ``source_ref`` is not
    persisted — this surface never had that lineage.
    """

    def __init__(self, conn: Any, *, scopes: "ScopedDomains") -> None:
        self.conn = conn
        self.scopes = scopes

    def append(self, event: Event) -> Event:
        """Append through the surface's existing ``_record_event``.

        Delegating here (rather than inserting inline) keeps one event writer for
        this surface: the atomicity tests and any operator tooling that wraps
        ``_record_event`` still see — and can still break — the real write.
        ``_record_event`` does not commit; the caller's transaction owns that.
        """
        from dataclasses import replace

        from . import authoring  # late: authoring imports this module

        row = authoring._record_event(
            self.conn,
            domain_id=self.scopes.domain_id(event.scope_id),
            unit_kind=event.target_kind,
            unit_key=event.target_key,
            op=event.op,
            before=dict(event.before) if event.before is not None else None,
            after=dict(event.after) if event.after is not None else None,
            operator=event.actor,
            via=event.via,
        )
        return replace(event, target_ref=row["id"], occurred_at=row["created_at"])

    def fold(self, *, scope_id: str) -> list[Event]:
        domain_id = self.scopes.maybe_domain_id(scope_id)
        if domain_id is None:
            return []
        rows = self.conn.execute(
            f"SELECT {EVENT_COLS} FROM authoring_events "
            "WHERE domain_id = %s ORDER BY created_at, id",
            (domain_id,),
        ).fetchall()
        return [self._event_from_row(row, scope_id=scope_id) for row in rows]

    def count_since(
        self,
        *,
        scope_id: str,
        seq: Optional[int] = None,
        since: Optional[str] = None,
    ) -> int:
        domain_id = self.scopes.maybe_domain_id(scope_id)
        if domain_id is None:
            return 0
        if since:
            row = self.conn.execute(
                "SELECT count(*) AS n FROM authoring_events "
                "WHERE domain_id = %s AND created_at > %s",
                (domain_id, since),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT count(*) AS n FROM authoring_events WHERE domain_id = %s",
                (domain_id,),
            ).fetchone()
        return int(_field(row, "n", 0) or 0) if row else 0

    def _event_from_row(self, row: Sequence[Any], *, scope_id: str) -> Event:
        return Event(
            scope_id=scope_id,
            op=_field(row, "op", 3),
            target_kind=_field(row, "unit_kind", 2),
            target_key=_field(row, "unit_key", 4),
            actor=_field(row, "operator", 7),
            via=_field(row, "via", 8),
            before=_json(_field(row, "before", 5)),
            after=_json(_field(row, "after", 6)),
            target_ref=_field(row, "id", 0),
            occurred_at=_iso(_field(row, "created_at", 9)),
        )


PROPOSAL_COLS = (
    "id, source, kind, external_key, body, evidence, evidence_digest, impact, "
    "state, submitted_by, decided_by, decision_note, sources"
)


class PgProposalBox:
    """``ProposalBox`` over ``domain_proposals`` (claim identity includes evidence)."""

    def __init__(self, conn: Any, *, scopes: "ScopedDomains") -> None:
        self.conn = conn
        self.scopes = scopes

    def find_claim(
        self, *, scope_id: str, external_key: str, evidence_digest: str
    ) -> Optional[Proposal]:
        row = self.conn.execute(
            f"SELECT {PROPOSAL_COLS} FROM domain_proposals "
            "WHERE domain_id = %s AND external_key = %s AND evidence_digest = %s "
            "AND state = 'pending' LIMIT 1",
            (self.scopes.domain_id(scope_id), external_key, evidence_digest),
        ).fetchone()
        return self._proposal(row, scope_id=scope_id) if row else None

    def insert(self, proposal: Proposal) -> Proposal:
        row = self.conn.execute(
            "INSERT INTO domain_proposals "
            "(domain_id, source, kind, external_key, body, evidence, evidence_digest, "
            " impact, state, submitted_by, sources) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s) "
            f"RETURNING {PROPOSAL_COLS}",
            (
                self.scopes.domain_id(proposal.scope_id),
                proposal.source,
                proposal.kind,
                proposal.external_key,
                proposal.body,
                json.dumps(dict(proposal.evidence)),
                proposal.evidence_digest,
                proposal.impact,
                proposal.submitted_by,
                json.dumps(list(proposal.submitters)),
            ),
        ).fetchone()
        return self._proposal(row, scope_id=proposal.scope_id)

    def merge_submitters(
        self, *, proposal_id: int, submitters: Sequence[str]
    ) -> Proposal:
        merged = list(dict.fromkeys(str(name) for name in submitters))
        row = self.conn.execute(
            "UPDATE domain_proposals SET sources = %s WHERE id = %s "
            "RETURNING domain_id, "
            f"{PROPOSAL_COLS}",
            (json.dumps(merged), proposal_id),
        ).fetchone()
        return self._proposal_shifted(row)

    def find_by_key(
        self, *, scope_id: str, external_key: str, state: Optional[str] = None
    ) -> Optional[Proposal]:
        sql = (
            f"SELECT {PROPOSAL_COLS} FROM domain_proposals "
            "WHERE domain_id = %s AND external_key = %s"
        )
        params: list[Any] = [self.scopes.domain_id(scope_id), external_key]
        if state is not None:
            sql += " AND state = %s"
            params.append(state)
        sql += " ORDER BY id DESC LIMIT 1"
        row = self.conn.execute(sql, tuple(params)).fetchone()
        return self._proposal(row, scope_id=scope_id) if row else None

    def get(self, *, scope_id: str, proposal_id: int) -> Optional[Proposal]:
        row = self.conn.execute(
            f"SELECT {PROPOSAL_COLS} FROM domain_proposals "
            "WHERE id = %s AND domain_id = %s",
            (proposal_id, self.scopes.domain_id(scope_id)),
        ).fetchone()
        return self._proposal(row, scope_id=scope_id) if row else None

    def decide(
        self, *, proposal_id: int, state: str, decided_by: str, note: str = ""
    ) -> Proposal:
        row = self.conn.execute(
            "UPDATE domain_proposals SET state = %s, decided_by = %s, "
            "decided_at = now(), decision_note = %s WHERE id = %s "
            "RETURNING domain_id, "
            f"{PROPOSAL_COLS}",
            (state, decided_by, note, proposal_id),
        ).fetchone()
        return self._proposal_shifted(row)

    def list_pending(
        self, *, scope_id: str, batch: Optional[str] = None, limit: int = 200
    ) -> list[Proposal]:
        rows = self.conn.execute(
            f"SELECT {PROPOSAL_COLS} FROM domain_proposals "
            "WHERE domain_id = %s AND state = 'pending' "
            "ORDER BY submitted_at, id LIMIT %s",
            (self.scopes.domain_id(scope_id), max(1, int(limit))),
        ).fetchall()
        return [self._proposal(row, scope_id=scope_id) for row in rows]

    def _proposal_shifted(self, row: Sequence[Any]) -> Proposal:
        """``RETURNING domain_id, <PROPOSAL_COLS>`` → 提案（列整体右移一位）。"""
        return self._proposal(row, scope_id=self.scopes.key_for_id(_field(row, "domain_id", 0)), shift=1)

    def _proposal(
        self, row: Sequence[Any], *, scope_id: str, shift: int = 0
    ) -> Proposal:
        return Proposal(
            scope_id=scope_id,
            source=_field(row, "source", 1 + shift),
            kind=_field(row, "kind", 2 + shift),
            external_key=_field(row, "external_key", 3 + shift),
            body=_field(row, "body", 4 + shift),
            evidence=_json(_field(row, "evidence", 5 + shift)) or {},
            evidence_digest=_field(row, "evidence_digest", 6 + shift),
            impact=_field(row, "impact", 7 + shift) or "",
            state=_field(row, "state", 8 + shift),
            submitted_by=_field(row, "submitted_by", 9 + shift),
            decided_by=_field(row, "decided_by", 10 + shift),
            decision_note=_field(row, "decision_note", 11 + shift),
            sources=tuple(_json(_field(row, "sources", 12 + shift)) or []),
            proposal_id=_field(row, "id", 0 + shift),
        )


PUBLICATION_COLS = (
    "id, domain_id, version, digest, manifest, changelog, published_by, published_at"
)


class PgPublicationStore:
    """``PublicationStore`` over ``ontology_publications`` (insert-only)."""

    def __init__(self, conn: Any, *, scopes: "ScopedDomains") -> None:
        self.conn = conn
        self.scopes = scopes

    def latest(self, *, scope_id: str) -> Optional[Publication]:
        row = self.conn.execute(
            f"SELECT {PUBLICATION_COLS} FROM ontology_publications "
            "WHERE domain_id = %s ORDER BY version DESC LIMIT 1",
            (self.scopes.domain_id(scope_id),),
        ).fetchone()
        return self._publication(row, scope_id=scope_id) if row else None

    def get(
        self,
        *,
        scope_id: str,
        version: Optional[int] = None,
        digest: Optional[str] = None,
    ) -> Optional[Publication]:
        if version is not None:
            row = self.conn.execute(
                f"SELECT {PUBLICATION_COLS} FROM ontology_publications "
                "WHERE domain_id = %s AND version = %s",
                (self.scopes.domain_id(scope_id), version),
            ).fetchone()
        elif digest is not None:
            row = self.conn.execute(
                f"SELECT {PUBLICATION_COLS} FROM ontology_publications "
                "WHERE domain_id = %s AND digest = %s",
                (self.scopes.domain_id(scope_id), digest),
            ).fetchone()
        else:
            raise ValueError("get needs a version or a digest; use latest() otherwise")
        return self._publication(row, scope_id=scope_id) if row else None

    def next_version(self, *, scope_id: str) -> int:
        row = self.conn.execute(
            "SELECT coalesce(max(version), 0) + 1 AS next_version "
            "FROM ontology_publications WHERE domain_id = %s",
            (self.scopes.domain_id(scope_id),),
        ).fetchone()
        return int(_field(row, "next_version", 0) or 1) if row else 1

    def insert(self, publication: Publication) -> Publication:
        row = self.conn.execute(
            "INSERT INTO ontology_publications "
            "(domain_id, version, digest, manifest, changelog, published_by) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            f"RETURNING {PUBLICATION_COLS}",
            (
                self.scopes.domain_id(publication.scope_id),
                publication.version,
                publication.digest,
                json.dumps(dict(publication.payload), ensure_ascii=False),
                json.dumps(publication.extra.get("changelog") or {}, ensure_ascii=False),
                publication.created_by,
            ),
        ).fetchone()
        return self._publication(row, scope_id=publication.scope_id)

    def count(self) -> int:
        """``ontology_publications`` 行数（跨作用域）。幂等发布与账本只读的判据。

        跨作用域同样是故意的：两次相同内容的发布必须只留下一行，按域过滤会让
        「另一域多铸了一个版本」逃过判据。
        """
        row = self.conn.execute(
            "SELECT count(*) AS n FROM ontology_publications"
        ).fetchone()
        return int(_field(row, "n", 0) or 0) if row else 0

    def _publication(self, row: Sequence[Any], *, scope_id: str) -> Publication:
        return Publication(
            scope_id=scope_id,
            version=int(_field(row, "version", 2)),
            digest=_field(row, "digest", 3),
            payload=_json(_field(row, "manifest", 4)) or {},
            manifest_schema_version=2,
            created_by=_field(row, "published_by", 6),
            created_at=_iso(_field(row, "published_at", 7)),
            extra={"changelog": _json(_field(row, "changelog", 5)) or {}},
        )


CONSUMER_COLS = "id, name, domains, token_hash, created_by, revoked_at"


class PgDistributionRegistry:
    """``DistributionRegistry`` over ``distribution_consumers`` / pull events."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def register(
        self, *, name: str, scopes: Sequence[str], token_hash: str, created_by: str
    ) -> Consumer:
        """登记一个消费者，委托给 ``distribution.register_consumer``。

        与 ``append`` 同一个理由：这一面只能有一个写入口。内核的 ``DistributionRegistry``
        把「登记消费者」算进端口，但真正的校验（名字非空、凭据摘要非空、名字唯一、
        域键归一）都在 ``register_consumer`` 里；在这里重写一遍就是第二条写路径。
        """
        from . import distribution as distribution_mod  # late: 避免循环导入

        row = distribution_mod.register_consumer(
            self.conn,
            name=name,
            domains=list(scopes),
            token_hash=token_hash,
            created_by=created_by,
        )
        return Consumer(
            consumer_id=int(row["id"]),
            name=row["name"],
            scopes=tuple(row.get("domains") or ()),
            token_hash=row["token_hash"],
            created_by=row["created_by"],
            revoked_at=_iso(row.get("revoked_at")),
        )

    def find_by_token_hash(self, *, token_hash: str) -> Optional[Consumer]:
        row = self.conn.execute(
            f"SELECT {CONSUMER_COLS} FROM distribution_consumers WHERE token_hash = %s",
            (token_hash,),
        ).fetchone()
        return self._consumer(row) if row else None

    def record_pull(self, *, consumer_id: int, scope_id: str, version: int) -> PullEvent:
        row = self.conn.execute(
            "INSERT INTO distribution_pull_events (consumer_id, domain_key, version) "
            "VALUES (%s, %s, %s) RETURNING happened_at",
            (consumer_id, scope_id, version),
        ).fetchone()
        return PullEvent(
            consumer_id=consumer_id,
            scope_id=scope_id,
            version=version,
            happened_at=_iso(_field(row, "happened_at", 0)) if row else None,
        )

    def pulls_since(
        self, *, consumer_id: Optional[int] = None, since: Optional[str] = None
    ) -> list[PullEvent]:
        sql = (
            "SELECT consumer_id, domain_key, version, happened_at "
            "FROM distribution_pull_events WHERE true"
        )
        params: list[Any] = []
        if consumer_id is not None:
            sql += " AND consumer_id = %s"
            params.append(consumer_id)
        if since is not None:
            sql += " AND happened_at > %s"
            params.append(since)
        sql += " ORDER BY happened_at, id"
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [
            PullEvent(
                consumer_id=_field(row, "consumer_id", 0),
                scope_id=_field(row, "domain_key", 1),
                version=_field(row, "version", 2),
                happened_at=_iso(_field(row, "happened_at", 3)),
            )
            for row in rows
        ]

    def consumers(self) -> list[Consumer]:
        rows = self.conn.execute(
            f"SELECT {CONSUMER_COLS} FROM distribution_consumers ORDER BY id"
        ).fetchall()
        return [self._consumer(row) for row in rows]

    def _consumer(self, row: Sequence[Any]) -> Consumer:
        return Consumer(
            consumer_id=_field(row, "id", 0),
            name=_field(row, "name", 1),
            scopes=tuple(_field(row, "domains", 2) or ()),
            token_hash=_field(row, "token_hash", 3),
            created_by=_field(row, "created_by", 4),
            revoked_at=_iso(_field(row, "revoked_at", 5)),
        )


class TemplateVocabulary:
    """``VocabularySource``：词表就是该域锚定的模板行（按 ``scope_id`` 取）。

    ``mint`` 只给沙箱用：符合性套件会凭空起一个作用域名，那一面还没有域。生产调用
    不传 ``mint``，未知作用域照旧报错——不静默造域，否则一个拼错的域键会变成
    「新域」而不是错误。
    """

    def __init__(
        self,
        conn: Any,
        *,
        scopes: Optional["ScopedDomains"] = None,
        domain: Optional[Mapping[str, Any]] = None,
        mint: Optional[Callable[[str], Mapping[str, Any]]] = None,
    ) -> None:
        self.conn = conn
        self.scopes = scopes or ScopedDomains(conn, seed=domain)
        self.mint = mint

    def load(self, *, scope_id: str) -> Vocabulary:
        try:
            domain = self.scopes.get(scope_id)
        except ValueError:
            if self.mint is None:
                raise
            domain = self.scopes.remember(self.mint(scope_id))
        tmpl = templates.get_template_by_id(
            self.conn, template_id=domain["template_id"]
        )
        schema = (tmpl or {}).get("schema") or {}
        entity_types = schema.get("entity_types") if isinstance(schema, dict) else None
        relationship_kinds = (
            schema.get("relationship_kinds") if isinstance(schema, dict) else None
        )
        if not isinstance(entity_types, list) or not entity_types:
            raise ValueError(
                f"domain {domain['key']!r} template has no usable entity_types"
            )
        if not isinstance(relationship_kinds, list) or not relationship_kinds:
            raise ValueError(
                f"domain {domain['key']!r} template has no usable relationship_kinds"
            )
        return Vocabulary.from_values(
            release=f"{tmpl.get('name')}@{domain.get('template_version')}",
            values={
                "entity_types": entity_types,
                "relationship_kinds": relationship_kinds,
            },
        )


def kernel_for(
    conn: Any,
    *,
    domain: Mapping[str, Any],
    mint: Optional[Callable[[str], Mapping[str, Any]]] = None,
) -> Kernel:
    """Wire a kernel to this connection, seeded with ``domain``.

    ``domain`` seeds the scope resolver so the existing call sites behave exactly
    as before (and the first call costs no extra query); the ports still resolve
    **per ``scope_id``**, which is what lets one connection serve several domains
    — the model production already uses, and the one the conformance gate needs.

    ``mint`` is for the sandbox only: it creates a template + domain for an
    unknown scope. Production leaves it unset so a bad domain key raises instead
    of quietly becoming a new domain.

    Callers must already be inside ``conn.transaction()`` (or be about to open
    one) — every port here borrows the connection and never commits.
    """
    scopes = ScopedDomains(conn, seed=domain)
    return Kernel(
        units=PgUnitStore(conn),
        events=PgEventJournal(conn, scopes=scopes),
        vocabulary=TemplateVocabulary(conn, scopes=scopes, mint=mint),
        proposals=PgProposalBox(conn, scopes=scopes),
        publications=PgPublicationStore(conn, scopes=scopes),
        distribution=PgDistributionRegistry(conn),
        relationship_kinds=_relationship_kinds(conn, domain),
        clause_kinds=("clause",),
        manifest_shape=DECLARATION.manifest_shape,
        declaration=DECLARATION,
    )


def _relationship_kinds(conn: Any, domain: Mapping[str, Any]) -> tuple[str, ...]:
    tmpl = templates.get_template_by_id(conn, template_id=domain["template_id"])
    schema = (tmpl or {}).get("schema") or {}
    kinds = schema.get("relationship_kinds") if isinstance(schema, dict) else None
    return tuple(kinds) if isinstance(kinds, list) else ()

"""Crosswalk assertions: the seam between ontologies and outside systems.

A crosswalk is **one knowledge unit**, not a table of its own. It says "this
endpoint in our ontology" relates to "that endpoint elsewhere" — another layer's
ontology key, or an external system's identifier. Modelled as a KU it inherits,
for free, everything the platform already guarantees: the proposal inbox, verbatim
evidence checking, tier guards, the append-only event trail, publication digests.
A separate table would mean reimplementing all six.

Three relation kinds, closed set, fixed direction ("our endpoint → theirs"):

    same_as   the same real-world thing under another name
    role_of   our endpoint is a role played by the target entity
              (``customer:acme --role_of--> organization:acme-corp``)
    maps_to   a value-domain mapping (an industry account onto a universal one)

Direction is fixed because a reverse row is a second copy of one fact, and two
copies drift. Reverse lookups are derived by the read face instead.

**A role is a relationship, not a type.** That is why ``role_of`` points at an
entity and the role itself never becomes an ``entity_types`` entry: the same
company is a customer in one system, a vendor in another, and a supplier in a
third, and all three must converge on one ``organization`` so a crosswalk has a
single landing spot.

This module is deliberately pure: validation is a function of the dict, so the
write path and every read face share one implementation and no test needs a
database to check the rules.
"""

from __future__ import annotations

from typing import Any, Optional

#: The relation kinds, closed. Submitting anything else is refused with the set
#: named — never silently mapped onto "something similar".
RELATIONS = ("same_as", "role_of", "maps_to")

#: Peer endpoint shapes.
PEER_KINDS = ("external_id", "ontology")

#: Required attributes per peer kind. A missing one is named in the refusal.
_PEER_REQUIRED = {
    "external_id": ("system", "id"),
    "ontology": ("layer_ref", "endpoint"),
}

#: Connectivity states, in the order an operator must clear them. Three-state
#: evidence is the ERP line's existing discipline (`erp-connector-onboarding`);
#: this module records it, it does not invent a fourth state.
CONNECTIVITY_STATES = ("catalog", "executor_tests", "live")


class CrosswalkError(ValueError):
    """A crosswalk assertion is malformed (the message names the problem)."""


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_crosswalk(attrs: dict) -> list[str]:
    """Every problem with a crosswalk's ``attrs``; empty list means valid.

    Pure: no connection, no clock. Both the write path and the read faces call
    this, so there is exactly one definition of a well-formed assertion.
    """
    problems: list[str] = []
    if not isinstance(attrs, dict):
        return ["crosswalk attrs must be a dict"]

    relation = attrs.get("relation")
    if relation not in RELATIONS:
        problems.append(
            f"relation {relation!r} is not one of {list(RELATIONS)}"
        )

    peer = attrs.get("peer")
    if not isinstance(peer, dict):
        problems.append('peer must be a dict with a "kind"')
    else:
        kind = peer.get("kind")
        if kind not in PEER_KINDS:
            problems.append(f"peer.kind {kind!r} is not one of {list(PEER_KINDS)}")
        else:
            for field in _PEER_REQUIRED[kind]:
                if _blank(peer.get(field)):
                    problems.append(f"peer ({kind}) requires {field!r}")
            if kind == "ontology":
                endpoint = peer.get("endpoint")
                if isinstance(endpoint, str) and endpoint and ":" not in endpoint:
                    problems.append(
                        f"peer.endpoint {endpoint!r} must be '<type>:<key>'"
                    )

    # confidence is optional, but when present it must be a number in [0, 1].
    # An absent value is treated as "below any threshold" by the read face —
    # fail closed — so it is not a validation error here.
    confidence = attrs.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            problems.append("confidence must be a number")
        elif not (0.0 <= float(confidence) <= 1.0):
            problems.append("confidence must be within [0, 1]")

    connectivity = attrs.get("connectivity")
    if connectivity is not None:
        problems.extend(_connectivity_problems(connectivity))

    return problems


def _connectivity_problems(connectivity: Any) -> list[str]:
    """Three-state evidence shape. Absent state is fine; a malformed one is not."""
    if not isinstance(connectivity, dict):
        return ["connectivity must be a dict of state -> {ok, evidence}"]
    problems: list[str] = []
    unknown = sorted(set(connectivity) - set(CONNECTIVITY_STATES))
    if unknown:
        problems.append(
            f"connectivity has unknown state(s) {unknown}; "
            f"expected a subset of {list(CONNECTIVITY_STATES)}"
        )
    for state, value in connectivity.items():
        if state not in CONNECTIVITY_STATES:
            continue
        if not isinstance(value, dict):
            problems.append(f"connectivity.{state} must be a dict")
            continue
        ok = value.get("ok")
        if not isinstance(ok, bool):
            problems.append(f"connectivity.{state}.ok must be a boolean")
        if ok is True and _blank(value.get("evidence")):
            # "ok without evidence" is the exact failure the three-state
            # discipline exists to prevent: a state nobody can check.
            problems.append(
                f"connectivity.{state} claims ok but carries no evidence"
            )
    return problems


def crosswalk_key(entity_type: str, entity_key: str) -> str:
    """The KU external key for our endpoint: ``<type>:<key>``.

    Semantic, not a surrogate id — a crosswalk must be portable across
    environments, and an autoincrement number is not.
    """
    if _blank(entity_type) or _blank(entity_key):
        raise CrosswalkError("crosswalk endpoint requires both type and key")
    return f"{entity_type.strip()}:{entity_key.strip()}"


def is_connectivity_complete(connectivity: Optional[dict]) -> bool:
    """All three states cleared?

    Any missing state is "not connected", never "probably fine" — the ERP line's
    rule is that two-out-of-three does not make a system reachable.
    """
    if not isinstance(connectivity, dict):
        return False
    return all(
        isinstance(connectivity.get(state), dict)
        and connectivity[state].get("ok") is True
        and not _blank(connectivity[state].get("evidence"))
        for state in CONNECTIVITY_STATES
    )


def missing_connectivity_states(connectivity: Optional[dict]) -> list[str]:
    """Which states are not yet cleared, in the order they must be cleared."""
    if not isinstance(connectivity, dict):
        return list(CONNECTIVITY_STATES)
    out = []
    for state in CONNECTIVITY_STATES:
        value = connectivity.get(state)
        if not (
            isinstance(value, dict)
            and value.get("ok") is True
            and not _blank(value.get("evidence"))
        ):
            out.append(state)
    return out


def is_confirmed(attrs: dict, *, threshold: Optional[float]) -> bool:
    """Whether a crosswalk counts as reviewed for coverage purposes.

    Absent confidence fails closed (``threshold`` or not): a mapping nobody put
    a number on has not been checked, and counting it would inflate coverage
    with the very rows still awaiting review.
    """
    confidence = attrs.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return False
    if threshold is None:
        return True
    return float(confidence) >= float(threshold)


def expired_states(
    connectivity: Optional[dict], *, max_age_days: Optional[float]
) -> list[str]:
    """States whose evidence is older than the domain's declared max age.

    An expired state counts as missing — "we checked it once, in March" is not a
    live connection. ``max_age_days is None`` means the domain declared no
    expiry, in which case nothing expires and the read face must say so rather
    than silently treating old evidence as fresh.
    """
    if max_age_days is None or not isinstance(connectivity, dict):
        return []
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    out: list[str] = []
    for state in CONNECTIVITY_STATES:
        value = connectivity.get(state)
        if not isinstance(value, dict) or value.get("ok") is not True:
            continue
        at = value.get("at")
        if not isinstance(at, str) or not at.strip():
            continue
        try:
            when = datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if (now - when).days > max_age_days:
            out.append(state)
    return out


def effective_missing_states(
    connectivity: Optional[dict], *, max_age_days: Optional[float] = None
) -> list[str]:
    """States that are missing *or* expired — the honest "what must be redone"."""
    missing = missing_connectivity_states(connectivity)
    expired = expired_states(connectivity, max_age_days=max_age_days)
    return [s for s in CONNECTIVITY_STATES if s in missing or s in expired]


def list_rows(
    conn: Any, *, namespace: str, entity_key: Optional[str] = None
) -> list[dict]:
    """Every live crosswalk in ``namespace``, shaped once for every reader.

    Two read faces serve these rows (a Logto-gated console route and the
    machine ``/api/v1/distribution`` route). A second copy of the shaping would
    drift into "the console shows one thing, the machine another" — which reads
    as a bug in whichever one you looked at second.
    """
    sql = (
        "SELECT external_key, body, attrs, tier, updated_at "
        "FROM knowledge_units WHERE namespace = %s AND kind = 'crosswalk' "
        "  AND (tags->>'deleted') IS NULL"
    )
    params: list = [namespace]
    if entity_key:
        sql += " AND external_key = %s"
        params.append(entity_key)
    sql += " ORDER BY external_key, updated_at DESC"
    out: list[dict] = []
    for row in conn.execute(sql, tuple(params)).fetchall():
        attrs = row["attrs"] or {}
        out.append({
            "key": row["external_key"],
            "body": row["body"],
            "relation": attrs.get("relation"),
            "peer": attrs.get("peer"),
            "confidence": attrs.get("confidence"),
            "connectivity": attrs.get("connectivity"),
            "missing_states": effective_missing_states(attrs.get("connectivity")),
            "confirmed": is_confirmed(attrs, threshold=None),
            "tier": row["tier"],
            "updated_at": row["updated_at"],
        })
    return out

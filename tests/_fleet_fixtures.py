"""Test-only provisioning for the fleet submitter contract.

After ``add-fleet-execution-loop`` a proposal's ``source`` must be one of three
classes, and ``fleet:``/``agent:`` both need a precondition that used to be
implicit:

- ``fleet:<id>/<post>`` needs a live registration for ``<id>`` bound to the
  domain (that is the whole point of the change — a source string used to be
  accepted because nothing checked it);
- ``agent:<role>@<domain>`` needs that identity to be a live domain member.

These helpers provision the precondition. They deliberately do **not** stub the
check: ``proposals.submit`` still runs the real resolution, so a test that
forgets to provision still fails the way production would.
"""

from __future__ import annotations

from typing import Any, Iterable


def register_fleet(
    conn: Any,
    fleet_ref: str,
    domains: Iterable[str] = ("legal",),
    *,
    name: str | None = None,
) -> dict:
    """Register ``fleet_ref`` as a fleet consumer bound to ``domains``."""
    from src.bench import distribution

    return distribution.register_consumer(
        conn,
        name=name or f"test-fleet-{fleet_ref}",
        domains=list(domains),
        token_hash=f"test-hash-{fleet_ref}",
        created_by="test",
        kind="fleet",
        fleet_ref=fleet_ref,
    )


def add_agent_member(
    conn: Any, identity: str, *, domain_key: str = "legal", role: str = "expert"
) -> dict:
    """Make ``agent:<role>@<domain>`` a live member of ``domain_key``."""
    from src.bench import workspaces

    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise ValueError(f"domain {domain_key!r} does not exist")
    return workspaces.add_member(
        conn, domain_id=domain["id"], user_id=identity, role=role, added_by="test"
    )


def provision_default_fleet_world(conn: Any, domains: Iterable[str] = ("legal",)) -> None:
    """The sources the older test modules submit with, made legitimate.

    ``fleet:a/1`` and ``fleet:b/2`` appear across the proposal/team tests;
    ``agent:concept@<domain>`` is the platform-minted identity those tests use
    to exercise the self-confirmation ban. The agent member is created per
    *actual* domain key, so a module that builds ``dom-text`` never tries to
    provision a member for a domain it never created.
    """
    from src.bench import workspaces

    keys = list(domains)
    for ref in ("a", "b", "abc"):
        register_fleet(conn, ref, keys)
    for key in keys:
        if workspaces.get_domain(conn, domain_key=key) is not None:
            add_agent_member(conn, f"agent:concept@{key}", domain_key=key)

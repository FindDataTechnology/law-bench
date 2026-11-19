"""Minimal HTTP client for the fd-wire entity-layer surface (real endpoints).

Endpoint/field shapes verified against fd-wire on-disk sources (recon
2026-11-03, refreshed for add-entity-bench-contract 0050 surfaces 2026-11-05;
sibling repo is truth, never edited from here):

- ``GET  /api/v1/entities/graph``   → ``{"nodes": [GraphNodeOut], "edges":
  [GraphEdgeOut]}`` (nodes now carry ``tier``/``sensitivity``). Empty graph =
  200 with empty lists (never 404).
- ``GET  /api/v1/entities``        → ``{"entities":[EntityOut,...]}``
- ``PUT  /api/v1/entities/{id}``   → full-replacement update, request body =
  ``EntityCreateIn`` ``{name, dataset_id, pk_columns, description,
  display_column, column_notes, tier, sensitivity}`` (0050: two incremental
  optional fields, vocabulary validated server-side); errors 404 (foreign/
  not-found), 409 (uniqueness), 422 (validation).
- ``PUT  /api/v1/entities/{id}/relationships/{rid}`` (0050 NEW) → update face,
  body ``{label, tier, sensitivity}`` — three keys REQUIRED (explicit null =
  clear), structural keys rejected 422 (``extra=forbid``). Relationship
  POST/DELETE unchanged.

Auth — two credential modes, routed per face (close-wire-real-loop design D1):

- **machine mode** (READ faces only): ``X-Internal-Token`` against the
  ``/api/v1/internal/entities`` read-only mirror (fd-wire
  ``add-entity-bench-contract`` task 3.1). Needs ``WIRE_INTERNAL_TOKEN`` +
  ``WIRE_CUSTOMER_ID`` (the customer must be in the server's scope allowlist
  ``FD_WIRE_INTERNAL_ENTITY_CUSTOMERS``, else 404).
- **console mode** (WRITE faces always; READ fallback): ``Authorization:
  Bearer <Logto ID token>`` — Logto-issued ID token verified server-side
  against JWKS/iss/aud/exp. This client does NOT run the OIDC dance; you hand
  it a token.

Routing rule (single point, ``_read_request``): read faces use the machine
channel when BOTH ``internal_token`` and ``customer_id`` are present, else
console; write faces ALWAYS console and raise an actionable error when no
console token is present — never a silent machine-mode write attempt.

Credential discipline (task 1.4): tokens are never logged or embedded in
error messages (errors carry status + response snippet only); ``repr`` masks
both credential values.

Configuration (env):

- ``WIRE_API_BASE``  base URL of the wire API. Production front door is
  ``https://wire.finddatatech.cloud`` (Caddy on cheap-1 reverse-proxies
  ``/api/`` → API NodePort 31883 over the tailscale mesh). A mesh-internal
  caller can also point directly at a node's ``http://<ip>:31883``.
- ``WIRE_ID_TOKEN``  console bearer token (Logto ID token string).
- ``WIRE_INTERNAL_TOKEN``  machine token (same secret as wire's
  ``FD_WIRE_INTERNAL_TOKEN``).
- ``WIRE_CUSTOMER_ID``  customer whose entities the machine face may read
  (must be in wire's scope allowlist).

No token/base configured → the client still constructs, but requests raise
``WireAuthError``/``WireClientError`` with actionable messages (fail honestly,
never fabricate a response). ``requests`` is imported lazily so ``import
wire_connector.client`` succeeds in a stdlib-only environment (selfcheck).

Dependency direction: this connector (internal) calls the PUBLIC bench kernel
and the fd-wire API over HTTP. fd-wire and law-bench never depend on this
package — the internal→public edge is the only allowed direction.
"""

from __future__ import annotations

import os
from typing import Any, Optional


class WireClientError(RuntimeError):
    """Base: transport/protocol failure, reported honestly with status/body."""


class WireAuthError(WireClientError):
    """Missing/invalid credentials or server-side auth misconfig (401/503)."""


DEFAULT_BASE_ENV = "WIRE_API_BASE"
DEFAULT_TOKEN_ENV = "WIRE_ID_TOKEN"
DEFAULT_INTERNAL_TOKEN_ENV = "WIRE_INTERNAL_TOKEN"
DEFAULT_CUSTOMER_ENV = "WIRE_CUSTOMER_ID"


def _import_requests():
    try:
        import requests  # noqa: PLC0415 - lazy: keeps stdlib import path alive
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise WireClientError(
            "the 'requests' package is required for live calls "
            "(offline import of wire_connector.client still works)"
        ) from exc
    return requests


def _mask(value: str) -> str:
    """Credential masking for repr/debug surfaces (task 1.4)."""
    return f"<set:{len(value)}ch>" if value else "<unset>"


class WireClient:
    """Small synchronous client over the wire entity surface (requests-based).

    Dual credential modes routed per face — see module docstring.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        id_token: Optional[str] = None,
        *,
        internal_token: Optional[str] = None,
        customer_id: Optional[str] = None,
        timeout: float = 20.0,
        base_env: str = DEFAULT_BASE_ENV,
        token_env: str = DEFAULT_TOKEN_ENV,
        internal_token_env: str = DEFAULT_INTERNAL_TOKEN_ENV,
        customer_env: str = DEFAULT_CUSTOMER_ENV,
    ) -> None:
        self.base_url = (base_url or os.environ.get(base_env) or "").rstrip("/")
        self.id_token = id_token or os.environ.get(token_env) or ""
        self.internal_token = (
            internal_token
            if internal_token is not None
            else os.environ.get(internal_token_env) or ""
        )
        self.customer_id = (
            customer_id
            if customer_id is not None
            else os.environ.get(customer_env) or ""
        )
        self.timeout = timeout
        self.base_env = base_env
        self.token_env = token_env
        self.internal_token_env = internal_token_env
        self.customer_env = customer_env

    def __repr__(self) -> str:  # task 1.4: tokens never leak via repr
        return (
            f"<WireClient base={self.base_url!r} "
            f"id_token={_mask(self.id_token)} "
            f"internal_token={_mask(self.internal_token)} "
            f"customer={self.customer_id!r}>"
        )

    # -- credential posture -------------------------------------------------

    @property
    def machine_reads_available(self) -> bool:
        """Read faces may use the machine channel (both pieces present)."""
        return bool(self.internal_token and self.customer_id)

    def _require_write_credentials(self) -> None:
        """Write faces ALWAYS go console — assert console token, honestly."""
        if not self.base_url:
            raise WireClientError(
                f"no wire API base configured: set {self.base_env} (e.g. "
                "https://wire.finddatatech.cloud) or pass base_url=..."
            )
        if not self.id_token:
            raise WireAuthError(
                f"no console bearer token for the WRITE face: set "
                f"{self.token_env} with a wire-console Logto ID token — writes "
                "never go through the machine channel (reviewer attribution "
                "rides the console identity)"
            )

    # -- plumbing -----------------------------------------------------------

    def _headers(self, *, machine: bool) -> dict:
        if machine:
            return {"X-Internal-Token": self.internal_token, "Accept": "application/json"}
        return {
            "Authorization": f"Bearer {self.id_token}",
            "Accept": "application/json",
        }

    def _send(
        self,
        method: str,
        url: str,
        *,
        headers: dict,
        json_body: Any = None,
    ) -> Any:
        requests = _import_requests()
        try:
            resp = requests.request(
                method, url, headers=headers, json=json_body, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise WireClientError(f"{method} {url}: {exc}") from exc
        if resp.status_code == 401:
            raise WireAuthError(
                f"{method} {url} → 401: credential rejected (expired console "
                f"ID token, wrong X-Internal-Token, or not in scope): "
                f"{self._snippet(resp)}"
            )
        if resp.status_code == 503:
            raise WireAuthError(
                f"{method} {url} → 503: wire server lacks auth config "
                f"(fail-closed): {self._snippet(resp)}"
            )
        if resp.status_code >= 400:
            raise WireClientError(
                f"{method} {url} → HTTP {resp.status_code}: {self._snippet(resp)}"
            )
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def _request(self, method: str, path: str, *, json_body: Any = None) -> Any:
        """Console-face request (writes; legacy read helper)."""
        self._require_write_credentials()
        url = f"{self.base_url}{path}"
        return self._send(method, url, headers=self._headers(machine=False), json_body=json_body)

    @staticmethod
    def _snippet(resp) -> str:
        """Short, desensitized response excerpt (wire details may contain
        names of other parties' rows — keep it bounded; never carries the
        request credentials)."""
        text = (resp.text or "").strip().replace("\n", " ")
        return text[:240]

    # -- read surface (dual-mode routed) --------------------------------------

    def get_graph(self) -> dict:
        """Graph read: machine mirror with customer scope when configured,
        else console ``GET /api/v1/entities/graph``."""
        if self.machine_reads_available:
            return self._send(
                "GET",
                f"{self.base_url}/api/v1/internal/entities/graph"
                f"?customer_id={self.customer_id}",
                headers=self._headers(machine=True),
            )
        if not self.base_url:
            raise WireClientError(
                f"no wire API base configured: set {self.base_env} (e.g. "
                "https://wire.finddatatech.cloud) or pass base_url=..."
            )
        if not self.id_token:
            raise WireAuthError(
                "no credentials for the read face: either set "
                f"{self.internal_token_env} + {self.customer_env} (machine "
                f"channel) or {self.token_env} (console Logto ID token)"
            )
        return self._send("GET", f"{self.base_url}/api/v1/entities/graph",
                          headers=self._headers(machine=False))

    def list_entities(self) -> dict:
        """Entity list read: machine mirror with customer scope when
        configured, else console ``GET /api/v1/entities``."""
        if self.machine_reads_available:
            return self._send(
                "GET",
                f"{self.base_url}/api/v1/internal/entities"
                f"?customer_id={self.customer_id}",
                headers=self._headers(machine=True),
            )
        if not self.base_url:
            raise WireClientError(
                f"no wire API base configured: set {self.base_env} (e.g. "
                "https://wire.finddatatech.cloud) or pass base_url=..."
            )
        if not self.id_token:
            raise WireAuthError(
                "no credentials for the read face: either set "
                f"{self.internal_token_env} + {self.customer_env} (machine "
                f"channel) or {self.token_env} (console Logto ID token)"
            )
        return self._send("GET", f"{self.base_url}/api/v1/entities",
                          headers=self._headers(machine=False))

    # -- write surface (console only — see README gaps) ------------------------

    def update_entity(
        self,
        entity_id: int,
        *,
        name: str,
        dataset_id: str,
        pk_columns: list[str],
        description: Optional[str] = None,
        display_column: Optional[str] = None,
        column_notes: Optional[dict[str, str]] = None,
        tier: Optional[str] = None,
        sensitivity: Optional[str] = None,
    ) -> dict:
        """``PUT /api/v1/entities/{id}`` — full replacement of EntityCreateIn.

        0050: ``tier``/``sensitivity`` are first-class (vocabulary validated
        server-side: raw/bronze/silver/gold, public/internal/confidential).
        Upstream revalidates the whole row (409 uniqueness / 422 validation,
        zero half-writes).
        """
        body = {
            "name": name,
            "dataset_id": dataset_id,
            "pk_columns": list(pk_columns),
            "description": description,
            "display_column": display_column,
            "column_notes": column_notes,
            "tier": tier,
            "sensitivity": sensitivity,
        }
        return self._request("PUT", f"/api/v1/entities/{entity_id}", json_body=body)

    def update_relationship(
        self,
        entity_id: int,
        relationship_id: int,
        *,
        label: Optional[str],
        tier: Optional[str],
        sensitivity: Optional[str],
    ) -> dict:
        """``PUT /api/v1/entities/{id}/relationships/{rid}`` (0050 NEW) —
        update face with the three keys REQUIRED (explicit null = clear);
        structural keys would 422 (extra=forbid) and are never sent."""
        body = {"label": label, "tier": tier, "sensitivity": sensitivity}
        return self._request(
            "PUT",
            f"/api/v1/entities/{entity_id}/relationships/{relationship_id}",
            json_body=body,
        )


__all__ = [
    "DEFAULT_BASE_ENV",
    "DEFAULT_CUSTOMER_ENV",
    "DEFAULT_INTERNAL_TOKEN_ENV",
    "DEFAULT_TOKEN_ENV",
    "WireAuthError",
    "WireClient",
    "WireClientError",
]

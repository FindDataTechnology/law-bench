"""Self-managed long-lived API keys (Phase 2 auth — X-API-Key channel).

The programmatic credential for callers that are not a browser session and do
not want to obtain a Logto Bearer JWT per request (e.g. a cron job, an internal
sub-project). The user creates a key in the UI; the plaintext is shown ONCE and
never persisted or logged — only:

- ``key_prefix``  — the first 16 chars of the plaintext (public), UNIQUE-indexed
  so a lookup by the incoming key's prefix is O(1),
- ``key_hash``    — a salted slow-hash (pbkdf2-hmac-sha256) of the full
  plaintext, verified *after* the prefix lookup.

Splitting public-prefix + salted-hash is the standard API-key storage shape: the
prefix gives a fast indexed lookup without exposing the secret, and the salted
slow-hash defeats an offline dump (a fresh random salt per key). ``revoked_at``
soft-deletes a key so the row survives for audit while being unusable.

Plaintext shape: ``lbk_<43 urlsafe chars>`` (the ``lbk_`` scheme prefix lets
:func:`verify_key` recognize "this is one of ours" vs. a stray header value, and
makes a present-but-non-our-format key bind to 401 rather than silently no-op).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from typing import Any, Optional

import psycopg  # for psycopg.errors.UniqueViolation

from src.settings import DEFAULT_DB, READONLY_REPLICA  # noqa: F401 — see verify_key
from src.eval.db import connect, now_iso
from src.eval.store import ensure_schema

_log = logging.getLogger(__name__)

# --- tuning constants ------------------------------------------------------ #

_KEY_SCHEME = "lbk"        # plaintext keys look like "lbk_<43 urlsafe chars>"
_PREFIX_LEN = 16           # public lookup prefix (first 16 chars of the key)
_ITERATIONS = 100_000      # pbkdf2 cost — slow enough to deter offline brute force
_SALT_BYTES = 16
_DK_BYTES = 32             # 256-bit derived key output


# --- hashing --------------------------------------------------------------- #


def hash_key(plaintext: str) -> str:
    """Return a salted slow-hash of ``plaintext`` (pbkdf2-hmac-sha256).

    Format: ``pbkdf2_sha256$<iterations>$<salt_hex>$<dk_hex>``. A fresh random
    salt per call means identical plaintexts hash differently and an offline
    dump resists rainbow tables. The plaintext itself is never persisted.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        "sha256", plaintext.encode("utf-8"), salt, _ITERATIONS, _DK_BYTES
    )
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${dk.hex()}"


def _verify_hash(plaintext: str, stored: str) -> bool:
    """Constant-time check of ``plaintext`` against a ``hash_key`` output.

    Returns ``False`` (never raises) on any structural mismatch — a malformed
    stored hash is treated as "does not match" so the caller binds it to 401
    rather than 500-ing on a corrupt row.
    """
    try:
        scheme, iter_s, salt_hex, dk_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256", plaintext.encode("utf-8"), salt, iterations, len(expected)
    )
    return hmac.compare_digest(dk, expected)


def _gen_plaintext() -> str:
    """Generate a fresh random plaintext key: ``lbk_<43 urlsafe chars>``.

    ``secrets.token_urlsafe(32)`` yields 43 urlsafe characters (~256 bits of
    entropy); the ``lbk_`` scheme prefix marks it as one of ours.
    """
    return f"{_KEY_SCHEME}_{secrets.token_urlsafe(32)}"


# --- CRUD ------------------------------------------------------------------ #


def create_key(
    user_id: str,
    label: str,
    scopes: Optional[list[str]] = None,
    db_path: Any = DEFAULT_DB,
) -> str:
    """Create a new API key for ``user_id``; return the plaintext ONCE.

    The plaintext is returned to the caller exactly once (the UI shows it, the
    user saves it, and it is never retrievable again). Only the public prefix
    + salted hash are persisted. ``scopes`` defaults to ``[]``.

    The ``key_prefix`` UNIQUE index makes a prefix collision unrepresentable at
    the DB level; ~72 bits of prefix entropy means it is astronomically unlikely
    regardless, but the insert is retried on a :class:`UniqueViolation` so a
    collision never surfaces to the user.
    """
    ensure_schema(db_path)
    scopes_json = json.dumps(list(scopes) if scopes else [], ensure_ascii=False)

    conn = connect(db_path)
    try:
        for _attempt in range(3):  # retry on vanishingly-rare prefix collision
            plaintext = _gen_plaintext()
            prefix = plaintext[:_PREFIX_LEN]
            try:
                conn.execute(
                    "INSERT INTO api_keys "
                    "(key_prefix, key_hash, user_id, label, scopes, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        prefix,
                        hash_key(plaintext),
                        user_id,
                        label,
                        scopes_json,
                        now_iso(),
                    ),
                )
                conn.commit()
                return plaintext
            except psycopg.errors.UniqueViolation:
                conn.rollback()  # collision -> regenerate and retry
                continue
        raise RuntimeError("could not generate a unique api-key prefix")
    finally:
        conn.close()


def verify_key(plaintext: str, db_path: Any = DEFAULT_DB) -> Optional[dict]:
    """Verify an ``X-API-Key`` value; return the resolved user dict or ``None``.

    On success returns ``{"sub", "name", "email", "scopes"}`` (the API-key
    channel carries no profile claims, so ``name``/``email`` are empty — the
    stable identity is ``sub`` = the owner's ``user_id``). Returns ``None`` when
    the value is absent, not our ``lbk_`` format, has an unknown prefix, is
    revoked, or fails the hash check. ``None`` is "not a valid key":
    :mod:`deps` treats a *present* ``X-API-Key`` that resolves to ``None`` as
    present-but-invalid (-> 401, no fallthrough).

    ``last_used_at`` is refreshed (best-effort) so the key-management UI can
    show recent activity; a failure here must not break authentication.
    """
    if (
        not plaintext
        or not plaintext.startswith(f"{_KEY_SCHEME}_")
        or len(plaintext) <= _PREFIX_LEN
    ):
        return None  # absent / not our format / too short to carry a secret

    prefix = plaintext[:_PREFIX_LEN]
    ensure_schema(db_path)

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, key_hash, user_id, scopes "
            "FROM api_keys WHERE key_prefix = %s AND revoked_at IS NULL",
            (prefix,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None  # unknown prefix, or revoked -> invalid
    if not _verify_hash(plaintext, row["key_hash"]):
        return None  # prefix matched but secret did not -> invalid

    # Best-effort last_used_at refresh; never let it fail the request.
    #
    # On a read-only replica (the China public pod), skip the UPDATE entirely:
    # the standby rejects writes, so a per-request touch would only emit error
    # noise. The flag is bound at import time from the ``READONLY_REPLICA`` env;
    # tests flip it by monkeypatching this module's attribute directly.
    if not READONLY_REPLICA:
        try:
            _touch_last_used(row["id"], db_path)
        except psycopg.OperationalError as exc:
            # Read-only standby / connection lost / transient DB error. The key
            # already verified — a failed audit touch must not 401/500 the
            # request. Narrowed from a bare ``except Exception`` so a real bug
            # (e.g. a malformed UPDATE) still surfaces instead of being hidden.
            _log.debug("last_used_at touch failed for key %s: %s", row["id"], exc)
        except Exception as exc:  # noqa: BLE001 — safety net, never fatal
            _log.debug("last_used_at touch raised for key %s: %s", row["id"], exc)

    scopes = row["scopes"]
    if isinstance(scopes, str):  # JSONB came back as text (defensive)
        try:
            scopes = json.loads(scopes)
        except (ValueError, TypeError):
            scopes = []
    if not isinstance(scopes, list):
        scopes = []
    return {
        "sub": row["user_id"],
        "name": "",
        "email": "",
        "scopes": [str(s) for s in scopes if s],
    }


def _touch_last_used(key_id: int, db_path: Any) -> None:
    """Refresh ``last_used_at`` for a key (best-effort, called by verify_key)."""
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE api_keys SET last_used_at = %s WHERE id = %s",
            (now_iso(), key_id),
        )
        conn.commit()
    finally:
        conn.close()


def revoke_key(key_id: int, user_id: str, db_path: Any = DEFAULT_DB) -> bool:
    """Soft-delete (revoke) a key. ``False`` if not owner / not found.

    A cross-user revoke returns ``False`` (the route maps that to 404) rather
    than raising, so the response does not leak that the key exists. Idempotent:
    revoking an already-revoked own key returns ``True``.
    """
    ensure_schema(db_path)
    conn = connect(db_path)
    try:
        # Ownership check: only the key's owner may revoke. A non-owner (or a
        # non-existent id) yields no row -> 404, indistinguishable to the caller.
        owner = conn.execute(
            "SELECT 1 FROM api_keys WHERE id = %s AND user_id = %s",
            (key_id, user_id),
        ).fetchone()
        if owner is None:
            return False
        # COALESCE preserves the original revoked_at (idempotent re-revoke).
        conn.execute(
            "UPDATE api_keys SET revoked_at = COALESCE(revoked_at, %s) "
            "WHERE id = %s",
            (now_iso(), key_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def list_keys(user_id: str, db_path: Any = DEFAULT_DB) -> list[dict]:
    """List a user's keys (never the hash). For ``GET /api/keys``.

    Rows include the public ``key_prefix`` (so the UI can remind the user
    "lbk_abc…") and audit columns (``created_at`` / ``last_used_at`` /
    ``revoked_at``) but never ``key_hash``.
    """
    ensure_schema(db_path)
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, key_prefix, label, scopes, created_at, last_used_at, "
            "revoked_at FROM api_keys WHERE user_id = %s "
            "ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    for r in rows:
        scopes = r["scopes"]
        if isinstance(scopes, str):
            try:
                scopes = json.loads(scopes)
            except (ValueError, TypeError):
                scopes = []
        out.append(
            {
                "id": r["id"],
                "key_prefix": r["key_prefix"],
                "label": r["label"],
                "scopes": scopes if isinstance(scopes, list) else [],
                "created_at": r["created_at"],
                "last_used_at": r["last_used_at"],
                "revoked_at": r["revoked_at"],
            }
        )
    return out

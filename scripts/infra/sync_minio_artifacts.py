#!/usr/bin/env python3
"""Mirror the ``artifacts/`` prefix from origin MinIO to a local MinIO.

Run on (or reachable from) the China box — copies new/changed docx/pdf objects
from the origin ``scraw-law-contracts`` bucket's ``artifacts/`` prefix into the
local MinIO so the public pod's ``GET /api/contracts/artifacts/{id}/download``
and the ``/samples`` browse page serve China-local bytes with no per-request
border crossing (task 5.1). Pairs with the Postgres logical-replication sync
(task 4.x): the ``contract_artifacts`` *rows* arrive via replication, but the
*binary docx/pdf objects* are in MinIO and need this separate mirror.

Content-addressed keys (``artifacts/{contract_type}/{artifact_id}.{ext}``) make
re-runs cheap: an object already present with matching size is skipped, so a
cron tick that finds nothing new is a handful of ``HEAD`` requests, not a full
re-copy. This is the MinIO analogue of fallback-A's ``pg_dump`` cadence — it
does not require a persistent connection (each run is a fresh scan), so it is
resilient to an intermittently-severed border link (a missed tick just leaves
the mirror staler by one cadence).

Auth/credentials: reads both endpoints' creds from the environment (the origin
``minio_root_user`` / ``minio_root_password`` + ``minio_host``, plus the local
``MINIO_LOCAL_HOST`` / ``MINIO_LOCAL_USER`` / ``MINIO_LOCAL_PASSWORD``). The
origin endpoint defaults to the deploy's ``minio_host``
(``http://23.144.68.246:30900``); override via ``--origin-host``. The local
endpoint defaults to ``$MINIO_LOCAL_HOST``; override via ``--local-host``.

Usage::

    # mirror artifacts from origin to local, hourly cron:
    python scripts/infra/sync_minio_artifacts.py \\
        --origin-host http://23.144.68.246:30900 \\
        --local-host http://localhost:9000

    # dry-run (list what would be copied, copy nothing):
    python scripts/infra/sync_minio_artifacts.py --dry-run

Exit code is 0 on success (including a dry-run), non-zero on a fatal error.
Per-object failures are logged and counted but do not fail the whole run — a
flaky border link should not abort the sync of the objects that *are*
reachable; the next tick retries the misses.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from urllib.parse import urlparse

# botocore/minio honor the macOS system proxy, which 502s against MinIO; bypass
# proxies entirely for the S3 client (same workaround as src/contracts/artifacts).
os.environ.setdefault("NO_PROXY", "*")

from minio import Minio  # noqa: E402

ARTIFACTS_PREFIX = os.environ.get("MINIO_ARTIFACTS_PREFIX", "artifacts/")
BUCKET = os.environ.get("MINIO_BUCKET", "scraw-law-contracts")

log = logging.getLogger("sync_minio_artifacts")


def _client(host: str, user: str, password: str) -> Minio:
    """Build a Minio client from a full ``host`` URL + creds."""
    secure = host.startswith("https")
    endpoint = urlparse(host).netloc
    if not endpoint:
        raise ValueError(f"invalid --host URL (no netloc): {host!r}")
    return Minio(endpoint, access_key=user, secret_key=password, secure=secure, cert_check=False)


def _list_objects(client: Minio, bucket: str, prefix: str) -> list:
    """List objects under ``prefix`` (non-recursive-safe; minio lists deeply)."""
    return list(client.list_objects(bucket, prefix=prefix, recursive=True))


def _copy_one(src: Minio, dst: Minio, bucket: str, obj, *, dry_run: bool) -> str:
    """Copy one object if missing/changed; return 'copied' | 'skipped' | 'failed'.

    Skips when the destination already has an object of the same name AND size —
    the content-addressed keys make size a sufficient equality proxy (a key is
    ``artifacts/{type}/{id}.{ext}`` and the artifact id pins the content). No
    ETag/MD5 round-trip needed; the size check is cheap and correct here.
    """
    name = obj.object_name
    try:
        existing = dst.stat_object(bucket, name)
    except Exception:
        existing = None  # not present -> copy

    if existing is not None and existing.size == obj.size:
        return "skipped"

    if dry_run:
        log.info("[dry-run] would copy %s (%d bytes)", name, obj.size)
        return "copied"

    # minio's copy_object server-side copies within/between endpoints the S3
    # client can reach; for a cross-border mirror where the local MinIO cannot
    # reach the origin, fall back to GET-then-PUT (download to a temp, upload).
    try:
        dst.copy_object(bucket, name, src, name)
    except Exception:
        # Cross-border: the destination MinIO's node likely cannot dial the
        # origin endpoint (GFW / no route). Fall back to a client-side relay:
        # stream the object through this process and PUT it to the local MinIO.
        log.debug("copy_object failed for %s, falling back to GET-then-PUT", name)
        try:
            response = src.get_object(bucket, name)
            try:
                dst.put_object(bucket, name, response, length=obj.size)
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:  # noqa: BLE001 — per-object, logged + counted
            log.warning("failed to copy %s: %s", name, exc)
            return "failed"
    return "copied"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("--origin-host", default=os.environ.get("minio_host", "http://23.144.68.246:30900"))
    ap.add_argument("--origin-user", default=os.environ.get("minio_root_user", ""))
    ap.add_argument("--origin-pass", default=os.environ.get("minio_root_password", ""))
    ap.add_argument("--local-host", default=os.environ.get("MINIO_LOCAL_HOST", "http://localhost:9000"))
    ap.add_argument("--local-user", default=os.environ.get("MINIO_LOCAL_USER", os.environ.get("minio_root_user", "")))
    ap.add_argument("--local-pass", default=os.environ.get("MINIO_LOCAL_PASSWORD", os.environ.get("minio_root_password", "")))
    ap.add_argument("--bucket", default=BUCKET)
    ap.add_argument("--prefix", default=ARTIFACTS_PREFIX)
    ap.add_argument("--dry-run", action="store_true", help="list what would be copied, copy nothing")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.origin_user or not args.origin_pass:
        log.error("origin MinIO creds missing (set minio_root_user / minio_root_password or pass --origin-user/--origin-pass)")
        return 2
    if not args.local_user or not args.local_pass:
        log.error("local MinIO creds missing (set MINIO_LOCAL_USER / MINIO_LOCAL_PASSWORD or pass --local-user/--local-pass)")
        return 2

    src = _client(args.origin_host, args.origin_user, args.origin_pass)
    dst = _client(args.local_host, args.local_user, args.local_pass)

    # Ensure the local bucket exists (idempotent).
    try:
        if not dst.bucket_exists(args.bucket):
            dst.make_bucket(args.bucket)
            log.info("created local bucket %s", args.bucket)
    except Exception as exc:  # noqa: BLE001
        log.error("cannot reach local MinIO / create bucket: %s", exc)
        return 3

    log.info("listing origin %s/%s ...", args.bucket, args.prefix)
    try:
        objects = _list_objects(src, args.bucket, args.prefix)
    except Exception as exc:  # noqa: BLE001 — origin unreachable is fatal here
        log.error("cannot list origin MinIO: %s", exc)
        return 4

    log.info("origin has %d objects under %s", len(objects), args.prefix)
    copied = skipped = failed = 0
    for obj in objects:
        result = _copy_one(src, dst, args.bucket, obj, dry_run=args.dry_run)
        if result == "copied":
            copied += 1
            log.info("copied %s", obj.object_name)
        elif result == "skipped":
            skipped += 1
        else:
            failed += 1

    log.info("done: %d copied, %d skipped, %d failed", copied, skipped, failed)
    # Per-object failures do not fail the run (a flaky link should not abort the
    # reachable copies; the next tick retries the misses). Only a total failure
    # (origin unreachable) exits non-zero, handled above.
    return 0


if __name__ == "__main__":
    sys.exit(main())

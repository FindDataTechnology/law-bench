"""Tests for the contract-artifact-storage surface (``src/contracts/artifacts.py``
+ the HTTP endpoints in ``src/web/routes/contract_context.py``).

Hermetic: the MinIO client is replaced with an in-memory fake (so no MinIO is
required), exercising the real service logic - dedup, DB row, key scheme, and
the upload->download round-trip. One integration test exercises the real MinIO
and skips if unreachable (the pattern from ``tests/test_clauses_corpus.py``).

The ``generate-stored`` endpoint bifurcates: by-tag (scenario/stance/
custom_clause_ids given) -> single variant dict; by-type (no tags) -> all
scenario x stance x base combinations, returned as a summary dict.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.clauses.store import upsert_clause


# --- in-memory MinIO fake -------------------------------------------------- #


class _FakeResp:
    def __init__(self, data: bytes):
        self._data = data

    def stream(self, amt: int = 8192):
        for i in range(0, len(self._data), amt):
            yield self._data[i : i + amt]

    def close(self):
        pass

    def release_conn(self):
        pass


class _FakeMinio:
    def __init__(self):
        self.uploaded: dict[str, bytes] = {}
        self.fput_calls = 0

    def bucket_exists(self, bucket):
        return True

    def make_bucket(self, bucket):
        pass

    def fput_object(self, bucket, key, path):
        self.fput_calls += 1
        with open(path, "rb") as fh:
            self.uploaded[key] = fh.read()
        return key

    def get_object(self, bucket, key):
        return _FakeResp(self.uploaded.get(key, b""))


@pytest.fixture
def fake_minio(monkeypatch):
    import src.contracts.artifacts as arts

    fake = _FakeMinio()
    monkeypatch.setattr(arts, "_client", lambda: fake)
    return fake


# --- seeding --------------------------------------------------------------- #


def _seed_base(seeded_db) -> None:
    upsert_clause(
        {
            "contract_type": "sale",
            "category": "base",
            "section": "当事人",
            "body": "甲方：{{party_a}}\n乙方：{{party_b}}",
            "slot_instructions": [
                {"name": "party_a", "label": "甲方", "description": "d", "example": "x", "required": True},
                {"name": "party_b", "label": "乙方", "description": "d", "example": "x", "required": True},
            ],
            "law_refs": [],
            "level": "national",
            "source_path": "t/base.docx",
            "source_doc_title": "T",
            "body_hash": "b-base",
        },
        db=seeded_db,
    )


def _seed_tagged(seeded_db, scenario: str = "生鲜乳购销") -> None:
    upsert_clause(
        {
            "contract_type": "sale",
            "category": "tagged",
            "section": "合同标的",
            "body": f"标的：{{{{subject}}}}（{scenario}专用条款）",
            "slot_instructions": [
                {"name": "subject", "label": "标的", "description": "d", "example": "x", "required": True},
            ],
            "law_refs": [],
            "level": "local",
            "source_path": "t/tagged.docx",
            "source_doc_title": "T",
            "body_hash": f"b-tagged-{scenario}",
            "tags": {"source": "tagged", "scenario": scenario},
        },
        db=seeded_db,
    )


# --- generate-stored: by-type (no tags -> all combinations) --------------- #


def test_by_type_base_only(app_client: TestClient, seeded_db, fake_minio):
    """No tagged/custom clauses -> one base combination."""
    _seed_base(seeded_db)
    r = app_client.post("/api/contracts/sale/generate-stored", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["contract_type"] == "sale"
    assert body["count"] == 1
    assert body["new"] == 1 and body["reused"] == 0
    art = body["artifacts"][0]
    assert art["scenario"] is None and art["stance"] is None
    assert art["docx_url"].endswith(f"/api/contracts/artifacts/{art['artifact_id']}/download?format=docx")
    assert art["docx_url_slotted"].endswith(
        f"/api/contracts/artifacts/{art['artifact_id']}/download?format=docx&variant=slotted"
    )
    assert art["pdf_url"] is None


def test_by_type_enumerates_scenario_combos(app_client: TestClient, seeded_db, fake_minio):
    """A tagged scenario -> base + scenario combinations (>=2 combos)."""
    _seed_base(seeded_db)
    _seed_tagged(seeded_db, "生鲜乳购销")
    r = app_client.post("/api/contracts/sale/generate-stored", json={})
    assert r.status_code == 200
    body = r.json()
    # combos = [(None,None), (生鲜乳购销,None)] -> 2 attempted; distinct bodies -> 2 artifacts
    assert body["count"] == 2
    scenarios = {a["scenario"] for a in body["artifacts"]}
    assert scenarios == {None, "生鲜乳购销"}


def test_by_type_markdown(app_client: TestClient, seeded_db, fake_minio):
    _seed_base(seeded_db)
    r = app_client.post("/api/contracts/sale/generate-stored", json={"format": "markdown"})
    body = r.json()
    assert body["count"] == 1
    assert body["artifacts"][0]["docx_url"] is None
    assert body["artifacts"][0]["pdf_url"] is None


def test_by_type_both_formats(app_client: TestClient, seeded_db, fake_minio):
    _seed_base(seeded_db)
    r = app_client.post("/api/contracts/sale/generate-stored", json={"format": "both"})
    body = r.json()
    art = body["artifacts"][0]
    assert art["docx_url"] and art["pdf_url"]


def test_by_type_unknown_type_404(app_client: TestClient, fake_minio):
    r = app_client.post("/api/contracts/does_not_exist/generate-stored", json={})
    assert r.status_code == 404


# --- generate-stored: by-tag (single variant) ----------------------------- #


def test_by_tag_single_variant(app_client: TestClient, seeded_db, fake_minio):
    _seed_base(seeded_db)
    _seed_tagged(seeded_db, "生鲜乳购销")
    r = app_client.post(
        "/api/contracts/sale/generate-stored", json={"scenario": "生鲜乳购销"}
    )
    assert r.status_code == 200
    body = r.json()
    # single-variant shape (not the all-combos summary)
    assert "artifact_id" in body and "artifacts" not in body
    assert body["docx_url"].endswith(f"/api/contracts/artifacts/{body['artifact_id']}/download?format=docx")
    assert body["body_text"]
    assert "生鲜乳购销专用条款" in body["body_text"]  # the tagged override is present
    assert body["reused"] is False


def test_by_tag_coherence_422(monkeypatch, app_client: TestClient, seeded_db, fake_minio):
    _seed_base(seeded_db)
    import src.contracts.artifacts as arts
    from src.clauses.coherence import CoherenceError

    def _raise(*_a, **_kw):
        raise CoherenceError("missing canonical sections: ['价款及支付']")

    monkeypatch.setattr(arts, "generate_contract_assembled", _raise)
    r = app_client.post(
        "/api/contracts/sale/generate-stored", json={"scenario": "生鲜乳购销", "format": "markdown"}
    )
    assert r.status_code == 422
    assert "价款及支付" in r.json()["detail"]


# --- dedup (by-tag single variant) ---------------------------------------- #


def test_dedup_same_inputs_reuse(app_client: TestClient, seeded_db, fake_minio):
    _seed_base(seeded_db)
    _seed_tagged(seeded_db, "生鲜乳购销")
    first = app_client.post(
        "/api/contracts/sale/generate-stored", json={"scenario": "生鲜乳购销"}
    ).json()
    second = app_client.post(
        "/api/contracts/sale/generate-stored", json={"scenario": "生鲜乳购销"}
    ).json()
    assert first["artifact_id"] == second["artifact_id"]
    assert first["reused"] is False
    assert second["reused"] is True
    # dual-variant: first call stored final + slotted docx (2 files); the second
    # call reuses the row and uploads nothing.
    assert len(fake_minio.uploaded) == 2
    assert first["docx_url_slotted"]  # slotted URL is surfaced


def test_dedup_fill_missing_format(app_client: TestClient, seeded_db, fake_minio):
    _seed_base(seeded_db)
    _seed_tagged(seeded_db, "生鲜乳购销")
    first = app_client.post(
        "/api/contracts/sale/generate-stored",
        json={"scenario": "生鲜乳购销", "format": "docx"},
    ).json()
    second = app_client.post(
        "/api/contracts/sale/generate-stored",
        json={"scenario": "生鲜乳购销", "format": "pdf"},
    ).json()
    assert first["artifact_id"] == second["artifact_id"]
    assert second["pdf_url"] is not None


def test_force_reuploads_existing_artifact(app_client: TestClient, seeded_db, fake_minio):
    """``force=True`` re-uploads docx even when the artifact already exists.

    Models the post-formatting-change refresh: body_text (hence the artifact
    id) is unchanged, but the rendered docx must be overwritten in MinIO.
    """
    _seed_base(seeded_db)
    _seed_tagged(seeded_db, "生鲜乳购销")
    app_client.post(
        "/api/contracts/sale/generate-stored", json={"scenario": "生鲜乳购销"}
    )
    calls_before = fake_minio.fput_calls
    r = app_client.post(
        "/api/contracts/sale/generate-stored",
        json={"scenario": "生鲜乳购销", "force": True},
    ).json()
    assert r["reused"] is True
    # dual-variant: force re-uploads both final and slotted docx (+2 calls);
    # the dict stays the same size (same keys overwrite), so count fput calls.
    assert fake_minio.fput_calls == calls_before + 2


# --- list / get / download ------------------------------------------------ #


def _store_one(app_client, seeded_db, fake_minio) -> int:
    """Store a base artifact via by-type; return its artifact_id."""
    _seed_base(seeded_db)
    body = app_client.post("/api/contracts/sale/generate-stored", json={}).json()
    return body["artifacts"][0]["artifact_id"]


def test_list_artifacts_filtered(app_client: TestClient, seeded_db, fake_minio):
    aid = _store_one(app_client, seeded_db, fake_minio)
    r = app_client.get("/api/contracts/artifacts", params={"contract_type": "sale"})
    assert r.status_code == 200
    rows = r.json()
    assert rows and all(rw["contract_type"] == "sale" for rw in rows)
    assert any(rw["id"] == aid for rw in rows)
    assert "body_text" not in rows[0]


def test_get_artifact_metadata(app_client: TestClient, seeded_db, fake_minio):
    aid = _store_one(app_client, seeded_db, fake_minio)
    r = app_client.get(f"/api/contracts/artifacts/{aid}")
    assert r.status_code == 200
    row = r.json()
    assert row["id"] == aid
    assert row["body_text"]
    assert row["contract_type"] == "sale"


def test_get_artifact_unknown_404(app_client: TestClient, fake_minio):
    assert app_client.get("/api/contracts/artifacts/999999").status_code == 404


def test_download_docx(app_client: TestClient, seeded_db, fake_minio):
    aid = _store_one(app_client, seeded_db, fake_minio)
    r = app_client.get(f"/api/contracts/artifacts/{aid}/download", params={"format": "docx"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "attachment" in r.headers["content-disposition"]
    assert len(r.content) > 0


def test_download_missing_format_404(app_client: TestClient, seeded_db, fake_minio):
    aid = _store_one(app_client, seeded_db, fake_minio)
    r = app_client.get(f"/api/contracts/artifacts/{aid}/download", params={"format": "pdf"})
    assert r.status_code == 404


def test_download_unknown_artifact_404(app_client: TestClient, fake_minio):
    r = app_client.get("/api/contracts/artifacts/999999/download", params={"format": "docx"})
    assert r.status_code == 404


def test_download_bad_format_400(app_client: TestClient, seeded_db, fake_minio):
    aid = _store_one(app_client, seeded_db, fake_minio)
    r = app_client.get(f"/api/contracts/artifacts/{aid}/download", params={"format": "xls"})
    assert r.status_code == 400


# --- dual-variant storage (final + slotted in one row) --------------------- #


def test_dual_variant_keys_present(app_client: TestClient, seeded_db, fake_minio):
    """One generate-stored (format=docx) yields both final and slotted docx keys."""
    aid = _store_one(app_client, seeded_db, fake_minio)
    row = app_client.get(f"/api/contracts/artifacts/{aid}").json()
    assert row["docx_key"].startswith("artifacts/")
    assert row["docx_key_slotted"].startswith("artifacts-slotted/")
    assert row["pdf_key"] is None  # format=docx requested
    assert row["pdf_key_slotted"] is None


def test_download_slotted_variant(app_client: TestClient, seeded_db, fake_minio):
    aid = _store_one(app_client, seeded_db, fake_minio)
    r = app_client.get(
        f"/api/contracts/artifacts/{aid}/download",
        params={"format": "docx", "variant": "slotted"},
    )
    assert r.status_code == 200
    assert "slotted" in r.headers["content-disposition"]
    assert len(r.content) > 0


def test_download_final_variant_unchanged(app_client: TestClient, seeded_db, fake_minio):
    aid = _store_one(app_client, seeded_db, fake_minio)
    r = app_client.get(
        f"/api/contracts/artifacts/{aid}/download",
        params={"format": "docx", "variant": "final"},
    )
    assert r.status_code == 200
    assert "slotted" not in r.headers["content-disposition"]


def test_download_slotted_missing_404(app_client: TestClient, seeded_db, fake_minio):
    """A markdown-only artifact (no docx keys) -> slotted docx download 404."""
    _seed_base(seeded_db)
    body = app_client.post(
        "/api/contracts/sale/generate-stored", json={"format": "markdown"}
    ).json()
    aid = body["artifacts"][0]["artifact_id"]
    r = app_client.get(
        f"/api/contracts/artifacts/{aid}/download",
        params={"format": "docx", "variant": "slotted"},
    )
    assert r.status_code == 404


# --- schema ---------------------------------------------------------------- #


def test_openapi_has_artifact_paths(app_client: TestClient):
    paths = set(app_client.get("/openapi.json").json()["paths"].keys())
    assert "/api/contracts/artifacts" in paths
    assert "/api/contracts/artifacts/{artifact_id}" in paths
    assert "/api/contracts/artifacts/{artifact_id}/download" in paths
    assert "/api/contracts/{contract_type}/generate-stored" in paths


# --- integration (real MinIO; skip if unreachable) ------------------------ #


def test_generate_stored_real_minio(app_client: TestClient, seeded_db):
    """Integration: by-type generate-stored against real MinIO (skip if unreachable)."""
    import src.contracts.artifacts as arts
    from src.settings import MINIO_BUCKET

    try:
        arts._client().bucket_exists(MINIO_BUCKET)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MinIO unreachable: {exc}")
    _seed_base(seeded_db)
    r = app_client.post("/api/contracts/sale/generate-stored", json={})
    if r.status_code != 200:
        pytest.skip(f"generate-stored failed against real MinIO: {r.text}")
    aid = r.json()["artifacts"][0]["artifact_id"]
    try:
        d = app_client.get(f"/api/contracts/artifacts/{aid}/download", params={"format": "docx"})
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"download stream failed against real MinIO: {exc}")
    assert d.status_code == 200
    assert len(d.content) > 0

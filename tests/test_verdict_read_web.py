"""Machine read face for the verdict ledger (add-eval-verdict-ledger, task 3.5).

The ledger landed in-process; a fleet that runs in another process — or another
product line entirely (壹座) — had no way to read it. These tests cover the three
routes that closed that gap, all through HTTP against the real app.

What they pin, in the order each one would bite:

- **auth is the same three-state check** as every other machine route: no token
  = 401 naming the header, unregistered/revoked = 403, out of scope = 403.
- **scope is the domain's own subtree**, computed the same way the run list
  computes it, so the two can never disagree.
- **`inconclusive` survives the wire.** A reader that folds it into `fail`
  learns the wrong lesson from a broken judge.
- **an unknown gate is refused, not filtered.** A 200 with an empty list looks
  exactly like "no such verdicts" — a different and false statement.
- **another domain's run id answers 404, never 403**, so the id is not confirmed
  to exist elsewhere.

The seed writes evaluations through ``store_result`` (the real write path), then
asserts against HTTP — no mocks of the ledger.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import distribution as bench_distribution
from src.bench import templates as bench_templates
from src.bench import workspaces
from src.bench.domain_rubrics import create_for_domain
from src.eval.store import store_result
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

VALID_SCHEMA = {
    "entity_types": ["company"],
    "concept_structures": {"indicator": ["name", "unit"]},
    "relationship_kinds": ["belongs_to"],
    "tier_vocabulary": ["gold", "silver", "bronze", "raw"],
    "sensitivity_vocabulary": ["public", "internal", "confidential"],
    "corpus_declaration": {"source_types": []},
}

TEMPLATE_NAME = "verdict-read-template"
A_KEY = "verdict-a"
B_KEY = "verdict-b"
TOKEN_A = "token-for-a-0123456789abcdef"
TOKEN_B = "token-for-b-0123456789abcdef"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _seed(conn) -> dict:
    """Two domains sharing one template, each with one fleet consumer + a rubric.

    Each domain gets its OWN rubric (its own digest), so the ruler list can be
    checked for "this domain's rulers only".
    """
    bench_templates.create_template(
        conn, name=TEMPLATE_NAME, schema=dict(VALID_SCHEMA), created_by="seed"
    )
    a = workspaces.instantiate_domain(
        conn, key=A_KEY, name="结论甲域", template_name=TEMPLATE_NAME,
        template_version=None, created_by="seed",
    )
    b = workspaces.instantiate_domain(
        conn, key=B_KEY, name="结论乙域", template_name=TEMPLATE_NAME,
        template_version=None, created_by="seed",
    )
    # Criteria are mandatory for a ruler whose digest is computed over them.
    rubric_a = create_for_domain(
        conn, domain_id=a["id"], name=f"{A_KEY}-rubric", context="check",
        criteria=[{"name": "c1", "description": "t", "guidance": "g"}],
        description="甲域尺子",
    )
    rubric_b = create_for_domain(
        conn, domain_id=b["id"], name=f"{B_KEY}-rubric", context="check",
        criteria=[{"name": "c1", "description": "t", "guidance": "g"}],
        description="乙域尺子",
    )
    for name, token, domain_key in (("fleet-a", TOKEN_A, A_KEY), ("fleet-b", TOKEN_B, B_KEY)):
        consumer = bench_distribution.register_consumer(
            conn, name=name, domains=[domain_key], token_hash=_digest(token),
            created_by="seed",
        )
        bench_distribution.promote_consumer_to_fleet(
            conn, name=consumer["name"], fleet_ref=f"fleet_{name}"
        )
    return {
        "a": a, "b": b,
        "rubric_a": rubric_a, "rubric_b": rubric_b,
        # ``eval_runs.rubric_domain_id`` is a DOMAIN id, not a rubric id — the
        # two are easy to confuse because both are "the id of the thing the
        # rubric belongs to". Kept explicit so a later edit cannot re-mix them.
        "domain_a_id": a["id"], "domain_b_id": b["id"],
    }


def _verdict(conn, *, domain_path: str, rubric_name: str, rubric_domain_id: int,
             subject_kind="pack", subject_key="builder", outcome="pass") -> int:
    """Write one ledger row through the REAL write path, attributed to a domain."""
    run_id = store_result(
        {
            "rubric": rubric_name, "score": 1.0 if outcome == "pass" else 0.0,
            "max_score": 1.0, "all_pass": outcome == "pass",
            "n_criteria": 1, "n_passed": 1 if outcome == "pass" else 0,
            "summary": "seed", "judge_model": "glm-5.2",
            "criteria_results": [
                {"id": "c1", "title": "t", "verdict": "pass", "reasoning": "ok"}
            ],
        },
        db_path=conn,
        subject_kind=subject_kind, subject_key=subject_key, subject_version="v1",
        ruler_kind="rubric", ruler_key=rubric_name, ruler_digest="a" * 64,
        gate="all-pass", outcome=outcome,
    )
    conn.execute(
        "UPDATE eval_runs SET rubric_domain_id = %s WHERE id = %s",
        (rubric_domain_id, run_id),
    )
    conn.commit()
    return run_id


def _user(sub: str, scopes: list[str]) -> User:
    return User(sub=sub, name=sub, email=f"{sub}@example.com",
                scopes=list(scopes), channel="test")


def _client(db, user: User) -> TestClient:
    app = create_app()

    def _current_user(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


def _bare_client(db) -> TestClient:
    """Machine client: ONLY get_db overridden — the route's token check is auth."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _get(client, path: str, token: str | None = None, **query):
    headers = {"X-Consumer-Token": token} if token is not None else {}
    return client.get(path, params=query or None, headers=headers)


# --- auth ------------------------------------------------------------------ #


def test_no_token_is_401_naming_the_header(seeded_db):
    _seed(seeded_db)
    with _bare_client(seeded_db) as bare:
        r = _get(bare, f"/api/v1/distribution/{A_KEY}/verdicts")
    assert r.status_code == 401
    assert "X-Consumer-Token" in r.json()["detail"]


def test_unknown_token_is_403(seeded_db):
    _seed(seeded_db)
    with _bare_client(seeded_db) as bare:
        r = _get(bare, f"/api/v1/distribution/{A_KEY}/verdicts", "not-a-real-token")
    assert r.status_code == 403


def test_cross_domain_read_is_403_not_empty(seeded_db):
    """A's token asking for B must not get an empty 200 — that reads as
    "B has no verdicts", which is a different and false statement."""
    _seed(seeded_db)
    with _bare_client(seeded_db) as bare:
        r = _get(bare, f"/api/v1/distribution/{B_KEY}/verdicts", TOKEN_A)
    assert r.status_code == 403
    assert B_KEY not in r.text or "不在绑定范围" in r.json()["detail"]


# --- the ledger ------------------------------------------------------------ #


def test_verdicts_are_scoped_to_the_domain(seeded_db):
    world = _seed(seeded_db)
    mine = _verdict(seeded_db, domain_path=world["a"]["path"],
                    rubric_name=f"{A_KEY}-rubric", rubric_domain_id=world["domain_a_id"])
    _verdict(seeded_db, domain_path=world["b"]["path"],
             rubric_name=f"{B_KEY}-rubric", rubric_domain_id=world["domain_b_id"])

    with _bare_client(seeded_db) as bare:
        r = _get(bare, f"/api/v1/distribution/{A_KEY}/verdicts", TOKEN_A)
    assert r.status_code == 200
    ids = [v["id"] for v in r.json()["verdicts"]]
    assert ids == [mine]


def test_inconclusive_survives_the_wire(seeded_db):
    world = _seed(seeded_db)
    _verdict(seeded_db, domain_path=world["a"]["path"],
             rubric_name=f"{A_KEY}-rubric", rubric_domain_id=world["domain_a_id"],
             outcome="inconclusive")
    with _bare_client(seeded_db) as bare:
        r = _get(bare, f"/api/v1/distribution/{A_KEY}/verdicts", TOKEN_A)
    assert [v["outcome"] for v in r.json()["verdicts"]] == ["inconclusive"]


def test_unknown_gate_is_400_not_an_empty_list(seeded_db):
    _seed(seeded_db)
    with _bare_client(seeded_db) as bare:
        r = _get(bare, f"/api/v1/distribution/{A_KEY}/verdicts", TOKEN_A,
                 gate="better-than")
    assert r.status_code == 400
    assert "better-than" in r.json()["detail"]


def test_gate_filter_narrows(seeded_db):
    world = _seed(seeded_db)
    for gate, name in (("all-pass", "x"), ("regression", "y")):
        rid = _verdict(seeded_db, domain_path=world["a"]["path"],
                       rubric_name=f"{A_KEY}-rubric",
                       rubric_domain_id=world["domain_a_id"])
        seeded_db.execute("UPDATE eval_runs SET gate = %s WHERE id = %s", (gate, rid))
    seeded_db.commit()

    with _bare_client(seeded_db) as bare:
        r = _get(bare, f"/api/v1/distribution/{A_KEY}/verdicts", TOKEN_A, gate="regression")
    assert r.json()["count"] == 1


def test_one_verdict_carries_its_criteria(seeded_db):
    world = _seed(seeded_db)
    rid = _verdict(seeded_db, domain_path=world["a"]["path"],
                   rubric_name=f"{A_KEY}-rubric",
                   rubric_domain_id=world["domain_a_id"])
    with _bare_client(seeded_db) as bare:
        r = _get(bare, f"/api/v1/distribution/{A_KEY}/verdicts/{rid}", TOKEN_A)
    assert r.status_code == 200
    body = r.json()["verdict"]
    assert body["id"] == rid
    assert len(body["criteria_results"]) == 1


def test_another_domains_run_id_is_404_not_403(seeded_db):
    """403 would confirm the id exists somewhere. 404 says nothing."""
    world = _seed(seeded_db)
    other = _verdict(seeded_db, domain_path=world["b"]["path"],
                     rubric_name=f"{B_KEY}-rubric",
                     rubric_domain_id=world["domain_b_id"])
    with _bare_client(seeded_db) as bare:
        r = _get(bare, f"/api/v1/distribution/{A_KEY}/verdicts/{other}", TOKEN_A)
    assert r.status_code == 404


# --- rulers ---------------------------------------------------------------- #


def test_rulers_are_this_domains_and_carry_digests(seeded_db):
    _seed(seeded_db)
    with _bare_client(seeded_db) as bare:
        r = _get(bare, f"/api/v1/distribution/{A_KEY}/rulers", TOKEN_A)
    assert r.status_code == 200
    rulers = r.json()["rulers"]
    keys = [x["key"] for x in rulers]
    assert f"{A_KEY}-rubric" in keys
    assert f"{B_KEY}-rubric" not in keys
    assert all(len(x["digest"]) == 64 for x in rulers)


def test_ruler_digest_matches_the_write_time_one(seeded_db):
    """The digest a consumer reads here MUST equal the one a verdict records —
    otherwise "same ruler" is unanswerable across the boundary."""
    world = _seed(seeded_db)
    from src.bench import verdicts as bench_verdicts

    expected = bench_verdicts.rubric_ruler(f"{A_KEY}-rubric", db_path=seeded_db)
    with _bare_client(seeded_db) as bare:
        r = _get(bare, f"/api/v1/distribution/{A_KEY}/rulers", TOKEN_A)
    got = {x["key"]: x["digest"] for x in r.json()["rulers"]}[f"{A_KEY}-rubric"]
    assert got == expected["digest"]

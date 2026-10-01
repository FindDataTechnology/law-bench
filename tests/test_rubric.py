"""Unit tests for ``src/eval/rubric.py`` against a throwaway seeded DB."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.eval import manage as M
from src.eval.rubric import list_rubrics, load_criteria


def test_list_rubrics(seeded_db: Path):
    rubrics = {r["name"]: r for r in list_rubrics(db_path=seeded_db)}
    assert "h_rubric" in rubrics
    assert "l_rubric" in rubrics
    assert rubrics["h_rubric"]["source"].startswith("harbor:")
    assert rubrics["l_rubric"]["source"] == "local"


def test_load_criteria_maps_to_harvey_labs_shape(seeded_db: Path):
    crits = load_criteria("l_rubric", db_path=seeded_db)
    assert [c["id"] for c in crits] == ["c1", "c2"]
    assert crits[0]["title"] == "d"
    assert crits[0]["match_criteria"] == "g"


def test_load_criteria_unknown_rubric_raises_keyerror(seeded_db: Path):
    with pytest.raises(KeyError):
        load_criteria("nope", db_path=seeded_db)


def test_load_criteria_empty_rubric_raises_valueerror(seeded_db: Path):
    M.create_rubric("empty", "contract", "d", [], db_path=seeded_db)
    with pytest.raises(ValueError):
        load_criteria("empty", db_path=seeded_db)

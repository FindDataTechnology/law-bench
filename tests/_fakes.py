"""In-process test doubles for the evaluation engine.

``FakeJudge`` impersonates a deepeval ``DeepEvalBaseLLM`` so that
``scoring.evaluate_contract(..., judge=FakeJudge(...))`` runs the real
aggregation/threading path with no network: ``GEval.measure`` calls the judge's
``generate`` (via ``generate_with_schema``) instead of hitting an LLM endpoint.

Per-criterion verdicts are deterministic because tests call ``evaluate_contract``
with ``max_workers=1``: the single-worker thread pool then judges criteria in
submission order, so the FakeJudge's verdict queue is consumed in the same order
as the rubric's criteria. (The deepeval model interface is criterion-agnostic -
it does not pass the criterion id to ``generate`` - so verdicts are keyed by
criteria order rather than by id.)

Contract (the attributes ``src/eval/scoring.py`` reads off each metric):
- ``measure(test_case, _show_indicator=False)`` is called once per criterion
- after ``measure``, scoring reads ``success`` (bool), ``reason`` (str),
  ``error`` (str|None), and ``evaluation_model`` (str|None)
"""

from __future__ import annotations

import json
from typing import Optional, Union

from deepeval.models import DeepEvalBaseLLM

# A queued per-criterion outcome: True=pass, False=fail, "error"=raise.
Verdict = Union[bool, str]


class FakeJudge(DeepEvalBaseLLM):
    """Deterministic, offline stand-in for the deepeval judge model.

    Args:
        verdicts: ordered per-criterion outcomes, consumed in criteria order
            (requires ``evaluate_contract(..., max_workers=1)``). Each entry is
            ``True`` (pass), ``False`` (fail), or ``"error"`` (simulate a
            judge-call exception for that criterion).
        model_name: value returned by ``get_model_name``; set to ``None`` to
            exercise the ``EVAL_MODEL`` env fallback in scoring.
    """

    def __init__(self, verdicts: list[Verdict], model_name: Optional[str] = "fake-judge"):
        self._verdicts = list(verdicts)
        self._model_name = model_name
        self._score_index = 0

    # -- DeepEvalBaseLLM abstract methods ---------------------------------- #

    def load_model(self, *args, **kwargs):
        return None

    def get_model_name(self, *args, **kwargs):
        return self._model_name

    def generate(self, prompt, schema=None, *args, **kwargs) -> str:
        # GEval calls generate twice per criterion: first to build evaluation
        # steps (schema=Steps), then to score (schema=ReasonScore). We serve a
        # fixed steps response and consume the verdict queue on the score call.
        schema_name = getattr(schema, "__name__", None)
        if schema_name == "Steps":
            return json.dumps({"steps": ["evaluate the criterion against the contract"]})
        if schema_name == "ReasonScore":
            if self._score_index >= len(self._verdicts):
                raise RuntimeError("FakeJudge verdict queue exhausted")
            verdict = self._verdicts[self._score_index]
            self._score_index += 1
            if verdict == "error":
                raise RuntimeError("fake judge error for criterion")
            return json.dumps({"score": 1 if verdict else 0, "reason": "fake verdict"})
        # Unknown schema: permissive fallback (not expected in the scoring path).
        return json.dumps({"steps": [], "score": 0, "reason": "fake"})

    async def a_generate(self, prompt, schema=None, *args, **kwargs) -> str:
        return self.generate(prompt, schema=schema, *args, **kwargs)

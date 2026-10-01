"""Contract evaluation engine.

Mirrors harvey-labs' rubric evaluation methodology (one LLM-judge call per
criterion -> binary pass/fail -> all-pass scoring) but implemented on top of
deepeval's native GEval LLM-judge, applied to the contracts this crew drafts.

- judge.py   : the LLM judge (deepeval GPTModel pointed at the Ark endpoint)
- rubric.py  : load a rubric + criteria from db/evaluation_rules.db
- scoring.py : build one GEval(strict_mode=True) per criterion, run all-pass
- run.py     : CLI entry (`python -m src.eval.run`)
"""

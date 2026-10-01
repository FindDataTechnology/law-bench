"""LLM judge factory for contract evaluation.

harvey-labs uses a dedicated Judge LLM (claude-sonnet) that grades each rubric
criterion. Here we reuse deepeval's native OpenAI-compatible model (GPTModel) and
point it at the same OpenAI-compatible endpoint (Volcengine Ark) the drafting
crew already uses, so evaluation shares one network path and one credential.

Config (env):
- OPENAI_API_KEY / OPENAI_API_BASE : same as the crew (Ark endpoint)
- EVAL_MODEL        : model id, litellm-prefixed like the crew (e.g. openai/glm-5.2)
- EVAL_TEMPERATURE  : optional, default 0.0 (deterministic judge, as in harvey-labs)
"""

import os

from deepeval.models.llms import GPTModel


def _strip_litellm_prefix(model: str) -> str:
    """CrewAI/litellm prefix OpenAI-compatible models with `openai/`.

    deepeval's GPTModel passes the model name straight to the openai SDK, which
    does not understand the litellm prefix, so strip it (openai/glm-5.2 -> glm-5.2).
    """
    return model.split("/", 1)[1] if model.startswith("openai/") else model


def get_judge() -> GPTModel:
    """Build a deepeval GPTModel judge pointed at the project's Ark endpoint."""
    required = ["OPENAI_API_KEY", "OPENAI_API_BASE", "EVAL_MODEL"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            "Missing env vars for the evaluation judge: "
            + ", ".join(missing)
            + ". Copy .env.example -> .env and add EVAL_MODEL."
        )

    return GPTModel(
        model=_strip_litellm_prefix(os.environ["EVAL_MODEL"]),
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_API_BASE"],
        temperature=float(os.getenv("EVAL_TEMPERATURE", "0.0")),
    )

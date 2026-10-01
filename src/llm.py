"""
LLM factory: creates CrewAI LLM instance from environment variables per role.
Reads:
- {ROLE}_MODEL
- {ROLE}_TEMPERATURE (optional, default 0.2)
- {ROLE}_MAX_TOKENS (optional, default 4096)
Fails loudly if required variable is missing.
"""

import os

from crewai import LLM

from src.settings import ConfigError


def get_llm(role: str) -> LLM:
    """
    Get an LLM instance configured for the given role.

    Args:
        role: Role name in uppercase, e.g. "DRAFTER"

    Returns:
        Configured LLM instance

    Raises:
        ConfigError: If {ROLE}_MODEL is not set in environment
    """
    model = os.getenv(f"{role}_MODEL")
    if not model:
        raise ConfigError(
            f"{role}_MODEL is not set. Copy .env.example to .env and fill in the "
            f"model for the {role} role."
        )
    temperature = float(os.getenv(f"{role}_TEMPERATURE", "0.2"))
    max_tokens = int(os.getenv(f"{role}_MAX_TOKENS", "4096"))

    return LLM(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

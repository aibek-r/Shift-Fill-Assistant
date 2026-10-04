"""Application settings, loaded from environment variables and an optional `.env` file."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """All tunables in one place. Every field can be overridden with an env var of the same name."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_parse_none_str="none",
        extra="ignore",
    )

    # LLM
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.4-mini"
    openai_reasoning_effort: Literal["low", "medium", "high"] | None = Field(
        default="low", description="Set to 'none' for models without reasoning support."
    )
    llm_timeout_seconds: float = Field(
        default=60.0, gt=0, description="Per-call timeout, shortened to the budget left."
    )
    llm_max_retries: int = Field(
        default=3,
        ge=0,
        description="Retries for transient model errors, with backoff inside the model budget. "
        "SDK retries are disabled.",
    )

    # Agent budgets and guardrails
    max_agent_steps: int = Field(default=12, ge=1, description="Max LLM calls per request.")
    max_run_seconds: float = Field(
        default=180.0,
        gt=0,
        description="Model execution budget: one deadline from the start of the run for every "
        "model call, retry and backoff. Deterministic completion and fallback may run after it.",
    )
    max_repair_attempts: int = Field(default=2, ge=0, description="Max rejected submissions.")
    max_recommendations: int = Field(default=5, ge=1)
    tool_output_char_limit: int = Field(default=6000, ge=500)

    # Business rules
    expiry_warning_days: int = Field(default=30, ge=0)
    reference_date: date | None = Field(
        default=None, description="Pins 'today' for reproducible demos; defaults to the real date."
    )

    # Retrieval and data
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    retrieval_min_score: float = Field(
        default=0.5, ge=0, le=1, description="Drops weak policy matches (tuned for bge-small)."
    )
    data_dir: Path = PROJECT_ROOT / "data"
    cache_dir: Path = PROJECT_ROOT / ".cache"

    @property
    def today(self) -> date:
        return self.reference_date or date.today()

    @property
    def llm_enabled(self) -> bool:
        return self.openai_api_key is not None and bool(self.openai_api_key.get_secret_value())

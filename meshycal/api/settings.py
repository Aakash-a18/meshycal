"""Env-var settings for the api app.

Per CLAUDE.md rule 4: no hardcoded hosts, ports, or URLs. Default is
"works on a developer laptop"; production overrides via env.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MESHYCAL_", extra="ignore")

    cors_origins: list[str] = Field(
        default=["http://localhost:3000"],
        description="Origins the web renderer may call from. "
        "JSON list in env: MESHYCAL_CORS_ORIGINS='[\"https://meshycal.com\"]'.",
    )

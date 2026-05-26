"""Factory + label helpers for picking a reasoner from configuration."""

from __future__ import annotations

from meshycal.reasoners.anthropic import AnthropicReasoner
from meshycal.reasoners.base import SchedulingReasoner
from meshycal.reasoners.scripted import ScriptedReasoner


def build_reasoner(
    *,
    provider: str,
    model: str,
    api_key: str | None,
) -> SchedulingReasoner:
    """Pick the right reasoner for a principal's config.

    Falls back to ``ScriptedReasoner`` whenever the provider needs a key
    and none is available — the run still proceeds with the deterministic
    picker. A missing key shouldn't block the demo, it should just
    degrade gracefully.
    """
    if provider == "anthropic" and api_key:
        return AnthropicReasoner(api_key=api_key, model=model)
    # openai / openai-compatible would slot in here.
    return ScriptedReasoner()


def reasoner_label(*, provider: str, model: str, api_key: str | None) -> str:
    """Human-readable label the orchestrator can include in the
    RunResult so the UI can show "this run used claude-sonnet-4-6"."""
    if provider == "anthropic" and api_key:
        return f"anthropic · {model or AnthropicReasoner.DEFAULT_MODEL}"
    if provider == "anthropic":
        return "anthropic · scripted fallback (no api key)"
    return "scripted"

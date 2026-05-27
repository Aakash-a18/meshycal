"""Factory + label helpers for picking a reasoner from configuration.

The factory is the only place that knows the mapping
``provider string -> concrete class``. Everything upstream (sandbox runner,
session store, UI) speaks in (provider, model, base_url, api_key) tuples.

Fallback discipline: any reasoner that needs network credentials but is
missing one of (api_key, base_url, model) degrades to ScriptedReasoner.
A missing config shouldn't block the demo; it should run deterministically
and the UI's reasoner_label will say "fallback".
"""

from __future__ import annotations

from meshycal.reasoners.anthropic import AnthropicReasoner
from meshycal.reasoners.base import SchedulingReasoner
from meshycal.reasoners.openai_compatible import OpenAICompatibleReasoner
from meshycal.reasoners.scripted import ScriptedReasoner

_OPENAI_COMPAT_PROVIDERS = {"openai", "openai-compatible"}
_OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_OPENAI_DEFAULT_MODEL = "gpt-4o"


def build_reasoner(
    *,
    provider: str,
    model: str,
    api_key: str | None,
    base_url: str | None = None,
) -> SchedulingReasoner:
    """Pick the right reasoner for a principal's config.

    - ``"anthropic"`` + api_key -> AnthropicReasoner (native SDK)
    - ``"openai"`` / ``"openai-compatible"`` + api_key -> OpenAICompatibleReasoner.
      For ``"openai"`` we default base_url to api.openai.com/v1 and model
      to gpt-4o if either is unset. For ``"openai-compatible"`` both
      base_url and model must be explicit.
    - anything else, or missing credentials -> ScriptedReasoner

    Never raises on missing config; degrades silently to scripted.
    """
    if provider == "anthropic" and api_key:
        return AnthropicReasoner(api_key=api_key, model=model)

    if provider in _OPENAI_COMPAT_PROVIDERS and api_key:
        resolved_base = base_url or (
            _OPENAI_DEFAULT_BASE_URL if provider == "openai" else ""
        )
        resolved_model = model or (
            _OPENAI_DEFAULT_MODEL if provider == "openai" else ""
        )
        if resolved_base and resolved_model:
            return OpenAICompatibleReasoner(
                api_key=api_key,
                base_url=resolved_base,
                model=resolved_model,
            )

    return ScriptedReasoner()


def reasoner_label(
    *,
    provider: str,
    model: str,
    api_key: str | None,
    base_url: str | None = None,
) -> str:
    """Human-readable label the orchestrator can include in the
    RunResult so the UI can show "this run used claude-sonnet-4-6"."""
    if provider == "anthropic" and api_key:
        return f"anthropic · {model or AnthropicReasoner.DEFAULT_MODEL}"
    if provider == "anthropic":
        return "anthropic · scripted fallback (no api key)"

    if provider in _OPENAI_COMPAT_PROVIDERS and api_key:
        resolved_base = base_url or (
            _OPENAI_DEFAULT_BASE_URL if provider == "openai" else ""
        )
        resolved_model = model or (
            _OPENAI_DEFAULT_MODEL if provider == "openai" else ""
        )
        if resolved_base and resolved_model:
            return f"{provider} · {resolved_model}"
        return f"{provider} · scripted fallback (missing base_url or model)"
    if provider in _OPENAI_COMPAT_PROVIDERS:
        return f"{provider} · scripted fallback (no api key)"

    return "scripted"

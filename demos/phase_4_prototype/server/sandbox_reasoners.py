"""Sandbox reasoners — pluggable per-principal LLM (or scripted) brains.

The 2-party orchestrator calls ``evaluate_proposal()`` on the recipient's
reasoner to pick a slot. The 3-party orchestrator (Phase 2) will also
call the existing :class:`SchedulingReasoner` Protocol's
``propose_reschedule_target`` for the pivot.

Adding the new method on a fresh ``SandboxReasoner`` Protocol rather
than modifying the existing ``reasoner.py`` so the existing
Phase 3 scenarios (Iris/Marius/Atlas hard-coded) keep working
unchanged.

API key handling: the AnthropicReasoner takes the key in its
constructor (private attribute) and never logs it. The key is supplied
fresh per-run by the orchestrator reading from the session store; it is
not persisted anywhere except as a transient attribute on the reasoner
instance that lives for the duration of the run.

This module declines to do anything if the user has chosen
``provider="scripted"`` (the default) — the deterministic
ScriptedSandboxReasoner is used and no network call is made.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from .reasoner import CalendarEvent

logger = logging.getLogger(__name__)


# --- Verdict --------------------------------------------------------------


@dataclass(frozen=True)
class ProposalVerdict:
    """What a reasoner decides about an incoming proposal."""

    accept: bool
    chosen_slot: str | None
    reason: str


# --- Protocol -------------------------------------------------------------


class SandboxReasoner(Protocol):
    """Decides whether to accept a proposal and which slot to pick.

    Async because LLM-backed implementations make network calls. The
    scripted implementation is still ``async def`` so the protocol is
    uniform — callers always ``await`` it.
    """

    async def evaluate_proposal(
        self,
        *,
        candidate_slots: list[str],
        duration_minutes: int,
        my_calendar: list[CalendarEvent],
        my_display_name: str,
    ) -> ProposalVerdict:
        ...


# --- Scripted -------------------------------------------------------------


class ScriptedSandboxReasoner:
    """First-fit non-conflicting picker. Deterministic, no I/O."""

    async def evaluate_proposal(
        self,
        *,
        candidate_slots: list[str],
        duration_minutes: int,
        my_calendar: list[CalendarEvent],
        my_display_name: str,
    ) -> ProposalVerdict:
        # Build a set of occupied slot_start strings for quick lookup.
        # (Naive — doesn't consider duration overlap. Good enough for v0
        # where candidates are spaced out.)
        occupied = {ev.slot_start for ev in my_calendar}
        for candidate in candidate_slots:
            if candidate not in occupied:
                return ProposalVerdict(
                    accept=True,
                    chosen_slot=candidate,
                    reason=f"scripted first-fit: {candidate} is the first candidate clear of {my_display_name}'s calendar",
                )
        return ProposalVerdict(
            accept=False,
            chosen_slot=None,
            reason=f"scripted: all candidates conflict with {my_display_name}'s existing events",
        )


# --- Anthropic ------------------------------------------------------------


class AnthropicReasoner:
    """Asks Claude to pick a non-conflicting candidate via tool use.

    Constructor: ``api_key`` (required), ``model`` (defaults to
    ``claude-sonnet-4-6`` if empty).

    The api_key is stored as a private attribute and used only to
    construct the Anthropic client; it is never logged or returned.
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"
    TOOL_NAME = "pick_meeting_slot"

    def __init__(self, *, api_key: str, model: str = "") -> None:
        if not api_key:
            raise ValueError("AnthropicReasoner requires a non-empty api_key")
        # Defer import so the Anthropic SDK is only required when this
        # reasoner is actually used.
        try:
            from anthropic import AsyncAnthropic  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError(
                "The 'anthropic' package is not installed. "
                "Run `uv pip install anthropic` or pick a different provider."
            ) from e
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL

    async def evaluate_proposal(
        self,
        *,
        candidate_slots: list[str],
        duration_minutes: int,
        my_calendar: list[CalendarEvent],
        my_display_name: str,
    ) -> ProposalVerdict:
        prompt = self._build_prompt(
            candidate_slots=candidate_slots,
            duration_minutes=duration_minutes,
            my_calendar=my_calendar,
            my_display_name=my_display_name,
        )
        tool = {
            "name": self.TOOL_NAME,
            "description": (
                f"Pick a meeting slot for {my_display_name} from the candidates. "
                "Set accept=false if every candidate conflicts with their calendar."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "accept": {
                        "type": "boolean",
                        "description": "True if a non-conflicting candidate exists.",
                    },
                    "chosen_slot": {
                        "type": "string",
                        "description": (
                            "The ISO 8601 candidate picked. Must be one of the "
                            "exact strings in the CANDIDATES list. Empty string if accept=false."
                        ),
                    },
                    "reason": {
                        "type": "string",
                        "description": "One sentence explaining the pick.",
                    },
                },
                "required": ["accept", "chosen_slot", "reason"],
            },
        }

        try:
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                tools=[tool],
                tool_choice={"type": "tool", "name": self.TOOL_NAME},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            logger.warning(
                "AnthropicReasoner: API call failed (%s); falling back to scripted first-fit.",
                type(e).__name__,
            )
            return await ScriptedSandboxReasoner().evaluate_proposal(
                candidate_slots=candidate_slots,
                duration_minutes=duration_minutes,
                my_calendar=my_calendar,
                my_display_name=my_display_name,
            )

        # Extract the tool_use block.
        verdict = self._parse_tool_response(resp, candidate_slots)
        if verdict is not None:
            return verdict
        # Bad response shape — fall back.
        logger.warning("AnthropicReasoner: unexpected response shape; falling back to scripted.")
        return await ScriptedSandboxReasoner().evaluate_proposal(
            candidate_slots=candidate_slots,
            duration_minutes=duration_minutes,
            my_calendar=my_calendar,
            my_display_name=my_display_name,
        )

    # ---- helpers

    def _build_prompt(
        self,
        *,
        candidate_slots: list[str],
        duration_minutes: int,
        my_calendar: list[CalendarEvent],
        my_display_name: str,
    ) -> str:
        cal_lines = [
            f"- {ev.slot_start}  ({ev.duration_minutes} min)  {ev.title}"
            for ev in my_calendar
        ]
        cal_block = "\n".join(cal_lines) if cal_lines else "(no events)"
        cand_block = "\n".join(f"- {s}" for s in candidate_slots)
        return (
            f"You are {my_display_name}'s scheduling agent. A counterparty has proposed a "
            f"{duration_minutes}-minute meeting and offered these candidate slots:\n\n"
            f"CANDIDATES:\n{cand_block}\n\n"
            f"{my_display_name}'s EXISTING CALENDAR (ISO 8601 UTC):\n{cal_block}\n\n"
            "Pick the first candidate that does NOT overlap with any existing event on the "
            "calendar. If every candidate conflicts, set accept=false. Respond by calling the "
            f"`{self.TOOL_NAME}` tool.\n\n"
            "Hard rules:\n"
            "- chosen_slot must be one of the exact strings in CANDIDATES.\n"
            "- An overlap is any candidate that starts within an existing event's "
            f"[slot_start, slot_start + duration] window or vice-versa.\n"
            "- One-sentence reason; no preamble."
        )

    def _parse_tool_response(
        self,
        resp: Any,
        candidate_slots: list[str],
    ) -> ProposalVerdict | None:
        blocks = getattr(resp, "content", None) or []
        for block in blocks:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == self.TOOL_NAME:
                payload = getattr(block, "input", None)
                if not isinstance(payload, dict):
                    return None
                accept = bool(payload.get("accept", False))
                chosen = payload.get("chosen_slot") or None
                reason = str(payload.get("reason", "")).strip() or "claude declined to explain"
                # Guard against the model inventing a slot.
                if accept and chosen and chosen not in candidate_slots:
                    return ProposalVerdict(
                        accept=False,
                        chosen_slot=None,
                        reason=f"claude returned a slot ({chosen}) not in CANDIDATES; rejecting",
                    )
                return ProposalVerdict(
                    accept=accept and bool(chosen),
                    chosen_slot=chosen if accept else None,
                    reason=reason,
                )
        return None


# --- Factory --------------------------------------------------------------


def build_sandbox_reasoner(
    *,
    provider: str,
    model: str,
    api_key: str | None,
) -> SandboxReasoner:
    """Pick the right reasoner for a principal's config.

    Falls back to scripted whenever the provider needs a key and none is
    available — the run still proceeds, just with the deterministic
    picker. This is intentional: a missing key shouldn't block the demo,
    it should just degrade gracefully.
    """
    if provider == "anthropic" and api_key:
        return AnthropicReasoner(api_key=api_key, model=model)
    # openai / openai-compatible would slot in here in Phase 3.
    return ScriptedSandboxReasoner()


def reasoner_label(*, provider: str, model: str, api_key: str | None) -> str:
    """Human-readable label the orchestrator can include in the
    RunResult so the UI can show "this run used claude-sonnet-4-6"."""
    if provider == "anthropic" and api_key:
        return f"anthropic · {model or AnthropicReasoner.DEFAULT_MODEL}"
    if provider == "anthropic":
        return "anthropic · scripted fallback (no api key)"
    return "scripted"

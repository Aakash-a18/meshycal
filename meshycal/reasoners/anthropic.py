"""AnthropicReasoner — asks Claude to pick a non-conflicting candidate
via the Anthropic SDK's tool-use structured output.

The api_key is stored as a private attribute on an AsyncAnthropic client
instance. It is never logged or returned. The factory in
``meshycal.reasoners.factory`` falls back to the scripted reasoner when
no key is provided, so the call site can pass api_key=None safely.
"""

from __future__ import annotations

import logging
from typing import Any

from meshycal.calendar_object import CalendarObject
from meshycal.reasoners.base import ProposalVerdict
from meshycal.reasoners.scripted import ScriptedReasoner

logger = logging.getLogger(__name__)


class AnthropicReasoner:
    DEFAULT_MODEL = "claude-sonnet-4-6"
    TOOL_NAME = "pick_meeting_slot"

    def __init__(self, *, api_key: str, model: str = "") -> None:
        if not api_key:
            raise ValueError("AnthropicReasoner requires a non-empty api_key")
        try:
            from anthropic import AsyncAnthropic  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError(
                "The 'anthropic' package is not installed. "
                "Run `uv pip install anthropic` or pick a different provider."
            ) from e
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL
        self._fallback = ScriptedReasoner()

    async def evaluate_proposal(
        self,
        *,
        candidate_slots: list[str],
        duration_minutes: int,
        my_calendar: CalendarObject,
        my_display_name: str,
    ) -> ProposalVerdict:
        prompt = self._build_prompt(
            candidate_slots=candidate_slots,
            duration_minutes=duration_minutes,
            my_calendar=my_calendar,
            my_display_name=my_display_name,
        )
        tool: Any = {
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
                            "exact strings in the CANDIDATES list. Empty string "
                            "if accept=false."
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
                "AnthropicReasoner: API call failed (%s); falling back to scripted.",
                type(e).__name__,
            )
            return await self._fallback.evaluate_proposal(
                candidate_slots=candidate_slots,
                duration_minutes=duration_minutes,
                my_calendar=my_calendar,
                my_display_name=my_display_name,
            )

        verdict = self._parse_tool_response(resp, candidate_slots)
        if verdict is not None:
            return verdict
        logger.warning("AnthropicReasoner: unexpected response shape; falling back to scripted.")
        return await self._fallback.evaluate_proposal(
            candidate_slots=candidate_slots,
            duration_minutes=duration_minutes,
            my_calendar=my_calendar,
            my_display_name=my_display_name,
        )

    # --- helpers ------------------------------------------------------

    def _build_prompt(
        self,
        *,
        candidate_slots: list[str],
        duration_minutes: int,
        my_calendar: CalendarObject,
        my_display_name: str,
    ) -> str:
        cal_lines = [
            f"- {e.time}  ({e.duration} min)  {e.title or '(untitled)'}"
            for e in my_calendar.events
        ]
        cal_block = "\n".join(cal_lines) if cal_lines else "(no events)"
        cand_block = "\n".join(f"- {s}" for s in candidate_slots)
        return (
            f"You are {my_display_name}'s scheduling agent. A counterparty has proposed a "
            f"{duration_minutes}-minute meeting and offered these candidate slots:\n\n"
            f"CANDIDATES:\n{cand_block}\n\n"
            f"{my_display_name}'s EXISTING CALENDAR (local time of each event):\n{cal_block}\n\n"
            "Pick the first candidate that does NOT overlap with any existing event on the "
            "calendar. If every candidate conflicts, set accept=false. Respond by calling "
            f"the `{self.TOOL_NAME}` tool.\n\n"
            "Hard rules:\n"
            "- chosen_slot must be one of the exact strings in CANDIDATES.\n"
            "- An overlap is any candidate that starts within an existing event's "
            "[slot_start, slot_start + duration] window or vice-versa.\n"
            "- One-sentence reason; no preamble."
        )

    def _parse_tool_response(
        self,
        resp: Any,
        candidate_slots: list[str],
    ) -> ProposalVerdict | None:
        blocks = getattr(resp, "content", None) or []
        for block in blocks:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == self.TOOL_NAME
            ):
                payload = getattr(block, "input", None)
                if not isinstance(payload, dict):
                    return None
                accept = bool(payload.get("accept", False))
                chosen = payload.get("chosen_slot") or None
                reason = str(payload.get("reason", "")).strip() or "claude declined to explain"
                if accept and chosen and chosen not in candidate_slots:
                    return ProposalVerdict(
                        accept=False,
                        chosen_slot=None,
                        reason=(
                            f"claude returned a slot ({chosen}) not in CANDIDATES; "
                            "rejecting"
                        ),
                    )
                return ProposalVerdict(
                    accept=accept and bool(chosen),
                    chosen_slot=chosen if accept else None,
                    reason=reason,
                )
        return None

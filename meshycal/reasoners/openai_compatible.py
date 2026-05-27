"""OpenAICompatibleReasoner — talks to anything that speaks the OpenAI
``/v1/chat/completions`` shape: OpenAI itself, Groq, Together, OpenRouter,
Mistral, Anthropic's compatibility endpoint, Google's Gemini compatibility
endpoint, Ollama, LM Studio, vLLM, llama.cpp's server.

The user supplies (provider name, base_url, model, api_key). The reasoner
uses tool-call structured output mirroring the AnthropicReasoner's
``pick_meeting_slot`` tool so the verdict is the same shape on both sides.

The api_key is held on this object only for the lifetime of one run. It is
sent in the ``Authorization: Bearer`` header to the configured base_url
and to nowhere else, and is never logged. The factory in
``meshycal.reasoners.factory`` falls back to the scripted reasoner when
no key (or no base_url) is provided.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from meshycal.calendar_object import CalendarObject
from meshycal.reasoners.base import ProposalVerdict
from meshycal.reasoners.scripted import ScriptedReasoner

logger = logging.getLogger(__name__)


class OpenAICompatibleReasoner:
    TOOL_NAME = "pick_meeting_slot"
    DEFAULT_TIMEOUT = 30.0  # seconds

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAICompatibleReasoner requires a non-empty api_key")
        if not base_url:
            raise ValueError("OpenAICompatibleReasoner requires a non-empty base_url")
        if not model:
            raise ValueError("OpenAICompatibleReasoner requires a non-empty model")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
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
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [self._tool_schema(my_display_name)],
            "tool_choice": {
                "type": "function",
                "function": {"name": self.TOOL_NAME},
            },
            "max_tokens": 512,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        endpoint = f"{self._base_url}/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
                resp = await client.post(endpoint, json=body, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            logger.warning(
                "OpenAICompatibleReasoner: HTTP call failed (%s); falling back to scripted.",
                type(e).__name__,
            )
            return await self._fallback.evaluate_proposal(
                candidate_slots=candidate_slots,
                duration_minutes=duration_minutes,
                my_calendar=my_calendar,
                my_display_name=my_display_name,
            )

        verdict = self._parse_tool_response(payload, candidate_slots)
        if verdict is not None:
            return verdict
        logger.warning(
            "OpenAICompatibleReasoner: unexpected response shape; falling back to scripted."
        )
        return await self._fallback.evaluate_proposal(
            candidate_slots=candidate_slots,
            duration_minutes=duration_minutes,
            my_calendar=my_calendar,
            my_display_name=my_display_name,
        )

    # --- helpers ------------------------------------------------------

    def _tool_schema(self, my_display_name: str) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.TOOL_NAME,
                "description": (
                    f"Pick a meeting slot for {my_display_name} from the candidates. "
                    "Set accept=false if every candidate conflicts with their calendar."
                ),
                "parameters": {
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
            },
        }

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
        payload: Any,
        candidate_slots: list[str],
    ) -> ProposalVerdict | None:
        """Parse an OpenAI-style chat completion response with tool calls.

        Expected shape:
          { "choices": [ { "message": {
              "tool_calls": [ { "function": { "name": ..., "arguments": "<json str>" } } ]
          } } ] }
        """
        try:
            choices = payload.get("choices") or []
            if not choices:
                return None
            message = choices[0].get("message") or {}
            tool_calls = message.get("tool_calls") or []
            for call in tool_calls:
                function = call.get("function") or {}
                if function.get("name") != self.TOOL_NAME:
                    continue
                args_raw = function.get("arguments")
                if not isinstance(args_raw, str):
                    return None
                try:
                    args = json.loads(args_raw)
                except json.JSONDecodeError:
                    return None
                if not isinstance(args, dict):
                    return None
                accept = bool(args.get("accept", False))
                chosen = args.get("chosen_slot") or None
                reason = (
                    str(args.get("reason", "")).strip()
                    or f"{self._model} declined to explain"
                )
                if accept and chosen and chosen not in candidate_slots:
                    return ProposalVerdict(
                        accept=False,
                        chosen_slot=None,
                        reason=(
                            f"{self._model} returned a slot ({chosen}) not in "
                            "CANDIDATES; rejecting"
                        ),
                    )
                return ProposalVerdict(
                    accept=accept and bool(chosen),
                    chosen_slot=chosen if accept else None,
                    reason=reason,
                )
        except (AttributeError, IndexError, TypeError):
            return None
        return None

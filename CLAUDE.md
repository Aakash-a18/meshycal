# MeshyCal

The first Delegation built on Mesherra. Scheduling, agent-mediated, privacy-preserving.

The architecture is the source of truth. This file is orientation only — keep it short.

## What MeshyCal is

A **Delegation** packaging four parts that slot into a user's Mesherra stack at four different primitive levels:

1. **Object class definitions** — CalendarObject, MeetingObject, Proposal payload schema
2. **A SchedulingAgent** — domain agent that runs under each user's butler; reads the CalendarObject, exchanges Proposals, creates MeetingObjects
3. **Policy templates** — default outbound/inbound rules the user can override; merges into the user's signed PolicyDoc
4. **A UI manifest + renderer** — `delegation.json` declares the install bundle; the renderer is disposable per host surface

Full spec: `docs/ARCHITECTURE.md`.

## Vocabulary

For Mesherra primitives (Agent, Object, Layer, Promotion, Handshake, Policy, Residue, Butler, Delegation), see `../mesherra/CLAUDE.md`. Do not redefine.

MeshyCal-specific terms:

- **CalendarObject** — the user's calendar as a Mesherra-aligned Object. Owner-bound, lives in Personal layer, never crosses the wire.
- **MeetingObject** — the canonical agreement produced by a successful negotiation. Single owner (the initiator), live-reference-promoted to the counterpart. Both sides relate to the same canonical Object.
- **Proposal** — wire payload conforming to `meshycal.scheduling/proposal-v1`. Not an Object; a structured payload inside a SendClaim envelope.
- **SchedulingAgent** — the MeshyCal domain agent. One per user per install.
- **Reasoner** — pluggable backend (Anthropic / OpenAI / scripted) that turns a Proposal + CalendarObject into a verdict. MeshyCal-internal; not a Delegation Authoring SDK pattern.

## Build discipline

1. **Depend on Mesherra; never reverse.** MeshyCal imports the Mesherra SDK. Mesherra never imports MeshyCal.
2. **Use Mesherra primitives, do not reinvent.** Identity, scoped disclosure, provenance, signing, replay defense — always call into Mesherra.
3. **No real user data, ever.** Synthetic only — names, calendars, emails, events. Hard rule. Git history is forever.
4. **No hardcoded values.** Paths, hosts, ports, keys, principal IDs — all via environment. Required vars in `.env.example`. Fail fast on missing.
5. **Domain logic lives here, not in Mesherra.** Calendar reading, slot proposal logic, calendar-integration adapters, UI surfaces — all on this side of the line.
6. **CalendarObject never crosses the wire.** Only derivatives (Proposals, MeetingObject scoped views) cross. If a feature requires sending the calendar, the design is wrong.
7. **MeetingObject has one canonical owner.** Mesherra's current architecture is single-owner for Objects. Do not invent multi-writer semantics in MeshyCal.
8. **The SchedulingAgent never bypasses the airlock.** Outbound via `Mesherra.send_to()`; inbound via the registered callback. No direct A2A calls.
9. **Don't abstract MeshyCal prematurely.** This is the first Delegation, hand-crafted against the raw SDK. Resist extracting "reusable Delegation helpers" before a second Delegation exists. The Reasoner factory is internal; it does not graduate to a shared utility until Delegation #2 needs the same shape unprompted. See `docs/ARCHITECTURE.md` §10 rule 4.

## Where to read

- `docs/ARCHITECTURE.md` — full MeshyCal spec, Object classes, layer semantics, negotiation flow, open questions
- `docs/ROADMAP.md` — what's next and in what order; 5 milestones from "show me the AI" to "launchable product"
- `../mesherra/docs/ARCHITECTURE.md` — Mesherra primitive specifications MeshyCal builds on
- `../mesherra/docs/STRATEGY.md` — strategic framing; §5 covers MeshyCal as reference implementation, not as scheduling product

## Current status

The MeshyCal package (`meshycal/`) implements CalendarObject, MeetingObject, SchedulingAgent, policy template, and reasoners against the Mesherra SDK. The full §8 negotiation works end-to-end: PROPOSAL exchange → ACCEPTANCE → owner-side MeetingObject creation → LIVE promotion to counterpart → counterpart subscribes and fetches initial state → both calendars hold the booking. Verified by `meshycal/tests/test_meeting_object_roundtrip.py` against real HTTP listeners.

Lagging the target architecture: `delegation.json` manifest, Schema Registry wiring, invitee identity flow, Google Calendar adapter. See `docs/ARCHITECTURE.md` §11 for the gap table. The MeetingObject keystone gap is closed.

The `demos/` directory contains scaffolding from earlier development. It is not the organizing structure for MeshyCal — the Delegation contract in `docs/ARCHITECTURE.md` §2 is. Demos will be re-homed (Phase 1 → `tests/e2e/`; Phase 4 prototype → out-of-tree) as the production package matures. The sandbox runner's in-process simulation opts into the `SchedulingAgent(single_process_mode=True)` fallback that books locally without LIVE promotion (no HTTP listener available); production callers leave the flag default-False and start a listener.

## Web renderer (skeleton)

The first realization of Delegation rule 4 ("UI manifest + renderer") lives in two new directories:

- `meshycal/api/` — FastAPI app exposing a renderer-facing HTTP surface (`/api/meetings` list/detail, POST submit). Skeleton state returns synthetic data from `_fixtures.py`; step 4 swaps it for an adapter over per-principal `SchedulingAgent` + `ProvenanceLedger` + `ObjectStore`. CORS origins via `MESHYCAL_CORS_ORIGINS` (defaults to `http://localhost:3000`).
- `web/` — Next.js 15 + Tailwind App Router app. Renders the inbox (list), receipt detail view, and "new meeting" form. Talks to `meshycal/api/` at `NEXT_PUBLIC_MESHYCAL_API_URL` (defaults to `http://localhost:8000`). Server components for read endpoints; client component for the form.

The renderer is "disposable per host surface" (CLAUDE.md rule 4): the Next.js app is the **web** surface. Future surfaces (Slack card, email card, iOS app) would each ship their own renderer against the same `meshycal/api/` shapes.

### Running locally

```
# Terminal 1 — backend (port 8000). Use the venv-local uvicorn so you
# don't need to activate the venv first.
.venv/bin/uvicorn meshycal.api:create_app --factory --reload --port 8000

# Terminal 2 — frontend (port 3000, falls back to 3001 if taken)
cd web && npm install   # first run only
cd web && npm run dev
```

Then open whichever URL Next.js prints (`http://localhost:3000/inbox` or `:3001/inbox`). Three synthetic cards (pending / accepted / declined) are seeded; submit one through the form and it appears with status `pending` in the in-memory inbox.

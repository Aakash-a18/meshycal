# MeshyCal

The first Delegation built on Tesherra. Scheduling, agent-mediated, privacy-preserving.

## What MeshyCal is

A **Delegation** packaging:

1. **Object class definitions** — Calendar, Meeting, Proposal (schemas registered in Tesherra's Schema Registry)
2. **A scheduling Agent** — domain agent that runs under each user's butler; reads calendars, proposes slots, evaluates counter-proposals
3. **Policy templates** — sensible defaults for safe scheduling (e.g., "share candidate slots, never share titles or attendees")
4. **A mobile / web UI** — user-facing renderer

When installed, each piece slots into a user's Tesherra stack at a different primitive level. See `../tesherra/docs/ARCHITECTURE.md` section 10.

## Vocabulary

For Tesherra primitives (Agent, Object, Layer, Promotion, Handshake, Policy, Residue, Butler, Delegation), see `../tesherra/CLAUDE.md`. Do not redefine.

MeshyCal-specific terms:

- **Calendar Object** — an instance of the Calendar Object class. Owned by a single user; lives in their personal layer by default.
- **Meeting Object** — an instance of the Meeting Object class. Produced as the output of a successful negotiation; co-owned conceptually but with one canonical owner per the architecture.
- **Proposal** — a payload conforming to `meshycal.scheduling/proposal-v1`. The wire format for slot suggestions between scheduling agents.
- **Scheduling Agent** — the MeshyCal domain agent. Runs under each user's butler. One per user per MeshyCal install.

## Build discipline

1. **Depend on Tesherra; never reverse.** MeshyCal imports the tesherra SDK. Tesherra never imports MeshyCal.
2. **Use Tesherra primitives, do not reinvent.** Identity, scoped disclosure, provenance, signing — always call into Tesherra. Never reimplement.
3. **No real user data, ever.** Same rule as Tesherra (see ../tesherra/CLAUDE.md). Synthetic calendar entries only. This is non-negotiable; git history is forever.
4. **No hardcoded values.** Same env-var discipline as Tesherra. Required vars documented in `.env.example`; fail fast at startup.
5. **Domain logic lives here, not in Tesherra.** Calendar reading, slot proposal logic, OAuth integrations, UI — all on this side of the line.
6. **Stack is not yet committed.** Mobile / web likely TypeScript; agent code likely Python (matches Tesherra SDK). Defer specifics to Phase 1 design.
7. **Don't abstract MeshyCal prematurely.** MeshyCal is the first Delegation, hand-crafted against Tesherra's raw SDK. Resist the urge to extract "reusable Delegation helpers" from this codebase before a second Delegation exists. Two examples is the minimum from which useful templates can be derived; one is just a special case in disguise. If you find yourself writing code "so future Delegations can reuse it," stop — that code belongs in a separate Delegation Authoring SDK that doesn't exist yet, and it shouldn't exist until Delegation #2 forces real patterns to emerge. See `../tesherra/docs/ARCHITECTURE.md` section 12 item 10.

## Status & build order

Pre-alpha. Documentation-first. No production code yet.

Phase 1 of Tesherra ships provenance (per `../tesherra/docs/ARCHITECTURE.md` section 12). MeshyCal's first deliverable is the corresponding demo: two scheduling agents on localhost, hardcoded identities, deterministic slot picking (no LLM), exchanging signed proposals and producing matching residue entries.

Subsequent MeshyCal work tracks Tesherra's build order:
- Phase 1 (Tesherra provenance) → MeshyCal localhost two-agent demo
- Phase 2 (Tesherra identity) → MeshyCal cross-machine with verified principals
- Phase 3 (Tesherra scoped disclosure) → MeshyCal with the actual product punch (field-level policy stripping calendar titles)

The invitee experience (frictionless guest principal for the second user) is the hardest MeshyCal problem and is deferred to Phase 1.5 per Tesherra's open design questions.

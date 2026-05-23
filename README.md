# MeshyCal

> Two users' AI agents negotiate a meeting time. Neither calendar crosses the wire. The result is a signed, verifiable record of what was agreed.

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-pre--alpha-orange.svg)](#status)
[![Built on Tesherra](https://img.shields.io/badge/built%20on-Tesherra-purple.svg)](https://github.com/Aakash-a18/tesherra)

---

## What this actually is

MeshyCal looks like a scheduling app. It is technically a **Delegation** — the agent-era unit of application, a package built on the [Tesherra](https://github.com/Aakash-a18/tesherra) trust layer.

When you install MeshyCal, four things slot into your AI agent stack:

| Component | What it is | Where it lives |
|---|---|---|
| **Object class definitions** | JSON Schemas for Calendar, Meeting, and Proposal | Registered in Tesherra's Schema Registry |
| **A scheduling Agent** | Domain logic: reads your calendar privately, proposes candidate slots, evaluates incoming counter-proposals | Spawned under your butler agent |
| **Policy templates** | Safe defaults — share candidate slots, never share titles, never share attendee identities | Merged into your signed policy on install |
| **A mobile / web UI** | The user-facing surface for set-points, exceptions, and confirmations | On your device |

Your agent installs the Delegation; the Delegation does the work; you never operate a calendar app again unless you want to.

## How a meeting actually happens

```
You:           "Schedule 30 min with Maya this week"

Your agent:    [reads your calendar privately]
               [picks 3 candidate open slots]
               [sends ONLY the candidate slots — not the calendar —
                to Maya's agent, signed and scoped]

Maya's agent:  [verifies the sender is genuinely you]
               [checks the candidate slots against Maya's calendar privately]
               [picks one slot, or counter-proposes]

Your agent:    [confirms]

Both agents:   [sign the agreed slot]
               [write attested provenance entries to their respective ledgers]

Both apps:     Calendar event appears. Verifiable record exists on both sides.
```

What **never** crossed the wire: your titles, attendees, location, prior meetings, free/busy patterns outside the candidate window, or anything not explicitly in the proposal payload.

What both sides hold afterward: a tamper-evident signed record of the agreement, with matching byte-equal payload hashes. If anyone disputes the meeting later, the residue is the receipt.

## Why this exists

Scheduling is the smallest possible negotiation that exercises every piece of the Tesherra trust layer:

- **Identity** — you want to know it's actually Maya's agent, not someone impersonating her
- **Scoped disclosure** — you want only candidate slots crossing the boundary, not your calendar
- **Provenance** — you want a verifiable record of what was agreed, for the inevitable dispute

If trust infrastructure can make scheduling private and verifiable, it can do the same for contracts, procurement, regulated coordination, and everything else where two parties' agents need to interact.

**MeshyCal is the test rig. Not the market.** The market for Tesherra-class infrastructure is high-stakes B2B: contracts, transactions, regulated coordination. MeshyCal proves the mechanism in the smallest domain so the harder domains are accessible later.

## Relationship to Tesherra

```
MeshyCal  ──depends on──▶  Tesherra
```

One way. Tesherra is the domain-agnostic trust substrate; MeshyCal is the first domain-specific consumer.

- Tesherra never imports MeshyCal.
- MeshyCal's domain logic (calendar reading, slot proposing, OAuth integrations, UI) lives here, not in Tesherra.
- MeshyCal calls into Tesherra's SDK for everything trust-related (signing, scoped disclosure, provenance). Never reimplements.

This separation is what lets a second Delegation (a Contract Negotiator, a Procurement Pro, etc.) plug into the same Tesherra trust layer without conflict — and what eventually enables a Delegation marketplace.

## What's in this repo today

- [`README.md`](README.md) — this file
- [`CLAUDE.md`](CLAUDE.md) — orientation for any AI coding session entering the repo (vocabulary, build discipline, build order)
- [`.env.example`](.env.example) — configuration template (no hardcoded values anywhere; required vars documented)
- [`.gitignore`](.gitignore) — no secrets, no real user data, ever
- [`LICENSE`](LICENSE) — Apache 2.0

**No production code yet.** The Phase 1 demo is specified in the Tesherra repo: [`demos/phase_1/SPEC.md`](https://github.com/Aakash-a18/tesherra/blob/main/demos/phase_1/SPEC.md). MeshyCal's Phase 1 deliverables are the two scheduling agents that exercise that spec on localhost.

## The bundled experience, step by step

1. User 1 tells the MeshyCal app: "schedule 30 min with User 2 this week."
2. User 1's butler dispatches to its MeshyCal scheduling Agent.
3. The scheduling agent reads User 1's calendar privately and computes candidate slots.
4. The proposal crosses the Tesherra airlock — signed, scoped, identity-verified — onto the A2A wire.
5. User 2's airlock verifies and accepts; User 2's MeshyCal scheduling Agent picks a slot against User 2's private calendar.
6. The agreed slot returns; both airlocks attach signed provenance; both apps drop the event into the users' calendars.

Neither user's calendar ever crosses the boundary. Only candidate slots and the agreed time.

## Stack (planned, not yet committed)

- **Mobile / web UI** — likely TypeScript with React Native or equivalent
- **Scheduling Agent** — likely Python (matches the Tesherra Python SDK)
- Hybrid is fine; specific choices deferred to Phase 1 design

## Read first

- [`CLAUDE.md`](CLAUDE.md) — this repo's vocabulary, build discipline, and Phase 1 plan
- [`../tesherra/CLAUDE.md`](https://github.com/Aakash-a18/tesherra/blob/main/CLAUDE.md) — Tesherra vocabulary (Delegation, Object, Agent, Promotion, Residue, etc.)
- [`../tesherra/docs/ARCHITECTURE.md`](https://github.com/Aakash-a18/tesherra/blob/main/docs/ARCHITECTURE.md) — the trust layer this Delegation runs on (especially section 10 for the Delegation integration contract)
- [`../tesherra/docs/STRATEGY.md`](https://github.com/Aakash-a18/tesherra/blob/main/docs/STRATEGY.md) — strategic positioning (MeshyCal as first published Delegation, test rig vs. market)

## Build discipline

1. **Depend on Tesherra; never reverse.** MeshyCal imports the Tesherra SDK. Tesherra never imports MeshyCal.
2. **Use Tesherra primitives, never reinvent.** Identity, scoped disclosure, provenance, signing — always call into Tesherra.
3. **No real user data, ever.** Synthetic calendars only. Hard rule; git history is forever.
4. **No hardcoded values.** All configuration via env vars, documented in `.env.example`. Fail fast at startup if required vars are missing.
5. **Domain logic lives here, not in Tesherra.** Calendar reading, slot proposal logic, OAuth integrations, UI — all on this side of the line.
6. **Stack not yet committed.** Mobile/web likely TypeScript; agent code likely Python. Defer specifics to Phase 1 design.
7. **Don't abstract MeshyCal prematurely.** If you find yourself writing code "so future Delegations can reuse it," stop. That code belongs in a separate Delegation Authoring SDK that doesn't exist yet, and it shouldn't exist until Delegation #2 forces real patterns to emerge.

## Status

Pre-alpha. Documentation-only.

**Phase 1 plan:** two scheduling agents on localhost, hardcoded identities, deterministic slot picking (no LLM), exchanging signed proposals and producing matching residue entries. Tracks Tesherra Phase 1 (provenance vertical slice).

**Phase 2:** cross-machine demo with verified principals (tracks Tesherra Phase 2 / identity verification).

**Phase 3:** the actual product punch — field-level policy stripping calendar titles, attendees, anything sensitive (tracks Tesherra Phase 3 / scoped disclosure).

**Phase 1.5:** the invitee experience — frictionless guest principal for the second user. This is the hardest MeshyCal product problem (beating Calendly's one-sided-link cold-start). Deferred until Tesherra's guest-principal primitive lands.

## Contributing

Pre-alpha. Contribution guidelines will come once Phase 1 ships. Until then: issues and questions welcome; PRs probably premature.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).

Copyright © 2026 Aakash Agrawal.

# MeshyCal

The first Delegation built on Tesherra. Two users' AI agents negotiate a meeting time without exposing either calendar, producing a signed attested record.

**Status:** pre-alpha. Documentation-first. No production code yet.

## What this is

MeshyCal is not a scheduling app. It is a **Delegation** — a published package that uses Tesherra primitives to deliver scheduling-as-a-service that the user *grants authority to*, rather than *operates*.

The Delegation packages four components, each of which slots into a different primitive in the user's Tesherra stack at install time:

| Component | What it is | Where it slots in |
|---|---|---|
| Calendar / Meeting / Proposal **Object class definitions** | JSON schemas + canonical IDs | Schema Registry |
| **Scheduling Agent** | Domain agent: reads calendar, proposes slots, evaluates proposals | Spawned under each user's butler |
| **Policy templates** | Defaults like "share candidate slots, never share titles" | Merged into the user's signed Policy on install |
| **Mobile / web UI** | User-facing renderer for set-points, exceptions, confirmations | Loaded on the user's device |

See `../tesherra/docs/ARCHITECTURE.md` section 10 for the architectural placement; `../tesherra/docs/STRATEGY.md` section 5 for the strategic positioning.

## Relationship to Tesherra

MeshyCal depends on Tesherra. The dependency arrow runs one way:

```
MeshyCal  ──depends on──▶  Tesherra
```

Never reverse. Tesherra is domain-agnostic and knows nothing about scheduling, calendars, or meetings. All domain logic lives in this repo.

## The bundled experience

When two MeshyCal users meet, what actually happens:

1. User 1 tells the MeshyCal app: "schedule 30 min with User 2 this week."
2. User 1's butler dispatches to its MeshyCal scheduling Agent.
3. The scheduling agent reads User 1's calendar privately and computes candidate slots.
4. The proposal crosses the Tesherra airlock (signed, scoped, identity-verified) onto the A2A wire.
5. User 2's airlock verifies and accepts; User 2's MeshyCal scheduling Agent picks a slot against User 2's private calendar.
6. The agreed slot returns, both airlocks attach signed provenance, both apps drop the event into the users' real calendars.

Neither user's calendar ever crosses the boundary. Only candidate slots and the agreed time.

## Stack (planned, not yet committed)

- **Mobile / web UI**: likely TypeScript + a mobile framework (React Native or equivalent)
- **Scheduling Agent**: likely Python (to match Tesherra's Python SDK)
- Hybrid is fine; specific choices deferred to the Phase 1 demo design

## Read first

- `CLAUDE.md` — orientation for any AI coding session entering this repo
- `../tesherra/CLAUDE.md` — Tesherra vocabulary (Delegation, Object, Agent, etc.)
- `../tesherra/docs/ARCHITECTURE.md` — the trust layer this Delegation runs on
- `../tesherra/docs/STRATEGY.md` — strategic context (MeshyCal as first published Delegation)

## License

TBD.

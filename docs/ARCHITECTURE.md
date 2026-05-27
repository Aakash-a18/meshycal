# MeshyCal Architecture

This document describes MeshyCal as the first Delegation built on Mesherra. It is forward-looking: it describes the system MeshyCal is being built to be. Sections marked **Status** call out where the current code lags the target.

Authority on Mesherra primitives (Agent, Object, Layer, Promotion, Handshake, Policy, Residue, Butler, Delegation) lives in `../../mesherra/docs/ARCHITECTURE.md`. This document does not redefine those terms; it describes how MeshyCal *uses* them.

---

## 1. What MeshyCal is

MeshyCal is a **Delegation** for scheduling. Two users with MeshyCal installed under their respective butlers can coordinate a meeting time without exposing either calendar, producing a signed, tamper-evident record of what was agreed.

MeshyCal is not a scheduling product competing with Calendly. It is the canonical reference implementation of the Delegation pattern on Mesherra. Its job is to:

1. Prove the Mesherra trust layer works end-to-end across all three pieces (identity, scoped disclosure, provenance) in a domain humans understand.
2. Establish the four-part Delegation shape (Object classes + Agent + Policy template + UI manifest) so the second Delegation has a template to deviate from.
3. Pressure-test Mesherra's public SDK by being its first real consumer.

MeshyCal succeeds strategically when it makes the *second* Delegation feel obvious to build. It does not succeed by capturing the scheduling market.

---

## 2. The Delegation contract

A Delegation is a published bundle that grants the user's butler authority over one domain of their life. MeshyCal packages the four parts:

| Part | What it is in MeshyCal | File / module |
|---|---|---|
| **Object class definitions** | CalendarObject, MeetingObject, Proposal payload schema | `meshycal/calendar_object.py`, `meshycal/meeting_object.py` *(target)*, `schemas/` |
| **Agent code** | SchedulingAgent — the domain agent that runs under the butler | `meshycal/scheduling_agent.py` |
| **Policy templates** | Default rules for what may be shared and accepted | `meshycal/policy_template.py` |
| **UI manifest + renderer** | `delegation.json` + (eventually) a thin renderer | *(not yet shipped)* |

When a user installs MeshyCal, each part slots into their stack at a different level:

- Object classes register in Mesherra's Schema Registry under the publisher's principal
- The SchedulingAgent spawns as a sub-agent under the user's butler
- The policy template merges into the user's signed PolicyDoc (user-editable; defaults are starting points, not commitments)
- The UI manifest tells any host surface (web, mobile, voice, AR) how to render MeshyCal's view if a user opens it directly

The manifest is what turns the Python package into something a butler can install. Until `delegation.json` exists, MeshyCal is a library a developer can use, not a Delegation a butler can grant authority to. See §11 (Status).

---

## 3. Object classes

### 3.1 CalendarObject

The user's calendar as a Mesherra-aligned owner-bound Object.

- **Owner**: one principal — the user
- **Home layer**: Personal (visible only to the owner's own agents by default)
- **Mutability**: live (events get added and removed continuously)
- **Multiplicity**: singular (per Mesherra §3.2)
- **Canonical hash**: `SHA-256(JCS(events + timezone + version))` — the snapshot proof the SchedulingAgent attests to when it sends a Proposal ("this is what my calendar said at version N")
- **Read API**: `free_slots()`, `is_busy_at()`, `busy_intervals_on()` — the agent's read surface for building Proposals
- **Write API**: `book()`, `remove_event()` — both bump the version counter so the canonical hash changes

**What CalendarObject is *not*:** it is not promoted across the boundary. It never leaves the owner's stack. The wire only ever sees *derivatives* — Proposals containing candidate slots, never the underlying calendar. This is the disclosure invariant the entire scheme depends on.

### 3.2 MeetingObject

The result of a successful negotiation. The canonical "agreement" that both sides relate to.

Per Mesherra §3.2 ("Multiplicity: singular — co-ownership deferred to v1+"), MeetingObject has **a single canonical owner**: the initiator of the negotiation. In the rare edge case where both parties initiate simultaneously, the owner is determined by the lexicographically smaller `principal_id` of the two participants (deterministic tiebreaker; see §12 open question 9). Both parties experience it as a shared meeting through the following mechanism:

- The owner's stack holds the canonical MeetingObject in their Personal layer at creation
- Immediately on acceptance, the owner **promotes a live reference** of the MeetingObject into a Shared layer membership for the counterpart
- Both sides query/observe the same canonical state through their respective views
- Updates by the owner (location change, reschedule) propagate to the counterpart via Mesherra's live-reference push pattern (A2A `SubscribeToTask`)
- The counterpart cannot mutate the MeetingObject directly; proposed changes are sent as a new Proposal that, if accepted, become an owner-issued update

This gives users the **experience** of a co-owned meeting without breaking Mesherra's owner-is-canonical commitment. There is one canonical state. Conflict resolution is not needed because there is only one writer.

**MeetingObject fields (target):**

- `meeting_id` — stable Promotion ID assigned at creation
- `owner` — initiator's principal
- `counterpart` — accepting party's principal
- `time`, `duration_minutes`, `timezone`
- `title`, `location` *(scoped per-viewer per policy — see §4)*
- `attendees` *(scoped per-viewer per policy)*
- `agreement_hash` — content hash of the agreed Proposal that produced this Meeting
- `provenance_pointer` — anchor to the negotiation's Residue chain

**Status:** MeetingObject is implemented and wired through the SchedulingAgent. On a successful negotiation the initiator creates the MeetingObject as a real Mesherra Object (`mutability=LIVE`) and live-reference-promotes it to the counterpart; the counterpart subscribes and fetches the initial state via the trust layer. There is one canonical agreement state on the initiator's side; the counterpart's view is a Mesherra-scoped projection of that state. The keystone §11 gap is closed. End-to-end verified by `meshycal/tests/test_meeting_object_roundtrip.py`.

Reschedule and cancellation flows (updates the owner pushes after the meeting exists) are wired at the trust-layer level — `Mesherra.update_object` fan-out pushes to subscribers — but the SchedulingAgent's UX-side handling of update pushes is currently a no-op stub (§12 open question 7).

### 3.3 Proposal (wire payload, not an Object)

A Proposal is the on-wire payload format scheduling agents exchange during negotiation. It is **not** a Mesherra Object — it has no owner, layer, lifecycle, or residue of its own. It is a structured payload that rides inside a Mesherra SendClaim envelope.

Schema: `meshycal.scheduling/proposal-v1`. Fields:

- `candidates` — list of candidate ISO 8601 slot strings
- `duration_minutes`
- `constraint_hints` — soft constraints ("morning preferred", "30-min buffer")
- `calendar_titles` — optional, blocked by default policy
- `attendee_emails` — optional, blocked by default policy

The default outbound policy template allows `candidates`, `duration_minutes`, `constraint_hints` and blocks `calendar_titles`, `attendee_emails`. The airlock enforces this on every send.

---

## 4. Layer semantics for MeshyCal Objects

```
   USER A's STACK                                    USER B's STACK
   ─────────────────                                 ─────────────────

   PERSONAL LAYER (A)                                PERSONAL LAYER (B)
   ┌──────────────────────┐                          ┌──────────────────────┐
   │  CalendarObject (A)  │                          │  CalendarObject (B)  │
   │  • owner: A          │                          │  • owner: B          │
   │  • never crosses     │                          │  • never crosses     │
   │    the wire          │                          │    the wire          │
   └──────────┬───────────┘                          └──────────┬───────────┘
              │ free_slots() / busy_intervals_on()              │
              ▼                                                  ▼
   ┌──────────────────────┐    Proposals (scoped    ┌──────────────────────┐
   │  SchedulingAgent (A) │ ◀──by Policy, signed──▶ │  SchedulingAgent (B) │
   └──────────┬───────────┘    by SendClaim)        └──────────┬───────────┘
              │                                                  │
              │ on acceptance, A (initiator) creates             │
              │ MeetingObject locally, then promotes             │
              │ a live reference into a Shared layer:            │
              ▼                                                  │
   ╔═══════════════════════════════════════════════════════════╗ │
   ║              SHARED LAYER  (A ↔ B)                        ║ │
   ║                                                            ║ │
   ║   ┌──────────────────────────────────┐                    ║ │
   ║   │   MeetingObject                  │ ◀──live ref────────╫─┤
   ║   │   • canonical owner: A           │   promoted          ║ │
   ║   │   • B has live reference view    │   to B              ║ │
   ║   │   • per-viewer field visibility  │                    ║ │
   ║   └──────────────────────────────────┘                    ║ │
   ╚═══════════════════════════════════════════════════════════╝ │
              │                                                  │
              │  promotion + every update writes paired          │
              │  residue entries in BOTH ledgers                 │
              ▼                                                  ▼
   ╔══════════════════════╗                          ╔══════════════════════╗
   ║  MESHERRA AIRLOCK    ║                          ║  MESHERRA AIRLOCK    ║
   ║  enforces policy on  ║                          ║  enforces policy on  ║
   ║  every layer cross   ║                          ║  every layer cross   ║
   ╚══════════════════════╝                          ╚══════════════════════╝
```

**Layer rules for MeshyCal Objects:**

- **CalendarObject** is *always* in the owner's Personal layer. There is no scenario where the calendar itself is promoted. Its data only leaves in derivative form via Proposals.
- **MeetingObject** is created in the owner's Personal layer, then immediately promoted into a Shared layer between owner and counterpart. The promotion is signed and Residue is written on both sides at promotion time and again on every subsequent update.
- **Proposals** are wire payloads, not Objects. They do not have layer membership.

**Per-viewer visibility on MeetingObject** lets the owner choose which fields the counterpart sees. Default policy: counterpart sees `time`, `duration_minutes`, `timezone`, `title`, `location`. Counterpart does **not** see other attendees on the owner's side, internal notes, or the owner's full provenance chain. The owner sees the full object; the counterpart sees a scoped view of the same Object.

---

## 5. The Scheduling Agent

One SchedulingAgent runs per user per MeshyCal install, under the user's butler.

**Responsibilities:**

- Read the owner's CalendarObject when constructing a Proposal
- Send Proposals via `Mesherra.send_to()` — never directly to the A2A wire
- Receive incoming Proposals via the inbound gateway callback
- Run incoming Proposals through a Reasoner to produce a verdict (accept / counter / reject)
- On acceptance: create the MeetingObject (if owner) and promote a live reference (if owner), or accept the promotion (if counterpart)
- Book the agreed slot into the owner's CalendarObject

**Non-responsibilities (these belong to Mesherra, not MeshyCal):**

- Identity verification of the counterpart — handled by the inbound gateway via the Directory client
- Policy enforcement — handled by the airlock; the agent never reads its own PolicyStore
- Signing / canonicalization — handled by the SDK
- Replay defense, dedup — handled by Mesherra's inbound gateway
- Provenance writes — handled by Mesherra's outbound and inbound gateways

**Bypass discipline:** the SchedulingAgent's only outbound path is `self._sdk.send_to(...)` and its only inbound path is the callback registered via `self._sdk.on_message(...)`. It does not *call* methods on `A2AAdapter` directly — adapter construction may pass through the agent's process today, but no agent code path skips the airlock to write to the A2A wire. The cleaner long-term shape (open question §12) is for `Mesherra(...)` to own adapter construction entirely so the agent file never imports `A2AAdapter` at all.

### 5.1 Reasoners

A SchedulingReasoner takes a CalendarObject and a list of candidate slots and returns a `ProposalVerdict` (accept / counter with alternative slots / reject). Reasoners are interchangeable:

- `ScriptedReasoner` — deterministic, used in tests and predictable demos
- `AnthropicReasoner` — Claude-backed, for natural-language preference reasoning
- `OpenAICompatibleReasoner` — any OpenAI-protocol endpoint

Reasoners are domain-specific code that lives in MeshyCal and never leak into Mesherra. The Reasoner abstraction is a MeshyCal-internal choice; it is **not** a Delegation Authoring SDK pattern. If Delegation #2 turns out to also need a swappable LLM backend, that may justify lifting the pattern up; until then it stays here.

---

## 6. Policy templates

MeshyCal ships a default PolicyDoc factory (`build_policy_doc`) that produces a two-rule PolicyDoc:

**Outbound rule** (match: schema `meshycal.scheduling/proposal-v1`, direction OUTBOUND):

- `outbound_allow`: `candidates`, `duration_minutes`, `constraint_hints`
- `outbound_block`: `calendar_titles`, `attendee_emails`
- `max_array_size`: `{candidates: 5}` — caps slot enumeration

**Inbound rule** (match: schema `meshycal.scheduling/proposal-v1`, direction INBOUND):

- `inbound_allow`: `candidates`, `duration_minutes`, `constraint_hints`

The user signs this PolicyDoc with their own key when they install MeshyCal. The signed doc lands in the per-principal PolicyStore. Both gateways consult the PolicyEngine against it on every message. The user can edit the doc later through their policy editor (which lives in the butler or in MeshyCal's renderer, not in this Delegation's core).

**What the template promises:** sensible defaults. Nothing more. The user is the policy authority; MeshyCal's defaults are starting points, never commitments. The platform cannot write policy into the user's PolicyStore.

---

## 7. UI manifest and renderer

A Delegation manifest (`delegation.json`) is the bundle a butler reads to install a Delegation. It declares:

- The publisher principal (verified through the Directory)
- The Object class schemas (with publisher signatures, registered against the Schema Registry)
- The SchedulingAgent entry point
- The default PolicyDoc template
- The renderer manifest — what surface(s) the Delegation knows how to render to, and pointers to the renderer code

**Status:** `delegation.json` does not yet exist. Today, MeshyCal is installed by importing the Python package directly. This works for development but is not the install model the architecture commits to.

**Renderer:** the renderer is disposable. MeshyCal's renderer surface today is a prototype web sandbox (`demos/phase_4_prototype/`). As ambient/voice/AR surfaces emerge, the renderer is the layer that gets re-implemented per surface; the Object classes, agent, and policy template stay constant.

---

## 8. The negotiation flow

> **Note:** all 10 steps are implemented. Steps 1–8 are the signed Proposal exchange; steps 9–10 are the MeetingObject creation + live-reference promotion + counterpart subscribe + initial-state fetch. The counterpart books from the canonical MeetingObject state, not from an independent local accept — closing the "two independent book calls" gap §11 previously called out.

```
   1. Initiator A's butler routes "schedule with B" intent to A's SchedulingAgent
                                  │
                                  ▼
   2. A's SchedulingAgent reads A's CalendarObject → free_slots()
                                  │
                                  ▼
   3. A's SchedulingAgent builds Proposal(candidates, duration, hints)
                                  │
                                  ▼
   4. Mesherra outbound airlock:
        • PolicyEngine filters fields (calendar_titles, attendee_emails dropped)
        • Crypto signs SendClaim envelope
        • ProvenanceLedger writes EMIT entry on A's side
                                  │
                                  ▼  A2A wire
                                  │
   5. Mesherra inbound airlock on B:
        • Directory verifies A's identity + signature
        • Replay defense checks (nonce, clock skew, ledger dedup)
        • PolicyEngine filters inbound fields per B's PolicyDoc
        • ProvenanceLedger writes RECEIVE entry on B's side
                                  │
                                  ▼
   6. B's SchedulingAgent reads scoped Proposal + B's CalendarObject
                                  │
                                  ▼
   7. Reasoner produces verdict (accept | counter | reject)
                                  │
              ┌───────────────────┼────────────────────┐
              ▼                   ▼                    ▼
        7a. ACCEPT          7b. COUNTER          7c. REJECT
              │                   │                    │
              ▼                   ▼                    ▼
       (continue 8+)       (loop back to 3,     (signed rejection;
                            B becomes sender;    handshake closes
                            both sides write     with paired residue)
                            paired residue)
              │
              ▼
   8. B's SchedulingAgent sends acceptance Proposal back through airlock
                                  │
                                  ▼
   9. A (initiator) receives acceptance:
        • Creates MeetingObject in Personal layer
        • Promotes live reference to B (signed Promotion; paired residue)
        • Books the slot into A's CalendarObject (version bumps)
                                  │
                                  ▼
  10. B receives the live-reference handle:
        • Accepts the promotion (signed; paired residue)
        • Books the slot into B's CalendarObject (version bumps)
                                  │
                                  ▼
                Both ledgers now contain a complete, signed,
                hash-chained trace from initial intent to
                co-visible MeetingObject.
```

Notes on the flow:

- Steps 4 and 5 are the airlock crossings. Every message through them produces paired Residue entries (EMIT on sender, RECEIVE on receiver).
- The Proposal exchange in step 3–7 can loop multiple times (counter-proposals). Each loop is fully signed and recorded.
- Step 9's MeetingObject creation and promotion is the moment the "shared agreement" becomes a real Mesherra Object. Before this step, the negotiation exists only as a signed Proposal trail.
- Step 10's acceptance of the promotion is what gives B legitimate standing to read the MeetingObject. Without the signed acceptance, B would just have an unauthorized handle.

---

## 9. Identity for invitees (the hard problem)

The most difficult MeshyCal-specific question is: **how does a guest user with no MeshyCal install accept a meeting from a MeshyCal user?**

The architecture commits to verified principals on both sides. A guest has no principal in the Directory. The two reasonable resolutions:

1. **Invite-then-install.** The guest receives a low-friction onboarding flow that creates a guest principal (lightweight DID-style identity, no full account), enough to sign their side of the handshake. Friction: any. Trust: real.
2. **Asymmetric flow.** The MeshyCal user negotiates with a placeholder identity, captures the agreement, and the guest later "claims" it by demonstrating control of the contact channel (email/phone) the invite was sent to. The Residue chain is incomplete on the guest side until the claim. Friction: minimal. Trust: weaker.

Both have tradeoffs. The current architecture does not yet commit to one. This is the highest-priority open question in §12.

---

## 10. Build discipline (MeshyCal-specific)

In addition to the rules in `CLAUDE.md`, MeshyCal-specific commitments:

1. **CalendarObject never crosses the wire.** Only derivative payloads (Proposals, MeetingObject scoped views) cross. If a feature seems to require sending the calendar, the design is wrong.
2. **MeetingObject has one canonical owner.** Until Mesherra commits to co-ownership in a future architecture revision, MeshyCal does not invent multi-writer semantics on its own.
3. **The SchedulingAgent never bypasses the airlock.** All outbound through `Mesherra.send_to()`; all inbound through the registered callback. No direct A2A calls.
4. **The Reasoner abstraction is MeshyCal-internal.** It does not become a "Delegation LLM SDK" until Delegation #2 has the same need with the same shape.
5. **Synthetic data only.** No real names, calendars, emails, or events anywhere — fixtures, tests, prototypes, screenshots. Hard rule. Git history is forever.
6. **No hardcoded values.** All paths, hosts, ports, keys, principal IDs via environment. Fail fast on missing required vars.

---

## 11. Status & dependencies

### What's built today

- `CalendarObject` — owner-bound, canonically hashable, mutable. Production-ready.
- `MeetingObjectState` (in `meshycal/meeting_object.py`) — the structured state wrapped inside a Mesherra `Object` (`mutability=LIVE`, `schema_ref=meshycal.scheduling/meeting-v1`). Owner-bound, content-hash-anchored, scoped at promotion time via `MEETING_SCOPE_FIELDS`.
- `SchedulingAgent` — wraps the Mesherra SDK with an `ObjectStore`. On accept, the initiator creates the MeetingObject + LIVE-promotes it; the counterpart subscribes and fetches initial state via `subscribe_to_pending_meetings(peer_url, my_url)`. Does not bypass the airlock.
- `policy_template.py` — default outbound/inbound PolicyDoc factory.
- Reasoners — Anthropic, OpenAI-compatible, scripted variants, all interchangeable behind a Protocol.
- Tests: `tests/test_scheduling_agent.py` (Proposal exchange hash invariant) + `tests/test_meeting_object.py` (state Pydantic model) + `tests/test_meeting_object_roundtrip.py` (full §8 end-to-end with real HTTP listeners).

### What lags the target

| Gap | What's missing | What it blocks |
|---|---|---|
| `delegation.json` manifest | The install bundle (§7) | Butlers cannot install MeshyCal; the Delegation pattern is not yet realized end-to-end |
| Schema Registry wiring | `.env.example` declares `MESHYCAL_SCHEMA_PUBLISHER_PRINCIPAL` and `MESHYCAL_SCHEMA_REGISTRY_URL`; no code reads them. Schemas live as hardcoded strings. | Forced rewrite when Delegation #2 ships; today's schemas have no publisher signature chain |
| Invitee identity flow | No guest-principal lifecycle (§9) | The "send a meeting to anyone" UX |
| Renderer | The Phase 4 prototype is scaffolding, not a published renderer | Demo polish; butler-surface integration |
| Per-viewer field visibility primitive | Mesherra's per-viewer layer-membership (Mesherra ARCH §3.3) is not yet first-class. MeshyCal currently uses scope `fields` lists at promotion time as a workaround. | Per-viewer custom field visibility on a single MeetingObject (e.g., Alice and Carol see different attendee lists). |
| Reschedule/cancel UX on receiver side | `_handle_object_update` is a no-op stub in Slice 1. Push pipeline works; consumer just logs. | The "owner reschedules and the counterpart's calendar updates" demo polish. |

### Mesherra dependencies

The following Mesherra primitives MeshyCal had been waiting on have **shipped** in Mesherra Phase 4 Slice 1+2 and are now consumed:

| Mesherra primitive | MeshyCal feature now realized |
|---|---|
| `Object` class | MeetingObject is a real Mesherra Object on the initiator's side (`mutability=LIVE`, `schema_ref=meshycal.scheduling/meeting-v1`) |
| `Promotion` + `PromotionHandle` | Owner LIVE-promotes the MeetingObject; counterpart receives the signed handle; both sides relate to the same canonical state |
| `Mesherra.subscribe_to_object`, `Mesherra.on_object_update`, `Mesherra.fetch_object` (LIVE branch) | Counterpart subscribes to receive future updates, fetches initial state immediately, and books from the canonical agreement |

Still gated:

| Mesherra primitive | MeshyCal feature gated on it |
|---|---|
| `Layer` class (still stub) | Formal layer membership for CalendarObject/MeetingObject (currently MeshyCal uses scope `fields` at promotion time as a workaround) |
| `SchemaRegistry` | Signed schema publication (§7 manifest, schema-registry wiring) |

### Demos directory

`demos/phase_1/` and `demos/phase_4_prototype/` contain working scaffolding from earlier development phases. They are not part of the Delegation contract and will be re-homed as `tests/e2e/` (Phase 1 demo) and an out-of-tree prototype repo (Phase 4 sandbox) once the production package matures. They are not the organizing structure for MeshyCal going forward — the Delegation contract in §2 is.

---

## 12. Open design questions

These are MeshyCal-specific. Cross-references to Mesherra's `docs/ARCHITECTURE.md` §14 where the question is upstream.

1. **Invitee identity flow** (§9). Highest priority. Picks between guest-principal lifecycle and asymmetric flow.
2. **MeetingObject co-ownership.** Today MeetingObject is single-owner with live-reference promotion. If MeshyCal use cases reveal the asymmetry is painful (e.g., counterpart needs to reschedule), this becomes a request to Mesherra to lift the single-owner commitment (cross-reference Mesherra §3.2 and §14).
3. **Per-viewer field visibility primitive.** Mesherra's per-viewer layer-membership (Mesherra §3.3) is currently expressed conceptually but not yet exposed as a first-class API. MeshyCal's MeetingObject needs it; specifying that API is partly a MeshyCal design pressure.
4. **Reasoner extraction trigger.** When (if ever) does the swappable-LLM-backend pattern earn its place as a shared Delegation utility rather than MeshyCal-internal? Trigger: Delegation #2 implements the same pattern unprompted.
5. **Calendar integration.** Real-world CalendarObject backed by Google / Microsoft / iCloud calendars. Adapters belong in MeshyCal (per Mesherra build discipline rule 2). Not yet designed; deferred until invitee flow is settled.
6. **Recurrence and series.** A MeetingObject today represents one meeting. Recurring meetings are a series of MeetingObjects sharing a series ID. Schema not yet designed.
7. **Rescheduling and cancellation flows.** Both produce new Residue entries on the existing MeetingObject. Wire pattern not yet specified.
8. **Multi-party scheduling.** Today the architecture covers 1:1 negotiation. N-party scheduling cascades the negotiation pattern — each pair handshakes, with one MeetingObject as the shared anchor. Open whether N-party requires Mesherra primitive changes.
9. **Adapter ownership inside the SDK.** Today the SchedulingAgent constructs an `A2AAdapter` and passes it to the `Mesherra(...)` SDK. Cleaner shape: `Mesherra(...)` owns adapter construction internally so MeshyCal never imports `A2AAdapter`. Cosmetic for now; matters when other Delegations are written and the import shrinks the surface MeshyCal is responsible for understanding.

---

## 13. Cross-references

- `../../mesherra/docs/ARCHITECTURE.md` — full Mesherra primitive specification
  - §3.2 (Object), §3.3 (Layer), §3.7 (Object data flow) — primitive semantics MeshyCal builds on
  - §10 — Mesherra's framing of MeshyCal as first consumer
  - §13.11 — Schema Registry
- `../../mesherra/docs/STRATEGY.md` — strategic positioning; §5 specifically frames MeshyCal as reference implementation
- `../CLAUDE.md` — orientation for any AI coding session entering this repo

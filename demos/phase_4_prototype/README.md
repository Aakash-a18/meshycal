# MeshyCal Phase 4 — interactive prototype

A self-contained design + behavior prototype for the Phase 4 MeshyCal
renderer. Two pieces:

1. **`index.html`** — single-file HTML/CSS/JS. Open in any browser.
2. **`server/`** — small FastAPI bridge that exposes the existing
   Phase 3 Mesherra backend over HTTP. When this is running, the
   prototype displays **real** cryptographic outputs from a live
   Mesherra two-party negotiation; when it's off, the prototype
   gracefully falls back to a choreographed animation with seeded
   pseudo-hashes.

The on-screen "backend" badge (in the live-demo section) reports
which mode is active.

## Quick start

```bash
# from the MeshyCal repo root
source .venv/bin/activate
uvicorn demos.phase_4_prototype.server.main:app --port 8765 --reload
```

Then open `demos/phase_4_prototype/index.html` in your browser.

The badge will flip to `● backend live · real cryptography`. Press
**Request meeting** — the animation will play while a real Phase 3
negotiation runs server-side (~200ms), and the ledger entries +
hashes shown are the actual signed Mesherra residue.

---

## Aesthetic direction

**Editorial archival meets digital tessera.** A notary's office for the
agent age.

| Element       | Choice                                                                                       |
| ------------- | -------------------------------------------------------------------------------------------- |
| Surface       | parchment cream `hsl(40 32% 93%)`, with subtle paper grain and radial wash                   |
| Type          | **Fraunces** (display, optical-sized serif with `WONK` variation), **Newsreader** (body, refined serif), **IBM Plex Mono** (data) |
| Ink           | deep blue-black `hsl(222 28% 11%)`                                                           |
| Warning       | terracotta `hsl(13 60% 50%)` — the blocked-field color                                       |
| Verified      | jade green `hsl(155 30% 33%)` — the allowed-field color, the receive-action color            |
| Seam / signal | gold leaf `hsl(40 70% 53%)` — the moment the two halves fit                                  |
| Motion        | slow, deliberate cubic-bezier curves; restrained except at the tessera-fit moment            |

**Why not the AI defaults.** The skill explicitly steers away from
generic sans (Inter, Roboto), purple gradients on white, and
predictable layouts. The project's origin metaphor — the Roman tessera,
two halves that fit centuries apart — earns an editorial, archival
treatment over a tech-monospace one.

## The brand-defining moment

When a negotiation completes, two stone halves (the tessera) slide in
from opposite sides, a vertical gold seam grows between them, and the
caption reads `tessera fit · trust verified`. This is the **single
moment** a viewer is meant to remember. Everything else in the page
serves it: the airlock evaporation foreshadows it; the matching ledger
hashes prove it numerically; the policy template explains how it's
enforced.

## Page structure

1. **Hero** — Fraunces "the digital tessera" with the stone graphic.
2. **Three primitives** — Provenance / Identity / Scoped disclosure,
   each tagged with their shipped phase.
3. **Live demo** (dark editorial section) — split-screen Iris ↔ wire ↔
   Marius. The airlock chamber sits in the middle. Field tiles
   evaporate; scoped fields cross; tessera-fit overlay plays; both
   ledgers populate.
4. **Policy** — the default MeshyCal template as syntax-highlighted YAML,
   alongside narrative explaining what it means.
5. **Roadmap** — three scenarios with their backend status.
6. **Colophon** — the metaphor, the repos, the prototype's own
   self-description.

## Scenario coverage

The three test scenarios you specified, with what each needs:

| # | Scenario                       | Status in this prototype | Backend needs                                                                                              |
| - | ------------------------------ | ------------------------ | ---------------------------------------------------------------------------------------------------------- |
| 1 | A ↔ B direct request           | **Live in the browser**  | Already shipped — Phase 3 covers it end-to-end.                                                            |
| 2 | A, B, C, D group find          | Tabbed, not implemented  | **Multi-party orchestration.** A coordinator pattern on top of Mesherra's bilateral primitive. Each bilateral exchange still passes through the existing policy + receipt machinery — no change to Mesherra. |
| 3 | Cascading reschedule           | Tabbed, not implemented  | **LLM-driven scheduling agent.** Agents must reason about tradeoffs ("can I move my meeting with C to free this slot?") and initiate downstream negotiations under per-user policy. Mesherra trust layer unchanged. |

## When this becomes a real app

Recommended stack — opinionated but reversible:

- **Web first:** Next.js 15 + React 19 + TypeScript. Server components
  for the policy/ledger views (server-side render with verified
  receipts); client components for the live demo + animations.
- **Animation library:** Motion (formerly Framer Motion). The airlock
  evaporation and the tessera-fit moment justify a real motion runtime.
- **Backend bridge:** the existing Python Mesherra SDK stays
  authoritative. The web app talks to a thin FastAPI service that
  exposes the SDK over HTTP (orchestrator role from the Phase 1/2/3
  demos lifted into a real service).
- **Mobile:** deferred to Phase 4.5. Either React Native sharing the
  TypeScript front-end, or native iOS/Android — defer the decision
  until the web app proves the interaction model.
- **Synthetic data only** — `synthetic_calendar.py` already exists in
  this repo. The web app reads from the same JSON shape.

## Phase 4 follow-up — what comes next

In priority order:

1. **Productionize this prototype.** Port to Next.js + React. Wire the
   "Run scenario 1" button to a real backend hit (FastAPI wrapping the
   Phase 3 demo orchestrator) so the receipts shown are *actually*
   signed Mesherra residue, not seeded hashes.
2. **Policy editor.** Visual editor for the YAML template. User adds /
   removes fields from allow / block lists; signs the new version with
   their Ed25519 key; the PolicyStore versioning machinery handles
   monotonicity.
3. **Receipt inspector.** Click a ledger entry to see its full
   canonical JSON, signature, and chain link. Designed like an old
   evidence dossier opening.
4. **Scenario 2 backend.** Multi-party group-find. Coordinator pattern
   on top of the existing bilateral SDK.
5. **Scenario 3 backend.** Agent reasoning layer. LLM-driven proposer
   with per-user policy bounds on what it may autonomously propose.

## Notes on the implementation

- Pure HTML/CSS/JS, single file, no build step. Open it directly.
- Google Fonts pulled at runtime via stylesheet `@import`.
- DOM construction uses safe `createElement` / `textContent` rather
  than `innerHTML` to keep the prototype out of the XSS bad-pattern
  category if anyone reuses the code.
- The "fake hash" function is deterministic-looking but not
  crypto-strong — the real app uses `SHA-256(JCS(payload))` via the
  existing Mesherra crypto primitives. The visual format matches what
  the production ledger view would show.

## Open questions the prototype surfaces

These are the design decisions the real app needs to make that the
prototype is intentionally noncommittal about:

- **Identity in the UI.** This prototype shows two principals as
  "Iris" and "Marius." A real app needs a sign-up flow (key
  generation? key import? recovery story?). The whole Phase 2
  identity directory exists; how the user interacts with it is open.
- **Group-find UX.** Scenario 2 says A, B, C, D find a common time. Is
  one of them the coordinator? Does the UI show all four perspectives,
  or just the convener's? Decision deferred to when scenario 2 ships.
- **Agent reasoning UX.** Scenario 3 has B's agent reasoning about
  trades. Does the user see the agent's reasoning trace? Audit it
  after the fact? Approve before commit? These are real product
  questions; the prototype just gestures at "agent-to-agent dialog
  visible."

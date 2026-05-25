# MeshyCal Sandbox Frontend Design

**File:** `MeshyCal/demos/phase_4_prototype/SANDBOX_FRONTEND_DESIGN.md`
**Target output:** `MeshyCal/demos/phase_4_prototype/sandbox.html`
**Status:** Detailed implementation spec. Reference material when the sandbox build begins. The higher-level `SANDBOX_ARCHITECTURE.md` is the document for non-technical reading and for feeding into UI design tools.
**CSS namespace:** All sandbox-specific identifiers use the `sb-` prefix.
**XSS discipline:** Same as `index.html` — all dynamic DOM content via `elem()` / `textContent` / `document.createTextNode()`. `innerHTML` never used for dynamic content.
**Dependencies:** Pure HTML + CSS + vanilla JS, single file, no build step. Google Fonts via `<link>` at runtime, same as `index.html`.
**Relationship to `index.html`:** Additive, separate file. `index.html` is not modified.

---

## 1. Page Layout

### 1.1 ASCII Sketch

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  HEADER BAR                                                                 │
│  ⌘ MESHYCAL · SANDBOX          [← back to demo]   [Reset session]          │
├────────────────────────────┬────────────────────────────────────────────────┤
│  EDITOR PANEL (320px)      │  STAGE PANEL (fluid)                           │
│                            │                                                │
│  [+ Add principal]         │  ┌── REQUEST INITIATOR ──────────────────────┐│
│                            │  │ From ▾  To ▾  Earliest  Latest  [Fire]    ││
│  ┌─ card: Iris ──────────┐ │  └───────────────────────────────────────────┘│
│  │ I  Iris (iris@…)      │ │                                                │
│  │ [calendar mini-view]  │ │  ┌── VISUALIZATION STAGE ────────────────────┐│
│  │ [policy summary]      │ │  │ narrative band                             ││
│  │ [reasoner: scripted]  │ │  │ principal columns + reasoning trace        ││
│  │ [▼ expand]            │ │  │ agent dialogue transcript                  ││
│  └───────────────────────┘ │  │ tessera-fit badges + ledgers               ││
│                            │  └───────────────────────────────────────────┘│
│  ┌─ card: Marius ────────┐ │                                                │
│  │ M  Marius             │ │                                                │
│  └───────────────────────┘ │                                                │
└────────────────────────────┴────────────────────────────────────────────────┘
```

### 1.2 Layout Choice: Side-by-Side

Editor left (320px fixed), stage right (fluid). Vertical rule between (`border-right: 1px solid var(--rule)`). Editor and stage scroll independently.

Below 1100px viewport: stacks (editor on top, stage below).

Rationale: the stage is the payoff — it needs to stay visible while editing. Stacked would force scrolling between editor and visualization, losing real-time feedback. Mirrors how R&D tools like Postman work.

Grid: `display: grid; grid-template-columns: 320px 1fr; gap: 0` on `.sb-workspace`.

---

## 2. Editor Surface

### 2.1 Principal Card — Collapsed State

Each principal is a card in `.sb-editor-list`. Cards stack vertically with `border-bottom: 1px solid var(--rule)`.

Collapsed card shows:
- **Avatar**: 40px circle, initials, colored from principal's assigned color slot.
- **Display name** (Fraunces italic, 18px, click to inline-edit).
- **Principal ID** read-only (IBM Plex Mono, 10px, `var(--ink-mute)`).
- **Reasoner badge**: one-word label (`scripted` / `anthropic` / `openai` / `compatible`).
- **Event count**: "N events".
- **Expand/collapse chevron**.
- **Delete `×` button** (hover-visible).

Cards expand **in place** (not in a drawer), pushing cards below them down. Animated `max-height` CSS transition (200ms ease).

### 2.2 Principal Card — Expanded State

Four sub-sections:

#### 2.2.1 Identity
- Display name `<input class="sb-name-input">`: looks like Fraunces italic heading, no border, transparent bg.
- Principal ID `<span class="sb-pid mono">`: read-only, auto-generated as `{slug}@sandbox.local` (unless locked).
- Delete link `sb-delete-link`: terracotta "remove principal".

#### 2.2.2 Calendar editor
- `<ul class="sb-event-list">` with one `<li class="sb-event-row">` per event:
  - `<input type="time" class="sb-ev-time">` 24h
  - `<input type="number" class="sb-ev-dur" min="5" max="480" step="5">` + "min"
  - `<input type="text" class="sb-ev-title">`: italic, placeholder "event title"
  - `<input type="text" class="sb-ev-attendees">`: small mono muted, placeholder "attendees (comma-separated)"
  - `×` remove button on hover
- `<button class="sb-add-event-btn">+ add event</button>` ghost style. Disabled at 10 events with "max 10".

Event tile style: lighter treatment than `index.html`'s `.calendar` (uses `var(--paper-deep)` for tiles in editor mode, not dark ink).

#### 2.2.3 Policy editor
- **Outbound allow list** for `meshycal.scheduling/proposal-v1`: tag-chip input. Default chips: `candidates`, `duration_minutes`, `constraint_hints`.
- **Outbound block list**: terracotta-tinted tag chips. Default: `calendar_titles`, `attendee_emails`.
- **Inbound allow list**: same pattern. Default: `candidates`, `duration_minutes`, `constraint_hints`.
- **Max cascade depth**: `<select class="sb-cascade-select">` with 0/1/2/3 options. Default 1.

#### 2.2.4 Reasoner config
- **Provider dropdown** `<select class="sb-provider-select">`: scripted (default) / anthropic / openai / openai-compatible.
- **Model name** `<input class="sb-model-input">`: hidden when scripted. Placeholders per provider:
  - anthropic: `claude-sonnet-4-6`
  - openai: `gpt-4o`
  - openai-compatible: `model name`
- **API key** `<input type="password" class="sb-apikey-input">`: hidden when scripted. Placeholder "API key (session only — never stored)".
  - **Warning notice below** (`sb-apikey-warning`): "This key lives in memory only. It is never sent to any server other than the provider's API endpoint. You must re-enter it after a page refresh." Small mono, terracotta at 0.75 opacity.
- **Base URL** `<input type="url" class="sb-baseurl-input">`: only shown for openai-compatible.

JS toggles a `sb-hidden` utility class for conditional visibility.

### 2.3 Add Principal Button

`<button class="sb-add-principal-btn">+ add principal</button>` at the bottom of the editor list. Full-width ghost style. Generates new principal with synthetic name (`Principal D`, `Principal E`, ...) and default values. Max 6 principals; button disabled at max.

### 2.4 Principal Color Slots

6 slot palette assigned in rotation:

| Slot | Background | Ink | Label |
|---|---|---|---|
| 0 | `hsl(40 32% 85%)` | `var(--ink)` | iris-gold |
| 1 | `var(--jade)` | `var(--paper)` | jade |
| 2 | `var(--terracotta)` | `var(--paper)` | terracotta |
| 3 | `hsl(240 25% 52%)` | `var(--paper)` | slate |
| 4 | `hsl(30 55% 42%)` | `var(--paper)` | amber |
| 5 | `hsl(270 20% 45%)` | `var(--paper)` | plum |

Each `Principal` carries `colorSlot: 0..5` assigned at creation. Dialogue panel's left-border accent maps to color slot at runtime (not hardcoded principal name).

---

## 3. Request Initiator

### 3.1 Form Layout

`<div class="sb-request-form">` above the visualization, parchment-deep background, mono labels.

Fields (flex row, wraps narrow):
- **Sender** `<select class="sb-req-sender">` — populated from `SB_STATE.principals`.
- **Recipient** `<select class="sb-req-recipient">` — list minus current sender.
- **Earliest start** `<input type="datetime-local" class="sb-req-earliest">`
- **Latest end** `<input type="datetime-local" class="sb-req-latest">`
- **Duration** `<input type="number" class="sb-req-duration" min="5" max="480" step="5" value="30">` + "min".
- **Context note** `<input type="text" class="sb-req-note">`: placeholder "what is this meeting about? (optional)". Full-width below.
- **Fire request** `<button class="sb-fire-btn">`: ink bg, paper text, mono uppercase. Hover: terracotta. Disabled during a run.

Sender == recipient → fire button disabled with tooltip "sender and recipient must be different".
Fewer than 2 principals → "add at least 2 principals".

### 3.2 Default Values

On page load with default principals:
- Sender: index 0
- Recipient: index 1
- Earliest: today + 1 day, 09:00 local
- Latest: today + 1 day, 18:00 local
- Duration: 30

---

## 4. Live Visualization

### 4.1 Idle State

Mono italic "fire a request to begin" centered in the stage.

### 4.2 Narrative Band

`<div class="sb-narrative-band">` — identical visual design to `.s3-narrative-band` from `index.html`. Eyebrow "the run", paragraph updated via `sbNarrativeBeat(text)` with 200ms fade.

### 4.3 Principal Columns Stage

Dynamic grid:
- 2 principals: `grid-template-columns: 1fr 1fr`
- 3 principals: `grid-template-columns: 1fr 1.6fr 1fr` (middle = reasoner/pivot)
- 4+: graceful degradation banner ("4+ principal visualization is available in v1")

Each principal column has:
- **Who header**: avatar + display name + principal ID (reuses `.party .who .avatar` / `.name` / `.id`).
- **Calendar mini-view**: reuses `.calendar` / `.event` / `.event .time` / `.event .title` / `.event .attendees` CSS verbatim.
- **Scoped payload panel** (for involved principals): reuses `.s3-pp-row` / `.s3-pp-k` / `.s3-pp-v` / `.s3-pp-blocked`.
- **Reasoning trace** (pivot principal only): reuses `.s3-reasoning-trace` / `.s3-trace-header` / `.s3-trace-fields` / `.s3-trace-reason`.

Tessera-fit overlay reuses Scenario 3's exact SVG path and animation. Verdict text dynamic: 2-party "tessera fit · trust verified"; 3-party "N fits · cascade complete · trust verified".

### 4.4 Flow Arrows

- 2-party: one forward + one return arrow (sender↔recipient).
- 3-party: 4 arrows matching Scenario 3 (A→B, B→C, C→B, B→A).

Reuses `.s3-arrow` / `.s3-arrow--active` / `s3-arrowhead` marker verbatim.

### 4.5 Agent Dialogue Transcript

`.sb-dialogue-panel` — identical visual design to `.s3-dialogue-panel`. Per-agent left-border color assigned dynamically:

| Color slot | Border / direction color |
|---|---|
| 0 (iris-gold) | `hsl(40 55% 68%)` / `hsl(40 45% 60%)` |
| 1 (jade) | `var(--jade)` / `hsl(155 30% 52%)` |
| 2 (terracotta) | `var(--terracotta)` / `hsl(13 45% 58%)` |
| 3 (slate) | `hsl(240 25% 62%)` / `hsl(240 20% 65%)` |
| 4 (amber) | `hsl(30 55% 62%)` / `hsl(30 45% 58%)` |
| 5 (plum) | `hsl(270 20% 55%)` / `hsl(270 18% 60%)` |

`sbDialogueAppend(principalId, fromLabel, directionLabel, bodyText, showSpinner)` maps `principalId` → color slot → `sb-dm--slot-{N}` class.

Thinking-row pattern (spinner + italic muted) reused verbatim from Scenario 3.

### 4.6 Exchange Badges

`sb-exchange-badges` container. `sbAppendExchangeBadge()` reuses inline tessera SVG badge code from `s3AppendExchangeBadge` verbatim.

### 4.7 Calendar Delta Animation

`sbAnimateCalendars(deltas)` iterates per-principal deltas in order:
- Moved/removed: `sbMoveSlot(colId, slotId)` adds `s3-slot-moving-out` then removes after 400ms.
- New/gained: `sbGainSlot(calId, slotId, time, title, attendees)` reused verbatim from Scenario 3.

All CSS classes (`s3-slot-moving-out` / `s3-slot-appearing` / `s3-slot-appeared` / `.event.booked` / `.event.free` / `@keyframes bookingFlash`) reused unchanged.

### 4.8 Step Indicator

`<div class="step-indicator sb-step-indicator">` below the request form. Generated dynamically:
- 2-party: 7 steps (matching Scenario 1)
- 3-party: 8 steps (matching Scenario 3)

Reuses `.step` / `.step.active` / `.step.done` verbatim.

### 4.9 Run Status Bar

Below step indicator. Mono 11px `hsl(40 25% 65%)`. Updated by `sbSetStatus(msg)`.

### 4.10 Topology Handling

UI does not know topology in advance. `sbRenderRun(result)` reads `result.exchanges[]` and `result.principals[]` to determine column count + arrow layout.

**2-party**: 7 narrative beats (build → scope → cross → match → seal → fit → update).
**3-party**: 9 narrative beats (build → scope → cross → reason → cascade → sub-accept → confirm → fit → update).
**4+-party**: graceful degradation (dialogue + step indicator only, no principal columns; banner "4+ visualization available in v1").

### 4.11 Error / Abort Rendering

On fetch error or backend 4xx/5xx:
- Narrative band: "Run aborted. [reason]"
- `sb-abort-banner` block below stage (visual match to `.s3-abort-banner`)
- Fire button re-enables
- "Reset stage" link in banner clears visualization back to idle

---

## 5. Session Lifecycle

### 5.1 Session Token

On page load `sbInit()`:
1. Check `localStorage.getItem("sb_session_token")`.
2. If absent: `POST /sandbox/session` → store `{ session_token, expires_at }`.
3. If present: use it for all API calls via `Authorization: Bearer {token}` header (or path param per backend spec).
4. If POST fails: enter **offline mode** — `sessionToken = null`, all API calls skipped, animation-mode fallback with seeded hashes. Header shows "○ backend offline · animation mode".

### 5.2 API Key Storage Policy

- Keys stored in `SB_STATE.apiKeys[principalId]` (in-memory JS only).
- NEVER written to localStorage.
- NEVER logged or appended to DOM.
- `sbPersistSession()` serializes a sanitized copy of principals with `reasoner.apiKey` stripped before writing to localStorage.
- On refresh: principal config restored, API keys are blank, user re-enters.
- Communicated via the API key warning notice and a header notice ("API keys are not persisted").

### 5.3 Default Principals on Fresh Session

Three default principals matching the Scenario 3 setup:

| Principal | Display name | Color slot | Reasoner | Events |
|---|---|---|---|---|
| `iris@sandbox.local` | Iris | 0 (gold) | scripted | 09:00 morning-standup 60min, 11:00 focus-block 30min |
| `marius@sandbox.local` | Marius | 1 (jade) | scripted | 10:00 weekly-review 60min, 14:00 project-sync 45min (blocks), 15:30 1-on-1 30min |
| `atlas@sandbox.local` | Atlas | 2 (terracotta) | scripted | 14:00 project-sync 45min (blocks) |

Policy: MeshyCal default template, max cascade depth 1.
Request form pre-fills: sender=Iris, recipient=Marius, duration=30, earliest=09:00 next day, latest=18:00 next day.

### 5.4 LocalStorage Keys

| Key | Value | Contains API keys? |
|---|---|---|
| `sb_session_token` | string | No |
| `sb_session_expires` | ISO 8601 | No |
| `sb_principals` | JSON (sanitized) | No |
| `sb_request_defaults` | JSON | No |

### 5.5 Reset Session

"Reset session" button:
1. `DELETE /sandbox/session` (fire-and-forget).
2. Clear all `sb_*` from localStorage.
3. `sbResetSession()`: clears `SB_STATE`, re-runs `sbInit()`, re-renders editor + stage.

Session status badge in header (mirrors `#backendStatus` from `index.html`):
- "● session live · {token[:8]}…" jade — backend connected
- "○ backend offline · animation mode" terracotta — backend unreachable

---

## 6. Aesthetic Discipline

### 6.1 Fonts

Same three fonts as `index.html` via Google Fonts `<link>`: Fraunces + Newsreader + IBM Plex Mono.

### 6.2 Palette

Same `:root` token block as `index.html` duplicated verbatim:
`--paper, --paper-deep, --paper-dim, --ink, --ink-soft, --ink-mute, --rule, --terracotta, --terracotta-deep, --jade, --jade-deep, --gold, --gold-deep, --display, --body, --mono, --rad, --rad-lg`.

### 6.3 Body Background

Same `body::before` grain/radial texture as `index.html`.

### 6.4 Input Styling

```css
.sb-card input, .sb-card select {
  font-family: var(--mono);
  font-size: 12px;
  background: var(--paper-deep);
  border: 1px solid var(--rule);
  border-radius: 0;
  color: var(--ink);
  padding: 6px 10px;
  width: 100%;
  outline: none;
  transition: border-color 150ms ease;
}
.sb-card input:focus, .sb-card select:focus {
  border-color: var(--ink-soft);
}
```

No rounded corners. No box shadows on focus. No blue ring. Notary-ledger feel.

### 6.5 Header Bar

```html
<header class="sb-header">
  <div class="sb-header-brand">⌘ MESHYCAL  ·  SANDBOX</div>
  <div class="sb-header-eyebrow">R&D mode · session-scoped principals · api keys in memory only</div>
  <nav class="sb-header-nav">
    <a href="index.html" class="sb-back-link">← demo</a>
    <div id="sb-session-badge" class="sb-session-badge">checking…</div>
    <button id="sb-reset-btn" class="sb-reset-btn ghost">reset session</button>
  </nav>
</header>
```

Same visual structure as `.hero-bar` in `index.html`.

### 6.6 No External Libraries

Same as `index.html`. Google Fonts CSS via `<link>` only. No npm/JS bundles.

---

## 7. JS Architecture

### 7.1 IIFE Structure

All JS in one `<script>` block at the bottom of `<body>`, inside an IIFE.

### 7.2 State Object

```js
const SB_STATE = {
  sessionToken: null,
  backendOk: false,
  principals: [],         // Array<Principal>
  runResult: null,
  runInProgress: false,
  apiKeys: {},            // { [principalId]: String }  — in-memory only
};
```

### 7.3 Entity Shapes (UI-side)

**Principal**: `{ id, displayName, colorSlot, calendar, policy, reasoner }`
**Event**: `{ time, duration, title, attendees, isBlocking }`
**Policy**: `{ outboundAllow[], outboundBlock[], inboundAllow[], maxCascadeDepth }`
**ReasonerConfig**: `{ provider, model, baseUrl }` — apiKey NOT here, lives in `SB_STATE.apiKeys[principalId]`
**Request**: `{ senderId, recipientId, earliest, latest, duration, note }`
**RunResult**: `{ success, principals[], exchanges[], calendarDeltas[], narrativeBeats[], durationMs, reasonerTrace? }`
**Exchange**: `{ id, initiatorId, responderId, proposalPayloadHash, acceptancePayloadHash, taskId }`
**CalendarDelta**: `{ principalId, type: "remove"|"add"|"rebook", slotId, time, title, attendees }`
**ReasonerTrace**: `{ requestedSlot, blockingEventTitle, blockingEventAttendee, proposedNewSlot, reason }`

The implementer reconciles these with the actual backend JSON shape from `SANDBOX_BACKEND_DESIGN.md`.

### 7.4 Core Functions

- `sbInit()` — load persisted state, probe backend, render initial UI.
- `sbRenderPrincipals()` — rebuild `#sb-editor-list` from `SB_STATE.principals`.
- `sbRenderPrincipalCard(principal)` — DOM for one collapsed card + event listeners.
- `sbUpsertPrincipal(principal)` — add or replace in state, persist, update dropdowns; in-place UI update (not full re-render).
- `sbDeletePrincipal(id)` — remove from state, persist, full re-render.
- `sbFireRequest()` — assemble request, inject API keys from `SB_STATE.apiKeys`, POST `/sandbox/run`, consume RunResult.
- `sbRenderRun(result)` — the main visualization driver. Determines topology, builds principal columns, walks narrative beats with `sleep()` calls, appends dialogue messages and badges, triggers tessera overlay, animates calendars.
- `sbResetSession()` — DELETE session, clear localStorage, re-init.
- `sbPersistSession()` — sanitize + write to localStorage.
- `sbNarrativeBeat(text)` — fade-swap-fade text in `#sb-nb-text`.
- `sbDialogueAppend(principalId, fromLabel, directionLabel, bodyText, showSpinner)` — append dialogue row with color-slot class.
- `sbAppendExchangeBadge(...)` — reuse Scenario 3 inline tessera badge code.
- `sbAnimateCalendars(deltas)` — choreographed sequence of `sbMoveSlot` and `sbGainSlot` calls with `sleep()` gaps.

### 7.5 Shared Helpers (duplicated from `index.html`)

Per CLAUDE.md rule 7 (no extraction before two examples exist): duplicated verbatim into `sandbox.html`.

- `elem(tag, opts, ...children)`
- `clearChildren(el)`
- `sleep(ms)`
- `fakeHash(seed)`
- `appendLedgerEntry(body, { seq, ts, action, op, actor, counterpart, hash })`
- `setLedgerEmpty(body, message)`
- `ledgerRow(label, value, valueClass)`

v1 extraction to `assets/helpers.js` is noted as planned (the second use case now exists).

### 7.6 API Constants

```js
const SB_API_BASE = (window.MESHYCAL_API_BASE || "http://127.0.0.1:8765").replace(/\/$/, "");
const SB_SANDBOX_API_BASE = (window.MESHYCAL_SANDBOX_API_BASE || SB_API_BASE).replace(/\/$/, "");
```

The sandbox endpoints are at `/sandbox/...`. The `/scenarios/...` endpoints from existing prototype are NOT called from `sandbox.html`.

---

## 8. What to Leave Untouched

- `index.html` — fully working, demo-worthy. Zero changes.
- All existing `server/` code.
- The Mesherra trust layer.
- All existing `UI_*.md` spec files and tests.

---

## 9. File Layout

**New files:**
| Path | Description |
|---|---|
| `demos/phase_4_prototype/sandbox.html` | The sandbox page. Single-file. |
| `demos/phase_4_prototype/SANDBOX_FRONTEND_DESIGN.md` | This spec. |
| `demos/phase_4_prototype/sandbox-demo-data.json` *(optional)* | Default principal set if too verbose to inline. `sbInit()` fetches it from a relative path; falls back to hardcoded inline data if fetch fails. |

**Untouched:** `index.html`, all `server/*.py`, all `tests/*.py`, all existing `UI_*.md`.

---

## 10. Backend Endpoint Contract (UI Assumptions)

The backend spec (`SANDBOX_BACKEND_DESIGN.md`) defines actual shapes. UI assumes:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/sandbox/session` | Create session. Returns token + expires + default principals. |
| `GET` | `/sandbox/session/{token}` | Read current state (api_keys scrubbed). |
| `PUT` | `/sandbox/session/{token}/principal/{id}` | Upsert principal (api_key accepted in body). |
| `DELETE` | `/sandbox/session/{token}/principal/{id}` | Remove principal. |
| `POST` | `/sandbox/session/{token}/run` | Fire a scheduling request → `RunResult`. |
| `DELETE` | `/sandbox/session/{token}` | Destroy session. |
| `GET` | `/healthz` | Liveness probe (shared with existing prototype). |

The implementer reconciles `SB_STATE.principals` and request form values against the backend spec's exact field names before wiring Phase D.

---

## 11. Build Sequence

**Phase A — Shell + editor.**
- `sandbox.html` skeleton with fonts, tokens, body grain.
- `sbInit()` stub, session token check, backend probe.
- Header bar with brand + session badge + reset button.
- Two-panel workspace grid (editor left, stage right).
- `sbRenderPrincipals()` + `sbRenderPrincipalCard()` collapsed.
- Card expand/collapse with max-height transition.
- Identity / Calendar / Policy / Reasoner sub-sections.
- `sbUpsertPrincipal()` + `sbDeletePrincipal()`.
- `sbPersistSession()` with API key sanitization.
- Three default principals seeded.

**Phase B — Request form.**
- All form fields with labels + validation.
- Sender/recipient sync (can't pick same).
- Fire button disabled states.
- `sbFireRequest()` stub (offline animation mode first).

**Phase C — Visualization (animation mode).**
- Stage idle placeholder.
- `sbRenderRun()` for 2-party with scripted fake RunResult.
- `sbNarrativeBeat()`, `sbDialogueAppend()`, `sbAppendExchangeBadge()`.
- `sbAnimateCalendars()`.
- Tessera-fit overlay.
- Extend to 3-party.
- 4+-party graceful degradation banner.
- Step indicator generation.
- `sbRenderAbort()` + abort banner.

**Phase D — Backend wiring.**
- POST `/sandbox/session`, store token, DELETE on reset.
- `sbFireRequest()` backend path: serialize principals + inject API keys + POST `/sandbox/.../run`.
- Test 2 scripted, 1 scripted + 1 LLM, offline fallback.

**Phase E — Polish + edge cases.**
- API key session-only verification: grep DOM/console/localStorage for any leak.
- Max principal guard (6).
- Max event guard (10 per principal).
- `innerHTML` audit (zero matches in dynamic content paths).
- Responsive: stacked below 1100px.
- Keyboard accessibility.
- Optional: extract default principals to `sandbox-demo-data.json`.

---

*End of MeshyCal Sandbox Frontend Design Spec.*

*Parallel spec: `SANDBOX_BACKEND_DESIGN.md` defines the actual request/response shapes. Reconcile §10 against it before beginning Phase D.*

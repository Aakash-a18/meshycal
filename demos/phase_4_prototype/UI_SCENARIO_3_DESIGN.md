# UI Scenario 3 Design — Cascading Reschedule with Agent Reasoning

**File:** `MeshyCal/demos/phase_4_prototype/UI_SCENARIO_3_DESIGN.md`
**Implements:** Tab 3 of the scenario switcher in `index.html`.
**Hard constraint:** `index.html` is not modified by the spec author. All additions are made by the implementing agent.
**Namespace discipline:** All IDs added for scenario 3 carry the prefix `s3-`. Avoids collision with scenario 1 (no prefix) and Track B (`s2-`).

---

## 1. Goal

When the user clicks tab 3 ("iii. Cascading reschedule") and presses "Request meeting", they witness a three-party negotiation where Marius' scheduling agent makes an autonomous decision mid-flight. Iris asks for Marius' 14:00 slot. Marius' agent detects that 14:00 is blocked by a meeting with Atlas, silently reasons about whether it can free the slot, then — while Iris is waiting — negotiates a reschedule with Atlas before returning acceptance to Iris. Three signed bilateral tessera fits, two distinct A2A task IDs.

The brand-defining beat is the "agent reasoning..." pause. After Iris' proposal arrives at Marius, the UI enters a deliberate visual hold: a spinner appears inside Marius' column under the label "agent reasoning...", the cascade flow arrow from Iris is complete but the arrow to Atlas has not yet drawn, and the reasoning trace panel begins filling in — first the key-value fields, then the full `reason` text. This pause lasts ~3 seconds wall time. It is the moment that communicates agentic behavior.

The reasoning trace panel is the demonstrable feature. It must remain fully visible throughout the run and after completion. Not a tooltip, not collapsible. Permanent panel inside Marius' column.

---

## 2. Stage Layout

Self-contained block inside `<div data-scenario-content="3">`. Does not share DOM nodes with scenario 1's stage.

### Column proportions

```
grid-template-columns: 1fr 1.6fr 1fr
```

Iris (left, 1 unit) · Marius (center, 1.6 units) · Atlas (right, 1 unit). Center is wider for: Marius' 3-event calendar, the reasoning trace panel, the 4-entry ledger, the exchange badge strip.

### ASCII layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [TESSERA-FIT OVERLAY — s3-tesseraFit — position:absolute, inset:0, z:10]   │
├─────────────────┬──────────────────────────────────┬─────────────────────────┤
│  IRIS           │  MARIUS (wider)                  │  ATLAS                  │
│  .party.left    │  .party.center                   │  .party.right           │
│                 │                                  │                         │
│  [avatar I]     │  [avatar M, halo at step 3]      │  [avatar A]             │
│  [calendar]     │  [calendar - 14:00 BLOCKING]     │  [calendar — empty]     │
│  [scoped        │                                  │                         │
│   payload]      │  [reasoning trace panel]         │  [payload panels]       │
│                 │  [exchange badges A B C]         │                         │
│                 │  [marius reschedule payload]     │                         │
├─────────────────┴──────────────────────────────────┴─────────────────────────┤
│  [s3-task-id-bar]  task_id_1: ... · task_id_2: ...                           │
├──────────────────────────────────────────────────────────────────────────────┤
│  [s3-stepIndicator — 8 steps including the reasoning pause]                  │
├──────────────────────────────────────────────────────────────────────────────┤
│  [s3-run-controls]                                                           │
├─────────────────┬──────────────────────────────────┬─────────────────────────┤
│  IRIS LEDGER    │  MARIUS LEDGER (4 entries)       │  ATLAS LEDGER           │
└─────────────────┴──────────────────────────────────┴─────────────────────────┘
```

---

## 3. Step Indicator — 8 steps

`id="s3-stepIndicator"`. Each step has `data-step="N"`.

| Step | .n | Label | Notes |
|------|-----|-------|-------|
| 1 | i. | Iris builds proposal | |
| 2 | ii. | Iris→Marius scoped | Arrow 1 draws |
| 3 | iii. | Agent reasoning… | `s3-step-pause` class; gold pulse; reasoning panel populates |
| 4 | iv. | Marius→Atlas | Arrow 3 draws; spinner stops |
| 5 | v. | Atlas accepts · B sealed | Arrow 4 draws; Exchange B badge |
| 6 | vi. | Marius→Iris acceptance | Arrow 5 draws; Exchange A and C badges; task IDs |
| 7 | vii. | Three fits · receipts | Final tessera overlay; ledgers populate |
| 8 | viii. | Calendars updated | Three calendar deltas animate |

Step 3 is visually distinguished: gold pulsing border via `s3StepPausePulse`.

---

## 4. Reasoning Trace Panel

### Purpose

Central demonstrable feature. Shows `reasoner_trace` verbatim in IBM Plex Mono. Never hidden or collapsed.

### DOM

Inside `.party.center`, between calendar and reschedule-payload section.
- `id="s3-reasoning-trace"`, class `.s3-reasoning-trace`
- Initial: `visibility: hidden; opacity: 0`. Activated by adding `.s3-reasoning-trace--visible`.

### Structure

```html
<div id="s3-reasoning-trace" class="s3-reasoning-trace" aria-live="polite">
  <div class="s3-trace-header">
    <span class="s3-trace-eyebrow">agent reasoning…</span>
    <span class="s3-trace-spinner s3-trace-spinner--active" id="s3-trace-spinner"></span>
  </div>
  <div class="s3-trace-fields" id="s3-trace-fields"><!-- 4 rows: requested_slot, blocking_event_title, blocking_event_attendee, proposed_new_slot --></div>
  <div class="s3-trace-reason-label">reason</div>
  <pre class="s3-trace-reason" id="s3-trace-reason">— awaiting —</pre>
</div>
```

### Field row format

```html
<div class="s3-trace-field">
  <span class="s3-tf-key">requested_slot</span>
  <span class="s3-tf-val">2026-06-02T14:00:00Z</span>
</div>
```

Each row appended via `s3AppendTraceField()` with staggered delays (0, 200, 400, 600ms). After 800ms total, `reason` text is set verbatim.

### Spinner

Visible by default with `.s3-trace-spinner--active`. `s3StopReasoningSpinner()` removes the active class at step 4 and updates eyebrow text to "agent reasoning — complete".

---

## 5. Cascade Flow Arrows

Five arrows as absolutely-positioned SVG paths inside an `s3-arrows-layer` SVG overlay on the stage.

| Arrow | ID | Activated at | Duration | Direction label |
|-------|-----|--------------|----------|-----------------|
| 1 | `s3-arrow-iris-marius` | Step 2 | 500ms | "proposal →" |
| (halo on avatar) | n/a | Step 3 | continuous | (pulse around Marius avatar via `s3-avatar-reasoning`) |
| 3 | `s3-arrow-marius-atlas` | Step 4 | 500ms | "→ reschedule proposal" |
| 4 | `s3-arrow-atlas-marius` | Step 5 | 500ms | "← acceptance" |
| 5 | `s3-arrow-marius-iris` | Step 6 | 500ms | "← acceptance" |

Each is a `<path>` with stroke-dasharray draw animation. Class `.s3-arrow--active` reveals.

Arrows persist after activation (do not fade out) until `s3Reset()`.

**Implementer's choice for positioning:** SVG `viewBox="0 0 1000 100"` is abstract; coordinates depend on rendered widths. Acceptable alternative: use `<div>` elements with `position:absolute; border-top: 1.5px solid var(--gold)` and CSS ::after arrowhead, sized via JS using `getBoundingClientRect()`. Simpler for cross-browser.

---

## 6. Tessera-Fit Handling — Three Exchanges

**Recommendation: inline exchange badges + one final full-screen overlay.**

Three full-screen overlays back-to-back would feel mechanical and bury the reasoning trace. Instead:

- Three inline badges (52×52 SVG tessera halves + seam) for exchanges A, B, C in a flex row inside Marius' column.
- One final full-screen `#s3-tesseraFit` overlay with verdict "three fits · cascade complete · trust verified" at step 7.

### Badge structure

```html
<div id="s3-exchange-badges" class="s3-exchange-badges">
  <div class="s3-exchange-badge" data-exchange="A">
    <svg class="s3-badge-svg" viewBox="0 0 52 72" aria-hidden="true">
      <path d="..." fill="#c8b89d"/>   <!-- left half -->
      <path d="..." fill="#b88467"/>   <!-- right half -->
      <line class="s3-badge-seam" x1="26" y1="8" x2="26" y2="64"/>
    </svg>
    <div class="s3-badge-meta">
      <div class="s3-badge-label">Exchange A</div>
      <div class="s3-badge-principals">I · M</div>
      <div class="s3-badge-hash">prop: <span class="hash-val">abc123…</span></div>
      <div class="s3-badge-hash">acpt: <span class="hash-val">def456…</span></div>
      <div class="s3-badge-taskid">task_id_1</div>
    </div>
  </div>
  <!-- B, C similar -->
</div>
```

Badge entrance: `animation: s3BadgeEnter 600ms cubic-bezier(0.34, 1.4, 0.6, 1) forwards`.
Seam reveal: 700ms `stroke-dashoffset` transition with 400ms delay after badge enters.

### Final overlay

`id="s3-tesseraFit"` — distinct from scenario 1's `id="tesseraFit"`. Same DOM structure. SVG gradient IDs use `s3-halfL` / `s3-halfR` to avoid collision with `halfL` / `halfR`. Reuses all existing `.tessera-fit-overlay`, `.tessera-half-l/r`, `.tessera-seam`, `.verdict` styles and `slideInL/R`, `seamGrow`, `fadeIn`, `fadeInLate` keyframes.

Verdict text static: `three fits  ·  cascade complete  ·  trust verified`.

Activated at step 7. Stays 2800ms. Then step 8.

---

## 7. Two A2A Task ID Display

Horizontal bar `id="s3-task-id-bar"` between stage and step indicator.

```css
.s3-task-id-bar {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  color: hsl(40 25% 55%);
  background: hsl(220 22% 6%);
  border: 1px solid hsl(220 18% 18%);
  border-top: none;
  padding: 10px 18px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  min-height: 36px;
}
```

Initial placeholder: "task IDs will appear when the cascade completes" in `<span class="s3-taskid-placeholder">`.

After cascade, populated via `s3PopulateTaskIds(task_id_1, task_id_2)`:

```html
<span class="s3-taskid-group">
  <span class="s3-taskid-exlabels">exchanges A + C</span>
  <span class="s3-taskid-key">task_id_1: </span>
  <span class="s3-taskid-val" title="<full>">abcdef012345678…</span>
</span>
<span class="s3-taskid-sep">·</span>
<span class="s3-taskid-group">
  <span class="s3-taskid-exlabels">exchange B</span>
  <span class="s3-taskid-key">task_id_2: </span>
  <span class="s3-taskid-val" title="<full>">9f3c7b2a4e1d…</span>
</span>
```

`.s3-taskid-key` → `hsl(40 50% 65%)`. `.s3-taskid-val` → `var(--gold)`. `.s3-taskid-exlabels` → `hsl(40 20% 50%)`.

---

## 8. Calendar Updates Across Three Principals

### Initial state

**Iris (`s3-cal-iris`):**
- 09:00 synthetic-morning-standup (60 min)
- 11:00 synthetic-focus-block (30 min)

**Marius (`s3-cal-marius`):**
- 10:00 synthetic-weekly-review (60 min)
- 14:00 synthetic-project-sync (45 min) — `data-slot="s3-marius-1400"` `class="event s3-blocking"`
- 15:30 synthetic-1-on-1 (30 min)

**Atlas (`s3-cal-atlas`):**
- Single placeholder `.event.free.s3-cal-atlas-empty`: "no events yet · atlas' internal calendar not modeled in v0"

### Transition at step 8

**`s3MoveSlot()`** — Marius 14:00 → 16:00:
1. Find `[data-slot="s3-marius-1400"]`, add class `s3-slot-moving-out` (opacity 0.15, strikethrough title, terracotta tint), 400ms transition.
2. After 420ms: remove from DOM. Insert new 16:00 event with `data-slot="s3-marius-1600"`, class `s3-slot-appearing`.
3. requestAnimationFrame → class `s3-slot-appeared` (opacity 1, jade left border, 500ms transition).

**`s3GainSlot(calId, slotId, time, title, attendees)`** — used for Iris 14:00 and Atlas 16:00:
1. Append `.event.s3-slot-appearing.booked` to the calendar (opacity 0).
2. requestAnimationFrame → `.s3-slot-appeared` (opacity 1, jade left border).

### Timing within step 8

| ms | action |
|------|--------|
| 0 | `s3MoveSlot` begins |
| 420 | Marius 16:00 appears (`s3GainSlot('s3-cal-marius', 's3-marius-1600', ...)`) |
| 500 | Iris 14:00 appears |
| 900 | Atlas 16:00 appears (after removing the empty placeholder) |
| 1400 | done; status updated |

---

## 9. HTML Additions

### 9.1 Wrapper

After existing scenario-1 markup (which must be wrapped in `<div data-scenario-content="1">`), add:

```html
<div data-scenario-content="3" style="display:none;">
  <!-- s3-stage, s3-task-id-bar, s3-stepIndicator, s3-run-controls, s3-ledger-block -->
</div>
```

### 9.2 Scenario-3 stage element

Top-level container:

```html
<div class="stage s3-stage" id="s3-stage">

  <!-- final tessera overlay -->
  <div class="tessera-fit-overlay" id="s3-tesseraFit">
    <div class="glyph">
      <svg class="tessera-half-l" viewBox="0 0 200 280" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <radialGradient id="s3-halfL" cx="60%" cy="35%" r="90%">
            <stop offset="0%" stop-color="#e0d4bf"/>
            <stop offset="100%" stop-color="#8a7456"/>
          </radialGradient>
        </defs>
        <path d="M 200 0 L 200 280 L 100 280 C 60 268, 30 230, 16 168 C 20 110, 50 56, 96 24 C 130 4, 170 0, 200 0 Z" fill="url(#s3-halfL)"/>
      </svg>
      <svg class="tessera-half-r" viewBox="0 0 200 280" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <radialGradient id="s3-halfR" cx="40%" cy="60%" r="90%">
            <stop offset="0%" stop-color="#d4a991"/>
            <stop offset="100%" stop-color="#6e4733"/>
          </radialGradient>
        </defs>
        <path d="M 0 0 L 0 280 L 100 280 C 140 268, 170 230, 184 168 C 180 110, 150 56, 104 24 C 70 4, 30 0, 0 0 Z" fill="url(#s3-halfR)"/>
      </svg>
      <div class="tessera-seam"></div>
    </div>
    <div class="verdict" id="s3-tesseraFit-verdict">three fits  ·  cascade complete  ·  trust verified</div>
  </div>

  <!-- IRIS -->
  <div class="party left">
    <div class="who">
      <div class="avatar">I</div>
      <div>
        <div class="name">Iris</div>
        <div class="id">iris@meshycal.demo</div>
      </div>
    </div>
    <div class="panel-label">iris' calendar — june 2</div>
    <div class="calendar" id="s3-cal-iris">
      <div class="event"><span class="time">09:00</span><div><div class="title">synthetic-morning-standup</div><div class="attendees">60 min · solo</div></div></div>
      <div class="event"><span class="time">11:00</span><div><div class="title">synthetic-focus-block</div><div class="attendees">30 min · solo</div></div></div>
      <!-- 14:00 slot appended at step 8 -->
    </div>
    <div class="panel-label">iris' scoped proposal — outbound</div>
    <div class="s3-payload-panel" id="s3-payload-iris">
      <div class="s3-pp-row"><span class="s3-pp-k">candidates</span><span class="s3-pp-v">["2026-06-02T14:00:00Z"]</span></div>
      <div class="s3-pp-row"><span class="s3-pp-k">duration_minutes</span><span class="s3-pp-v">30</span></div>
      <div class="s3-pp-row s3-pp-blocked"><span class="s3-pp-k">calendar_titles</span><span class="s3-pp-v">blocked ✕</span></div>
      <div class="s3-pp-row s3-pp-blocked"><span class="s3-pp-k">attendee_emails</span><span class="s3-pp-v">blocked ✕</span></div>
      <div class="s3-pp-row"><span class="s3-pp-k">constraint_hints</span><span class="s3-pp-v">{tz: "Europe/Paris"}</span></div>
      <div class="s3-pp-hash" id="s3-iris-proposal-hash">— hash pending —</div>
    </div>
  </div>

  <!-- flow arrows layer; positioned absolutely over the stage -->
  <svg class="s3-arrows-layer" id="s3-arrows-layer" viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true">
    <defs>
      <marker id="s3-arrowhead" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
        <path d="M 0 0 L 6 3 L 0 6" stroke="var(--gold)" stroke-width="1.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
      </marker>
    </defs>
    <path id="s3-arrow-iris-marius" class="s3-arrow" d="M 290 50 L 440 50" marker-end="url(#s3-arrowhead)"/>
    <path id="s3-arrow-marius-atlas" class="s3-arrow" d="M 560 35 L 710 35" marker-end="url(#s3-arrowhead)"/>
    <path id="s3-arrow-atlas-marius" class="s3-arrow" d="M 710 55 L 560 55" marker-end="url(#s3-arrowhead)"/>
    <path id="s3-arrow-marius-iris" class="s3-arrow" d="M 440 65 L 290 65" marker-end="url(#s3-arrowhead)"/>
  </svg>

  <!-- MARIUS -->
  <div class="party center">
    <div class="who">
      <div class="avatar s3-avatar-marius" id="s3-avatar-marius">M</div>
      <div>
        <div class="name">Marius</div>
        <div class="id">marius@meshycal.demo</div>
      </div>
    </div>
    <div class="panel-label">marius' calendar — june 2</div>
    <div class="calendar" id="s3-cal-marius">
      <div class="event"><span class="time">10:00</span><div><div class="title">synthetic-weekly-review</div><div class="attendees">60 min · solo</div></div></div>
      <div class="event s3-blocking" data-slot="s3-marius-1400"><span class="time">14:00</span><div><div class="title">synthetic-project-sync</div><div class="attendees">45 min · atlas</div></div></div>
      <div class="event"><span class="time">15:30</span><div><div class="title">synthetic-1-on-1</div><div class="attendees">30 min · solo</div></div></div>
      <!-- 16:00 slot appended at step 8 -->
    </div>

    <div class="panel-label s3-reasoning-label" id="s3-reasoning-label">marius' agent — awaiting proposal</div>

    <div id="s3-reasoning-trace" class="s3-reasoning-trace" aria-live="polite">
      <div class="s3-trace-header">
        <span class="s3-trace-eyebrow">agent reasoning…</span>
        <span class="s3-trace-spinner s3-trace-spinner--active" id="s3-trace-spinner"></span>
      </div>
      <div class="s3-trace-fields" id="s3-trace-fields"><!-- 4 rows --></div>
      <div class="s3-trace-reason-label">reason</div>
      <pre class="s3-trace-reason" id="s3-trace-reason">— awaiting —</pre>
    </div>

    <div class="panel-label">signed exchanges</div>
    <div id="s3-exchange-badges" class="s3-exchange-badges"><!-- badges A, B, C appended at steps 5, 6 --></div>

    <div class="panel-label">marius' reschedule proposal to atlas</div>
    <div class="s3-payload-panel" id="s3-payload-marius">
      <div class="s3-pp-row s3-pp-pending" id="s3-marius-proposal-pending">— pending reasoning —</div>
    </div>
  </div>

  <!-- ATLAS -->
  <div class="party right">
    <div class="who">
      <div class="avatar s3-avatar-atlas">A</div>
      <div>
        <div class="name">Atlas</div>
        <div class="id">atlas@meshycal.demo</div>
      </div>
    </div>
    <div class="panel-label">atlas' calendar — june 2</div>
    <div class="calendar" id="s3-cal-atlas">
      <div class="event free s3-cal-atlas-empty">
        <span class="time">—</span>
        <div>
          <div class="title">no events yet</div>
          <div class="attendees">atlas' internal calendar not modeled in v0</div>
        </div>
      </div>
    </div>
    <div class="panel-label">what atlas receives</div>
    <div class="s3-payload-panel" id="s3-payload-atlas"><div class="s3-pp-pending">— pending cascade —</div></div>
    <div class="panel-label">atlas' acceptance</div>
    <div class="s3-payload-panel" id="s3-payload-atlas-acceptance"><div class="s3-pp-pending">— pending —</div></div>
  </div>

</div>
```

### 9.3 Task ID bar (after stage)

```html
<div class="s3-task-id-bar" id="s3-task-id-bar">
  <span class="s3-taskid-placeholder" id="s3-taskid-placeholder">task IDs will appear when the cascade completes</span>
</div>
```

### 9.4 Step indicator

```html
<div class="step-indicator" id="s3-stepIndicator">
  <div class="step" data-step="1"><span class="n">i.</span> Iris builds proposal</div>
  <div class="step" data-step="2"><span class="n">ii.</span> Iris→Marius scoped</div>
  <div class="step s3-step-pause" data-step="3"><span class="n">iii.</span> Agent reasoning…</div>
  <div class="step" data-step="4"><span class="n">iv.</span> Marius→Atlas</div>
  <div class="step" data-step="5"><span class="n">v.</span> Atlas accepts · B sealed</div>
  <div class="step" data-step="6"><span class="n">vi.</span> Marius→Iris acceptance</div>
  <div class="step" data-step="7"><span class="n">vii.</span> Three fits · receipts</div>
  <div class="step" data-step="8"><span class="n">viii.</span> Calendars updated</div>
</div>
```

### 9.5 Run controls

```html
<div class="run-controls">
  <button id="s3-runBtn">Request meeting</button>
  <button id="s3-resetBtn" class="ghost">Reset</button>
  <div class="status" id="s3-runStatus">ready — press to begin</div>
</div>
```

`backendStatus` is a shared element — reuse the existing one in the page; scenario 3 just reads the shared `backendOk` from the IIFE scope.

### 9.6 Three-column ledger block

```html
<div class="s3-ledger-block">
  <div class="ledger" id="s3-ledgerIris">
    <div class="ledger-head">
      <div class="who">Iris' book</div>
      <div class="label">ledger_owner: iris@meshycal.demo</div>
    </div>
    <div class="ledger-body" id="s3-ledgerBodyIris"></div>
  </div>
  <div class="ledger" id="s3-ledgerMarius">
    <div class="ledger-head">
      <div class="who">Marius' book</div>
      <div class="label">ledger_owner: marius@meshycal.demo</div>
    </div>
    <div class="ledger-body" id="s3-ledgerBodyMarius"></div>
  </div>
  <div class="ledger" id="s3-ledgerAtlas">
    <div class="ledger-head">
      <div class="who">Atlas' book</div>
      <div class="label">ledger_owner: atlas@meshycal.demo</div>
    </div>
    <div class="ledger-body" id="s3-ledgerBodyAtlas"></div>
  </div>
</div>
```

---

## 10. CSS Additions

All inside the existing `<style>` block, after all existing rules, before `</style>`. Comment block: `/* SCENARIO 3 */`.

### Stage grid

```css
.s3-stage { grid-template-columns: 1fr 1.6fr 1fr; }
```

### Center party

```css
.party.center {
  border-left: 1px solid hsl(220 18% 22%);
  border-right: 1px solid hsl(220 18% 22%);
}
.party.center .avatar { background: var(--jade); color: var(--paper); }
```

### Blocking event highlight

```css
.s3-blocking {
  border-left: 3px solid var(--terracotta);
  background: hsl(13 25% 11%);
}
.s3-blocking .time { color: var(--terracotta); }
.s3-blocking .title { color: hsl(13 50% 75%); font-style: italic; }
```

### Reasoning trace panel

```css
.s3-reasoning-trace {
  border: 1px solid hsl(40 25% 28% / 0.6);
  background: hsl(222 28% 9%);
  padding: 16px 18px;
  font-family: var(--mono);
  font-size: 11.5px;
  visibility: hidden;
  opacity: 0;
  transition: opacity 400ms ease, visibility 0s linear 400ms;
  position: relative;
}
.s3-reasoning-trace::before {
  content: "REASONING TRACE";
  position: absolute;
  top: -8px; left: 14px;
  background: hsl(222 28% 9%);
  padding: 0 8px;
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.24em;
  color: hsl(40 25% 55%);
}
.s3-reasoning-trace--visible {
  visibility: visible;
  opacity: 1;
  transition: opacity 400ms ease;
}

.s3-trace-header { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.s3-trace-eyebrow {
  font-size: 10px; letter-spacing: 0.22em; text-transform: uppercase;
  color: hsl(40 25% 55%);
}
.s3-trace-spinner {
  display: inline-block; width: 12px; height: 12px;
  border: 1.5px solid hsl(40 70% 53% / 0.3);
  border-top-color: var(--gold);
  border-radius: 50%;
  opacity: 0;
}
.s3-trace-spinner--active { opacity: 1; animation: s3SpinnerRotate 800ms linear infinite; }
@keyframes s3SpinnerRotate { to { transform: rotate(360deg); } }

.s3-trace-fields { margin-bottom: 14px; }
.s3-trace-field {
  display: flex; gap: 10px; margin: 4px 0;
  opacity: 0; transform: translateY(4px);
  transition: opacity 300ms ease, transform 300ms ease;
}
.s3-trace-field--visible { opacity: 1; transform: translateY(0); }
.s3-tf-key { color: hsl(40 20% 55%); width: 190px; flex-shrink: 0; font-size: 11px; }
.s3-tf-val { color: hsl(40 60% 78%); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.s3-trace-reason-label {
  font-size: 9px; letter-spacing: 0.22em; text-transform: uppercase;
  color: hsl(40 20% 50%);
  margin-bottom: 8px; border-top: 1px solid hsl(220 18% 22%); padding-top: 10px;
}
.s3-trace-reason {
  font-family: var(--mono); font-size: 11px; line-height: 1.7;
  color: hsl(40 30% 72%);
  white-space: pre-wrap; word-break: break-word;
  margin: 0; background: transparent; border: none; padding: 0;
}
```

### Step 3 pause styling

```css
.s3-step-pause.active {
  background: hsl(222 28% 11%);
  border: 1px solid hsl(40 50% 30% / 0.5);
  animation: s3StepPausePulse 1.8s ease-in-out infinite;
}
.s3-step-pause.active .n { color: var(--gold); }
@keyframes s3StepPausePulse {
  0%, 100% { border-color: hsl(40 50% 30% / 0.5); box-shadow: none; }
  50%      { border-color: hsl(40 70% 53% / 0.4); box-shadow: 0 0 8px hsl(40 70% 53% / 0.12); }
}
```

### Avatar reasoning halo

```css
@keyframes s3ReasoningHalo {
  0%, 100% { box-shadow: 0 0 0 0 hsl(40 70% 53% / 0); }
  50%      { box-shadow: 0 0 0 8px hsl(40 70% 53% / 0.15); }
}
.s3-avatar-reasoning { animation: s3ReasoningHalo 1.4s ease-in-out infinite; }
```

### Flow arrows

```css
.s3-arrows-layer {
  position: absolute; inset: 0; width: 100%; height: 100%;
  pointer-events: none; z-index: 2; overflow: visible;
}
.s3-arrow {
  stroke: var(--gold); stroke-width: 1.5; fill: none;
  stroke-linecap: round;
  stroke-dasharray: 200; stroke-dashoffset: 200;
  opacity: 0;
  transition: stroke-dashoffset 500ms cubic-bezier(0.4, 0, 0.2, 1), opacity 200ms ease;
}
.s3-arrow.s3-arrow--active { stroke-dashoffset: 0; opacity: 0.85; }
```

### Exchange badges

```css
.s3-exchange-badges { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 4px; }
.s3-exchange-badge {
  display: flex; gap: 10px; align-items: flex-start;
  border: 1px solid hsl(220 18% 24%);
  background: hsl(220 22% 9%);
  padding: 10px 12px;
  opacity: 0; transform: translateY(8px) scale(0.96);
}
.s3-exchange-badge--entering { animation: s3BadgeEnter 600ms cubic-bezier(0.34, 1.4, 0.6, 1) forwards; }
@keyframes s3BadgeEnter { to { opacity: 1; transform: translateY(0) scale(1); } }
.s3-badge-svg { width: 52px; height: 52px; flex-shrink: 0; }
.s3-badge-meta { font-family: var(--mono); font-size: 10px; line-height: 1.6; display: flex; flex-direction: column; gap: 2px; }
.s3-badge-label { color: var(--gold); letter-spacing: 0.14em; text-transform: uppercase; font-size: 10px; font-weight: 500; }
.s3-badge-principals { color: hsl(40 25% 65%); }
.s3-badge-hash { color: hsl(40 15% 55%); font-size: 9.5px; }
.s3-badge-hash .hash-val { color: hsl(40 30% 65%); }
.s3-badge-taskid { color: hsl(155 30% 55%); font-size: 9px; letter-spacing: 0.1em; margin-top: 4px; }

.s3-badge-svg .s3-badge-seam {
  stroke: var(--gold); stroke-width: 1.5;
  stroke-dasharray: 60; stroke-dashoffset: 60;
  filter: drop-shadow(0 0 4px hsl(40 70% 55% / 0.5));
}
.s3-badge-svg--seam-active .s3-badge-seam {
  transition: stroke-dashoffset 700ms ease 400ms;
  stroke-dashoffset: 0;
}
```

### Payload panels

```css
.s3-payload-panel {
  font-family: var(--mono); font-size: 11px; color: hsl(40 25% 65%);
  display: flex; flex-direction: column; gap: 3px; padding: 8px 0;
}
.s3-pp-row { display: flex; gap: 12px; justify-content: space-between; }
.s3-pp-k { color: hsl(40 20% 55%); }
.s3-pp-v { color: hsl(40 35% 70%); text-align: right; }
.s3-pp-blocked .s3-pp-k { color: hsl(13 40% 50%); }
.s3-pp-blocked .s3-pp-v { color: hsl(13 40% 50%); }
.s3-pp-pending { color: hsl(40 15% 45%); font-style: italic; }
.s3-pp-hash { font-size: 9.5px; color: hsl(40 15% 45%); margin-top: 4px; letter-spacing: 0.04em; }
.s3-pp-hash.s3-pp-hash--real { color: var(--jade); }
```

### Calendar move animations

```css
.s3-slot-moving-out {
  transition: opacity 400ms ease, background 400ms ease;
  opacity: 0.15; background: hsl(13 30% 16%);
}
.s3-slot-moving-out .title { text-decoration: line-through; }
.s3-slot-moving-out .time { color: hsl(13 40% 45%); }

.s3-slot-appearing { opacity: 0; transition: opacity 500ms ease; }
.s3-slot-appeared { opacity: 1; border-left: 3px solid var(--jade); }
```

### Three-column ledger block

```css
.s3-ledger-block {
  display: grid;
  grid-template-columns: 1fr 1.4fr 1fr;
  gap: 24px;
  margin-top: 48px;
}
```

### Abort banner

```css
.s3-abort-banner {
  border: 1px solid var(--terracotta-deep);
  background: hsl(13 40% 10%);
  color: hsl(13 50% 70%);
  font-family: var(--mono); font-size: 12px;
  padding: 20px 24px; margin-top: 24px;
  position: relative;
}
.s3-abort-banner::before {
  content: "CASCADE ABORTED";
  display: block; font-size: 9px; letter-spacing: 0.28em; text-transform: uppercase;
  color: var(--terracotta); margin-bottom: 10px;
}
.s3-abort-banner .s3-abort-reason { line-height: 1.65; color: hsl(13 45% 65%); }
```

### Responsive

```css
@media (max-width: 1080px) {
  .s3-stage { grid-template-columns: 1fr; }
  .s3-ledger-block { grid-template-columns: 1fr; }
  .party.center { border: none; border-bottom: 1px solid hsl(220 18% 22%); }
  .s3-exchange-badges { flex-direction: column; }
  .s3-arrows-layer { display: none; }
}
```

---

## 11. JavaScript Runner

### Scope

Extend the existing IIFE. Add s3 helpers after `runScenario1`.

### Element refs

```js
const s3RunBtn       = $("s3-runBtn");
const s3ResetBtn     = $("s3-resetBtn");
const s3RunStatus    = $("s3-runStatus");
const s3StepInd      = $("s3-stepIndicator");
const s3TesseraFit   = $("s3-tesseraFit");
const s3TracePanel   = $("s3-reasoning-trace");
const s3TraceFields  = $("s3-trace-fields");
const s3TraceReason  = $("s3-trace-reason");
const s3TraceSpinner = $("s3-trace-spinner");
const s3BadgesEl     = $("s3-exchange-badges");
const s3TaskIdBar    = $("s3-task-id-bar");
const s3LedgerIris   = $("s3-ledgerBodyIris");
const s3LedgerMarius = $("s3-ledgerBodyMarius");
const s3LedgerAtlas  = $("s3-ledgerBodyAtlas");
```

### `s3SetStep(n)` / `s3SetStatus(msg)` / `fetchCascading()`

```js
function s3SetStep(n) {
  s3StepInd.querySelectorAll(".step").forEach((el) => {
    const s = parseInt(el.dataset.step, 10);
    el.classList.toggle("active", s === n);
    el.classList.toggle("done",   s < n);
  });
}
function s3SetStatus(msg) { s3RunStatus.textContent = msg; }

async function fetchCascading() {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 20000);
  try {
    const res = await fetch(API_BASE + "/scenarios/cascading/run", {
      method: "POST",
      signal: ctrl.signal,
      headers: { "content-type": "application/json" },
    });
    clearTimeout(t);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw Object.assign(new Error("cascade-failed"), { detail: body.detail || "" });
    }
    return await res.json();
  } finally {
    clearTimeout(t);
  }
}
```

### Trace helpers

```js
function s3AppendTraceField(key, value, delayMs) {
  const row = elem("div", { className: "s3-trace-field" });
  row.appendChild(elem("span", { className: "s3-tf-key", text: key }));
  row.appendChild(elem("span", { className: "s3-tf-val", text: value }));
  s3TraceFields.appendChild(row);
  setTimeout(() => row.classList.add("s3-trace-field--visible"), delayMs);
}

function s3ShowReasoningTrace(trace) {
  s3TracePanel.classList.add("s3-reasoning-trace--visible");
  s3AppendTraceField("requested_slot",          trace.requested_slot,          0);
  s3AppendTraceField("blocking_event_title",    trace.blocking_event_title,    200);
  s3AppendTraceField("blocking_event_attendee", trace.blocking_event_attendee, 400);
  s3AppendTraceField("proposed_new_slot",       trace.proposed_new_slot,       600);
  setTimeout(() => { s3TraceReason.textContent = trace.reason; }, 800);
}

function s3StopReasoningSpinner() {
  s3TraceSpinner.classList.remove("s3-trace-spinner--active");
  const eyebrow = s3TracePanel.querySelector(".s3-trace-eyebrow");
  if (eyebrow) eyebrow.textContent = "agent reasoning — complete";
  const avatarEl = $("s3-avatar-marius");
  if (avatarEl) avatarEl.classList.remove("s3-avatar-reasoning");
}
```

### Badge helper

```js
function s3AppendExchangeBadge(label, init, resp, propHash, acptHash, taskIdLabel) {
  const badge = elem("div", { className: "s3-exchange-badge" });
  badge.dataset.exchange = label;

  // Miniature tessera SVG
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 52 72");
  svg.setAttribute("class", "s3-badge-svg");
  const pathL = document.createElementNS(ns, "path");
  pathL.setAttribute("d", "M 26 2 C 22 4, 19 12, 18 22 L 18 36 L 16 44 L 19 52 L 17 60 L 18 68 L 26 70 L 26 2 Z");
  pathL.setAttribute("fill", "#c8b89d");
  const pathR = document.createElementNS(ns, "path");
  pathR.setAttribute("d", "M 26 2 L 26 70 L 34 68 L 35 60 L 33 52 L 36 44 L 34 36 L 34 22 C 33 12, 30 4, 26 2 Z");
  pathR.setAttribute("fill", "#b88467");
  const seam = document.createElementNS(ns, "line");
  seam.setAttribute("x1", "26"); seam.setAttribute("y1", "8");
  seam.setAttribute("x2", "26"); seam.setAttribute("y2", "64");
  seam.setAttribute("class", "s3-badge-seam");
  svg.appendChild(pathL); svg.appendChild(pathR); svg.appendChild(seam);

  const meta = elem("div", { className: "s3-badge-meta" });
  meta.appendChild(elem("div", { className: "s3-badge-label", text: "Exchange " + label }));
  meta.appendChild(elem("div", { className: "s3-badge-principals", text: init + " · " + resp }));

  const ph = elem("div", { className: "s3-badge-hash" });
  ph.appendChild(document.createTextNode("prop: "));
  ph.appendChild(elem("span", { className: "hash-val", text: propHash.slice(0, 12) + "…" }));
  meta.appendChild(ph);

  const ah = elem("div", { className: "s3-badge-hash" });
  ah.appendChild(document.createTextNode("acpt: "));
  ah.appendChild(elem("span", { className: "hash-val", text: acptHash.slice(0, 12) + "…" }));
  meta.appendChild(ah);

  meta.appendChild(elem("div", { className: "s3-badge-taskid", text: taskIdLabel }));

  badge.appendChild(svg);
  badge.appendChild(meta);
  s3BadgesEl.appendChild(badge);

  requestAnimationFrame(() => badge.classList.add("s3-exchange-badge--entering"));
  setTimeout(() => svg.classList.add("s3-badge-svg--seam-active"), 600);
}
```

### Task ID populator

```js
function s3PopulateTaskIds(t1, t2) {
  clearChildren(s3TaskIdBar);
  const g1 = elem("span", { className: "s3-taskid-group" });
  g1.appendChild(elem("span", { className: "s3-taskid-exlabels", text: "exchanges A + C  " }));
  g1.appendChild(elem("span", { className: "s3-taskid-key", text: "task_id_1: " }));
  const v1 = elem("span", { className: "s3-taskid-val", text: t1.slice(0, 16) + "…" });
  v1.title = t1;
  g1.appendChild(v1);
  const sep = elem("span", { className: "s3-taskid-sep", text: " · " });
  const g2 = elem("span", { className: "s3-taskid-group" });
  g2.appendChild(elem("span", { className: "s3-taskid-exlabels", text: "exchange B  " }));
  g2.appendChild(elem("span", { className: "s3-taskid-key", text: "task_id_2: " }));
  const v2 = elem("span", { className: "s3-taskid-val", text: t2.slice(0, 16) + "…" });
  v2.title = t2;
  g2.appendChild(v2);
  s3TaskIdBar.appendChild(g1);
  s3TaskIdBar.appendChild(sep);
  s3TaskIdBar.appendChild(g2);
}
```

### Calendar helpers

```js
function s3MoveSlot() {
  const slot = document.querySelector('[data-slot="s3-marius-1400"]');
  if (!slot) return;
  slot.classList.add("s3-slot-moving-out");
  setTimeout(() => { if (slot.parentNode) slot.parentNode.removeChild(slot); }, 400);
}

function s3GainSlot(calId, slotId, time, title, attendees) {
  const cal = document.getElementById(calId);
  if (!cal) return;
  const ev = elem("div", { className: "event s3-slot-appearing booked" });
  ev.dataset.slot = slotId;
  ev.appendChild(elem("span", { className: "time", text: time }));
  const inner = elem("div");
  inner.appendChild(elem("div", { className: "title", text: title }));
  inner.appendChild(elem("div", { className: "attendees", text: attendees }));
  ev.appendChild(inner);
  cal.appendChild(ev);
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      ev.classList.remove("s3-slot-appearing");
      ev.classList.add("s3-slot-appeared");
    });
  });
}
```

### Animation-mode fallback

```js
const s3FakeHashes = {
  irisEmit:           fakeHash(31),
  mariusReceive:      fakeHash(31),    // same seed → matching halves
  mariusEmitAtlas:    fakeHash(43),
  atlasReceive:       fakeHash(43),
  atlasEmit:          fakeHash(57),
  mariusReceiveAtlas: fakeHash(57),
  mariusEmitIris:     fakeHash(71),
  irisReceive:        fakeHash(71),
  taskId1: "animmode-t1-" + fakeHash(3).slice(0, 20),
  taskId2: "animmode-t2-" + fakeHash(9).slice(0, 20),
};
```

### `runScenario3()` — full step sequence

```js
async function runScenario3() {
  s3RunBtn.disabled = true;
  s3RunBtn.textContent = "Running…";

  let s3Real = null;
  const s3BackendPromise = backendOk
    ? fetchCascading().catch((err) => {
        console.warn("[s3] backend call failed:", err);
        return null;
      })
    : null;

  try {
    // STEP 1
    s3SetStep(1);
    s3SetStatus("step i — Iris builds proposal: 14:00 · 30 min");
    await sleep(1000);

    // STEP 2
    s3SetStep(2);
    s3SetStatus("step ii — Iris→Marius · scoped bytes cross · titles + emails blocked");
    $("s3-arrow-iris-marius").classList.add("s3-arrow--active");
    await sleep(900);

    // STEP 3 — the brand beat
    s3SetStep(3);
    s3SetStatus("step iii — agent reasoning…");
    $("s3-avatar-marius").classList.add("s3-avatar-reasoning");
    $("s3-reasoning-label").textContent = "marius' agent — reasoning…";

    if (s3BackendPromise) s3Real = await s3BackendPromise;

    const trace = s3Real ? s3Real.reasoner_trace : {
      requested_slot: "2026-06-02T14:00:00Z",
      blocking_event_title: "synthetic-project-sync",
      blocking_event_attendee: "atlas@meshycal.demo",
      proposed_new_slot: "2026-06-02T16:00:00Z",
      reason: "busy at requested slot 2026-06-02T14:00:00Z with atlas@meshycal.demo for \"synthetic-project-sync\"; proposing to move that meeting to 2026-06-02T16:00:00Z, which is free on both calendars",
    };
    s3ShowReasoningTrace(trace);
    await sleep(2800);

    // STEP 4
    s3SetStep(4);
    s3StopReasoningSpinner();
    $("s3-reasoning-label").textContent = "marius' agent — dispatching to atlas";
    s3SetStatus("step iv — Marius→Atlas · reschedule proposal dispatched");

    const reschedule = s3Real ? s3Real.marius_reschedule_proposal : {
      candidates: ["2026-06-02T16:00:00Z"],
      duration_minutes: 45,
      constraint_hints: { reason: "synthetic-reschedule-for-new-request" },
    };
    clearChildren($("s3-payload-marius"));
    [["candidates", JSON.stringify(reschedule.candidates)],
     ["duration_minutes", String(reschedule.duration_minutes)],
     ["constraint_hints", JSON.stringify(reschedule.constraint_hints || {})]].forEach(([k, v]) => {
      const row = elem("div", { className: "s3-pp-row" });
      row.appendChild(elem("span", { className: "s3-pp-k", text: k }));
      row.appendChild(elem("span", { className: "s3-pp-v", text: v }));
      $("s3-payload-marius").appendChild(row);
    });
    await sleep(500);
    $("s3-arrow-marius-atlas").classList.add("s3-arrow--active");
    await sleep(900);

    // STEP 5
    s3SetStep(5);
    s3SetStatus("step v — Atlas accepts · Exchange B tessera fit");
    // populate Atlas panels (see helpers above; abbreviated)
    clearChildren($("s3-payload-atlas"));
    clearChildren($("s3-payload-atlas-acceptance"));
    const recv = s3Real ? s3Real.marius_reschedule_proposal : reschedule;
    const acpt = s3Real ? s3Real.atlas_acceptance_payload : { candidates: ["2026-06-02T16:00:00Z"], duration_minutes: 45 };
    [["candidates", JSON.stringify(recv.candidates)], ["duration_minutes", String(recv.duration_minutes)]].forEach(([k, v]) => {
      const row = elem("div", { className: "s3-pp-row" });
      row.appendChild(elem("span", { className: "s3-pp-k", text: k }));
      row.appendChild(elem("span", { className: "s3-pp-v", text: v }));
      $("s3-payload-atlas").appendChild(row);
    });
    [["candidates", JSON.stringify(acpt.candidates)], ["duration_minutes", String(acpt.duration_minutes)]].forEach(([k, v]) => {
      const row = elem("div", { className: "s3-pp-row" });
      row.appendChild(elem("span", { className: "s3-pp-k", text: k }));
      row.appendChild(elem("span", { className: "s3-pp-v", text: v }));
      $("s3-payload-atlas-acceptance").appendChild(row);
    });
    await sleep(600);
    $("s3-arrow-atlas-marius").classList.add("s3-arrow--active");
    await sleep(700);

    const exB = s3Real ? s3Real.exchange_marius_atlas : null;
    s3AppendExchangeBadge("B", "M", "A",
      exB ? exB.proposal_payload_hash : s3FakeHashes.mariusEmitAtlas,
      exB ? exB.acceptance_payload_hash : s3FakeHashes.atlasEmit,
      "task_id_2");
    await sleep(1000);

    // STEP 6
    s3SetStep(6);
    s3SetStatus("step vi — Marius→Iris · acceptance dispatched");
    await sleep(500);
    $("s3-arrow-marius-iris").classList.add("s3-arrow--active");

    const exA = s3Real ? s3Real.exchange_iris_marius_proposal : null;
    s3AppendExchangeBadge("A", "I", "M",
      exA ? exA.proposal_payload_hash : s3FakeHashes.irisEmit,
      exA ? exA.acceptance_payload_hash : s3FakeHashes.irisReceive,
      "task_id_1");
    await sleep(700);

    const exC = s3Real ? s3Real.exchange_marius_iris_acceptance : null;
    s3AppendExchangeBadge("C", "M", "I",
      exC ? exC.proposal_payload_hash : s3FakeHashes.mariusReceive,
      exC ? exC.acceptance_payload_hash : s3FakeHashes.mariusEmitIris,
      "task_id_1");
    await sleep(800);

    const tid1 = s3Real ? s3Real.exchange_iris_marius_proposal.task_id : s3FakeHashes.taskId1;
    const tid2 = s3Real ? s3Real.exchange_marius_atlas.task_id : s3FakeHashes.taskId2;
    s3PopulateTaskIds(tid1, tid2);

    // STEP 7
    s3SetStep(7);
    s3SetStatus("step vii — three tessera fits · receipts written");

    const ts1 = s3Real ? s3Real.iris_ledger[0].timestamp : "2026-06-02T14:00:00Z";
    const ts2 = s3Real ? s3Real.iris_ledger[1].timestamp : "2026-06-02T14:00:03Z";

    clearChildren(s3LedgerIris);
    const irisEntries = s3Real
      ? s3Real.iris_ledger.map((r) => ({ seq: r.sequence, ts: r.timestamp, action: r.action_type, op: r.operation, actor: r.actor, counterpart: r.counterpart, hash: r.payload_hash }))
      : [
          { seq: 0, ts: ts1, action: "emit",    op: "proposal",   actor: "iris@meshycal.demo",   counterpart: "marius@meshycal.demo", hash: s3FakeHashes.irisEmit },
          { seq: 1, ts: ts2, action: "receive", op: "acceptance", actor: "marius@meshycal.demo", counterpart: "iris@meshycal.demo",   hash: s3FakeHashes.irisReceive },
        ];
    irisEntries.forEach((e) => appendLedgerEntry(s3LedgerIris, e));

    clearChildren(s3LedgerMarius);
    const mariusEntries = s3Real
      ? s3Real.marius_ledger.map((r) => ({ seq: r.sequence, ts: r.timestamp, action: r.action_type, op: r.operation, actor: r.actor, counterpart: r.counterpart, hash: r.payload_hash }))
      : [
          { seq: 0, ts: ts1, action: "receive", op: "proposal",   actor: "iris@meshycal.demo",   counterpart: "marius@meshycal.demo", hash: s3FakeHashes.mariusReceive },
          { seq: 1, ts: ts1, action: "emit",    op: "proposal",   actor: "marius@meshycal.demo", counterpart: "atlas@meshycal.demo",  hash: s3FakeHashes.mariusEmitAtlas },
          { seq: 2, ts: ts2, action: "receive", op: "acceptance", actor: "atlas@meshycal.demo",  counterpart: "marius@meshycal.demo", hash: s3FakeHashes.mariusReceiveAtlas },
          { seq: 3, ts: ts2, action: "emit",    op: "acceptance", actor: "marius@meshycal.demo", counterpart: "iris@meshycal.demo",   hash: s3FakeHashes.mariusEmitIris },
        ];
    mariusEntries.forEach((e) => appendLedgerEntry(s3LedgerMarius, e));

    clearChildren(s3LedgerAtlas);
    const atlasEntries = s3Real
      ? s3Real.atlas_ledger.map((r) => ({ seq: r.sequence, ts: r.timestamp, action: r.action_type, op: r.operation, actor: r.actor, counterpart: r.counterpart, hash: r.payload_hash }))
      : [
          { seq: 0, ts: ts1, action: "receive", op: "proposal",   actor: "marius@meshycal.demo", counterpart: "atlas@meshycal.demo",  hash: s3FakeHashes.atlasReceive },
          { seq: 1, ts: ts2, action: "emit",    op: "acceptance", actor: "atlas@meshycal.demo",  counterpart: "marius@meshycal.demo", hash: s3FakeHashes.atlasEmit },
        ];
    atlasEntries.forEach((e) => appendLedgerEntry(s3LedgerAtlas, e));

    s3TesseraFit.classList.add("active");
    await sleep(2800);
    s3TesseraFit.classList.remove("active");

    // STEP 8 — calendar deltas
    s3SetStep(8);
    s3SetStatus("step viii — calendars updated across three principals");
    s3MoveSlot();
    await sleep(420);
    s3GainSlot("s3-cal-marius", "s3-marius-1600", "16:00", "synthetic-project-sync", "atlas · rescheduled · signed");
    await sleep(80);
    s3GainSlot("s3-cal-iris", "s3-iris-1400", "14:00", "synthetic-iris-marius-meeting", "marius · tessera ref · signed");
    await sleep(400);
    const atlasEmpty = $("s3-cal-atlas").querySelector(".s3-cal-atlas-empty");
    if (atlasEmpty) atlasEmpty.remove();
    s3GainSlot("s3-cal-atlas", "s3-atlas-1600", "16:00", "synthetic-project-sync", "marius · rescheduled · signed");
    await sleep(1200);

    const tail = s3Real
      ? "done — real cascade in " + s3Real.duration_ms + "ms · three fits · three books match · press Reset"
      : "done — three fits (animation mode) · press Reset to run again";
    s3SetStatus(tail);
  } catch (err) {
    s3RenderAbort(err);
  } finally {
    s3RunBtn.disabled = false;
    s3RunBtn.textContent = "Run again";
  }
}
```

### `s3Reset()`

```js
function s3Reset() {
  s3SetStep(0);
  s3SetStatus("ready — press to begin");
  s3RunBtn.disabled = false;
  s3RunBtn.textContent = "Request meeting";

  ["s3-arrow-iris-marius","s3-arrow-marius-atlas","s3-arrow-atlas-marius","s3-arrow-marius-iris"]
    .forEach((id) => { const el = $(id); if (el) el.classList.remove("s3-arrow--active"); });

  const avatar = $("s3-avatar-marius");
  if (avatar) avatar.classList.remove("s3-avatar-reasoning");

  s3TracePanel.classList.remove("s3-reasoning-trace--visible");
  clearChildren(s3TraceFields);
  s3TraceReason.textContent = "— awaiting —";
  s3TraceSpinner.classList.add("s3-trace-spinner--active");
  const eyebrow = s3TracePanel.querySelector(".s3-trace-eyebrow");
  if (eyebrow) eyebrow.textContent = "agent reasoning…";

  clearChildren(s3BadgesEl);

  clearChildren(s3TaskIdBar);
  s3TaskIdBar.appendChild(elem("span", { className: "s3-taskid-placeholder", text: "task IDs will appear when the cascade completes" }));

  const label = $("s3-reasoning-label");
  if (label) label.textContent = "marius' agent — awaiting proposal";

  setLedgerEmpty(s3LedgerIris,   "— no entries yet —");
  setLedgerEmpty(s3LedgerMarius, "— no entries yet —");
  setLedgerEmpty(s3LedgerAtlas,  "— no entries yet —");

  s3TesseraFit.classList.remove("active");

  // Restore calendar deltas
  const m1600 = document.querySelector('[data-slot="s3-marius-1600"]');
  if (m1600) m1600.remove();
  const mariusCal = $("s3-cal-marius");
  if (mariusCal && !document.querySelector('[data-slot="s3-marius-1400"]')) {
    const ev1400 = elem("div", { className: "event s3-blocking" });
    ev1400.dataset.slot = "s3-marius-1400";
    ev1400.appendChild(elem("span", { className: "time", text: "14:00" }));
    const inner = elem("div");
    inner.appendChild(elem("div", { className: "title", text: "synthetic-project-sync" }));
    inner.appendChild(elem("div", { className: "attendees", text: "45 min · atlas" }));
    ev1400.appendChild(inner);
    const ev1530 = mariusCal.children[1];
    if (ev1530) mariusCal.insertBefore(ev1400, ev1530);
    else mariusCal.appendChild(ev1400);
  }

  const i1400 = document.querySelector('[data-slot="s3-iris-1400"]');
  if (i1400) i1400.remove();

  const a1600 = document.querySelector('[data-slot="s3-atlas-1600"]');
  if (a1600) a1600.remove();
  const atlasCal = $("s3-cal-atlas");
  if (atlasCal && !atlasCal.querySelector(".s3-cal-atlas-empty")) {
    const placeholder = elem("div", { className: "event free s3-cal-atlas-empty" });
    placeholder.appendChild(elem("span", { className: "time", text: "—" }));
    const inner = elem("div");
    inner.appendChild(elem("div", { className: "title", text: "no events yet" }));
    inner.appendChild(elem("div", { className: "attendees", text: "atlas' internal calendar not modeled in v0" }));
    placeholder.appendChild(inner);
    atlasCal.appendChild(placeholder);
  }

  clearChildren($("s3-payload-atlas"));
  $("s3-payload-atlas").appendChild(elem("div", { className: "s3-pp-pending", text: "— pending cascade —" }));
  clearChildren($("s3-payload-atlas-acceptance"));
  $("s3-payload-atlas-acceptance").appendChild(elem("div", { className: "s3-pp-pending", text: "— pending —" }));

  clearChildren($("s3-payload-marius"));
  $("s3-payload-marius").appendChild(elem("div", { className: "s3-pp-row s3-pp-pending", text: "— pending reasoning —" }));

  // Remove any abort banner
  const banner = document.querySelector(".s3-abort-banner");
  if (banner) banner.remove();
}

function s3RenderAbort(err) {
  const msg = (err && err.detail) || (err && err.message) || "unknown error";
  const existing = document.querySelector(".s3-abort-banner");
  if (existing) existing.remove();
  const banner = elem("div", { className: "s3-abort-banner" });
  banner.appendChild(elem("div", { className: "s3-abort-reason", text: msg }));
  const stage = $("s3-stage");
  if (stage && stage.nextSibling) stage.parentNode.insertBefore(banner, stage.nextSibling);
  else if (stage) stage.parentNode.appendChild(banner);
  s3SetStatus("cascade aborted — see details above · press Reset to clear");
}
```

### Button wiring

```js
s3RunBtn.addEventListener("click", () => {
  if (s3RunBtn.textContent === "Run again") s3Reset();
  runScenario3();
});
s3ResetBtn.addEventListener("click", s3Reset);
```

---

## 12. Tab Activation

The tab-switcher block updates `display` on `[data-scenario-content]` blocks. Shared with Track B's spec. On initial page load: scenario 1 visible, scenarios 2 and 3 hidden.

```js
document.querySelectorAll(".scenarios-tabs button").forEach((tab) => {
  tab.addEventListener("click", () => {
    const sc = parseInt(tab.dataset.scenario, 10);
    document.querySelectorAll(".scenarios-tabs button").forEach((b) =>
      b.setAttribute("aria-selected", b === tab ? "true" : "false")
    );
    document.querySelectorAll("[data-scenario-content]").forEach((block) => {
      const bn = parseInt(block.dataset.scenarioContent, 10);
      block.style.display = bn === sc ? "block" : "none";
    });
    if (sc === 1) setStatus("ready — press to begin");
    else if (sc === 2 && typeof s2SetStatus === "function") s2SetStatus("ready — press to begin");
    else if (sc === 3) s3SetStatus("ready — press to begin");
  });
});
```

---

## 13. Failure Rendering — CascadeAbortedError

When `fetchCascading()` throws (server 500 or network timeout), the runner's catch block calls `s3RenderAbort(err)` which inserts an `s3-abort-banner` div below the stage with the error detail. The stage freezes at the last activated step. `s3Reset()` removes the banner.

Common server messages:
- `"cascading scenario failed: CascadeAbortedError('reasoner found no viable reschedule slot...')"`
- `"cascading scenario failed: CascadeAbortedError('atlas declined the reschedule proposal...')"`

---

## 14. What to Leave Untouched

- Hero, primitives, policy, roadmap, colophon sections
- `:root` CSS tokens
- Existing keyframes: `bookingFlash`, `fadeIn`, `fadeInLate`, `slideInL`, `slideInR`, `seamGrow`
- All existing CSS classes (`.ledger`, `.field-tile`, `.calendar`, `.event`, `.party`, `.wire`, `.airlock`, `.step-indicator`, `.tessera-fit-overlay`, etc.)
- Scenario-1 IDs: `stage`, `tesseraFit`, `stepIndicator`, `runBtn`, `resetBtn`, `runStatus`, `backendStatus`, `ledgerBodyA`, `ledgerBodyB`, `airlockChamber`
- Scenario-1 JS: `runScenario1()`, `bookSlot()`, `unbookSlot()`, `reset()`, `setStep()`, `appendLedgerEntry()`, `fakeHash()`, `probeBackend()`, `renderBackendBadge()`, `fetchTwoParty()`
- IIFE wrapper — all new code added inside it
- `setLedgerEmpty()`, `elem()`, `clearChildren()`, `sleep()` — reused, not modified

---

## 15. New Keyframes

| Name | Used by | Description |
|------|---------|-------------|
| `s3SpinnerRotate` | `.s3-trace-spinner--active` | Continuous 360° rotation, 800ms linear |
| `s3ReasoningHalo` | `.s3-avatar-reasoning` | Pulsing box-shadow on Marius' avatar |
| `s3StepPausePulse` | `.s3-step-pause.active` | Gold border pulse on step 3 |
| `s3BadgeEnter` | `.s3-exchange-badge--entering` | Fade-in + scale, 600ms |

---

*End of UI Scenario 3 Design Spec.*

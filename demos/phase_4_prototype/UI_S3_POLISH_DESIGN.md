# UI S3 Polish Design — Narrative Band, Dialogue Panel, Atlas Calendar Fix

**File:** `MeshyCal/demos/phase_4_prototype/UI_S3_POLISH_DESIGN.md`
**Scope:** Scenario 3 only. Zero changes to scenarios 1 or 2. Zero backend changes.
**Hard constraint:** `index.html` is not modified by the spec author. All additions are made by the implementing agent.
**Namespace:** All new IDs and classes carry the `s3-` prefix, consistent with the existing discipline.
**XSS discipline:** All DOM content set via `elem()` / `textContent` or `document.createTextNode()`. `innerHTML` is never used for dynamic content.

---

## Context

The cascading-reschedule prototype is technically correct but narratively broken:

1. No setup paragraph — the viewer lands on three columns with no context.
2. Atlas's calendar starts with a "no events yet" placeholder. But Atlas has a 14:00 commitment with Marius — the exact slot Iris is requesting. Cascade looks one-sided.
3. The reasoning trace inside Marius's column shows the agent's internal voice but not the inter-agent conversation in plain English.

Three additions fix all three without touching the backend, the reasoning trace panel, or scenario-1/2 markup.

---

## 1. Narrative Band

### 1.1 Purpose

A persistent full-width text panel above the three principal columns inside `<div data-scenario-content="3">`. Before the run: setup paragraph. During the run: advances through eight beats synchronized to the step indicator.

### 1.2 Placement in HTML

Insert immediately before `<div class="stage s3-stage" id="s3-stage">`.

```html
<!-- s3-narrative-band: story context, sits above the stage -->
<div class="s3-narrative-band" id="s3-narrative-band" aria-live="polite">
  <div class="s3-nb-eyebrow">the scenario</div>
  <p class="s3-nb-text" id="s3-nb-text">Iris wants a 30-minute meeting with Marius on Tuesday at 14:00. Marius already has that slot booked with Atlas for their weekly project sync. Watch what happens when Iris's request collides with Marius's calendar.</p>
</div>
```

### 1.3 CSS

Add inside `<style>`, after `.s3-arrows-layer { display: none; }` (inside the existing `@media (max-width: 1080px)` block), before `</style>`.

```css
/* ----- s3 narrative band ----- */
.s3-narrative-band {
  background: hsl(40 28% 91%);
  border: 1px solid hsl(40 20% 78%);
  border-bottom: none;
  padding: 22px 28px 20px;
}
.s3-nb-eyebrow {
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  color: hsl(40 20% 52%);
  margin-bottom: 10px;
}
.s3-nb-text {
  font-family: var(--body);
  font-size: 16px;
  line-height: 1.6;
  color: hsl(222 28% 18%);
  margin: 0;
  font-style: italic;
  transition: opacity 300ms ease;
}
.s3-nb-text--fading {
  opacity: 0;
  transition: opacity 200ms ease;
}
@media (max-width: 1080px) {
  .s3-narrative-band { padding: 16px 18px 14px; }
  .s3-nb-text { font-size: 14px; }
}
```

### 1.4 Beat Text — 8 Beats Mapped to Steps

| Trigger | `textContent` of `#s3-nb-text` |
|---|---|
| `s3Reset()` / initial | `Iris wants a 30-minute meeting with Marius on Tuesday at 14:00. Marius already has that slot booked with Atlas for their weekly project sync. Watch what happens when Iris's request collides with Marius's calendar.` |
| Step 1 | `Iris is building her proposal: Tuesday at 14:00, 30 minutes. Her agent will scope it — only the slot and duration will cross the wire.` |
| Step 2 | `Iris's request has arrived at Marius's airlock. The scoped payload is in flight — calendar titles and attendee emails were stripped before it left.` |
| Step 3 | `Marius's agent noticed the conflict. Tuesday 14:00 is already booked — that's the project sync with Atlas. The agent is reasoning about whether it can free that slot…` |
| Step 4 | `Marius's agent has a plan. It's proposing to Atlas: can we shift the project sync from 14:00 to 16:00?` |
| Step 5 | `Atlas accepted. The 14:00 slot is now free. Marius can honour Iris's request.` |
| Step 6 | `Marius confirmed to Iris: Tuesday 14:00 is yours. Three signed receipts in flight.` |
| Step 7 | `Three tessera fits. Every receipt matches its counterpart. The trust layer verified the chain.` |
| Step 8 | `Three calendars updated. Iris gains 14:00. Marius and Atlas both move their project sync to 16:00. The cascade is complete.` |

### 1.5 `s3NarrativeBeat(text)` Helper

Add inside the IIFE, after `s3SetStatus`, before `fetchCascading`.

```js
function s3NarrativeBeat(text) {
  const el = $("s3-nb-text");
  if (!el) return;
  el.classList.add("s3-nb-text--fading");
  setTimeout(function () {
    el.textContent = text;
    el.classList.remove("s3-nb-text--fading");
  }, 200);
}
```

### 1.6 Insert Calls in `runScenario3()`

Insert one `s3NarrativeBeat(...)` call at the top of each step block, immediately after the `s3SetStep(N)` call. Use the exact strings from section 1.4. No existing lines are removed.

### 1.7 `s3Reset()` Addition

Add immediately after `s3SetStep(0)` at the top of `s3Reset()`:

```js
s3NarrativeBeat("Iris wants a 30-minute meeting with Marius on Tuesday at 14:00. Marius already has that slot booked with Atlas for their weekly project sync. Watch what happens when Iris's request collides with Marius's calendar.");
```

### 1.8 Failure Beat in `s3RenderAbort(err)`

Add at the top of `s3RenderAbort`, before the existing `const msg = ...` line:

```js
const abortMsg = (err && err.detail) || (err && err.message) || "unknown error";
s3NarrativeBeat("Cascade aborted. " + abortMsg);
```

Keep the rest unchanged.

---

## 2. Agent-to-Agent Dialogue Transcript Panel

### 2.1 Purpose

ADDITIONAL to the existing reasoning trace panel. The reasoning trace shows Marius's internal deliberation; the dialogue panel shows what the three agents say to each other across the wire. Both remain visible simultaneously.

### 2.2 Placement in HTML

Insert after `</div>` closing `<div class="stage s3-stage" id="s3-stage">` and before `<div class="s3-task-id-bar">`.

```html
<!-- s3-dialogue-panel: inter-agent conversation transcript -->
<div class="s3-dialogue-panel" id="s3-dialogue-panel" aria-label="Agent conversation transcript" aria-live="polite">
  <div class="s3-dp-header">
    <span class="s3-dp-eyebrow">agent conversation</span>
    <span class="s3-dp-hint">plain-English transcript of what the agents said to each other</span>
  </div>
  <div class="s3-dp-body" id="s3-dp-body">
    <!-- message rows appended via s3DialogueAppend() -->
  </div>
</div>
```

### 2.3 CSS

```css
/* ----- s3 dialogue panel ----- */
.s3-dialogue-panel {
  background: hsl(220 22% 7%);
  border: 1px solid hsl(220 18% 22%);
  border-top: none;
}
.s3-dp-header {
  display: flex;
  align-items: baseline;
  gap: 16px;
  padding: 14px 20px 12px;
  border-bottom: 1px solid hsl(220 18% 18%);
}
.s3-dp-eyebrow {
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  color: hsl(40 25% 55%);
}
.s3-dp-hint {
  font-family: var(--mono);
  font-size: 10px;
  color: hsl(40 15% 40%);
  letter-spacing: 0.04em;
}
.s3-dp-body {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 8px 0;
  min-height: 40px;
}

/* Message row */
.s3-dm {
  display: flex;
  gap: 0;
  padding: 10px 20px;
  border-bottom: 1px solid hsl(220 18% 13%);
  opacity: 0;
  transform: translateY(6px);
  transition: opacity 350ms ease, transform 350ms ease;
}
.s3-dm:last-child { border-bottom: none; }
.s3-dm--visible { opacity: 1; transform: translateY(0); }

.s3-dm-meta {
  font-family: var(--mono);
  font-size: 10px;
  color: hsl(40 15% 45%);
  letter-spacing: 0.06em;
  width: 160px;
  flex-shrink: 0;
  padding-top: 2px;
  line-height: 1.5;
}
.s3-dm-time { display: block; color: hsl(40 20% 38%); }
.s3-dm-from { display: block; font-weight: 500; color: hsl(40 20% 55%); }

.s3-dm-bubble {
  flex: 1;
  font-family: var(--body);
  font-size: 14px;
  line-height: 1.55;
  color: hsl(40 20% 78%);
  padding-left: 16px;
  border-left: 3px solid transparent;
  font-style: italic;
}
.s3-dm-direction {
  font-family: var(--mono);
  font-size: 9.5px;
  font-style: normal;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  margin-bottom: 5px;
  display: block;
  color: hsl(40 15% 45%);
}

/* Per-agent left-border accent */
.s3-dm--iris   .s3-dm-bubble { border-left-color: hsl(40 55% 68%); }
.s3-dm--iris   .s3-dm-direction { color: hsl(40 45% 60%); }
.s3-dm--marius .s3-dm-bubble { border-left-color: var(--jade); }
.s3-dm--marius .s3-dm-direction { color: hsl(155 30% 52%); }
.s3-dm--atlas  .s3-dm-bubble { border-left-color: var(--terracotta); }
.s3-dm--atlas  .s3-dm-direction { color: hsl(13 45% 58%); }

/* Thinking row */
.s3-dm--thinking .s3-dm-bubble { color: hsl(40 15% 50%); font-style: italic; }
.s3-dm--thinking .s3-dm-direction { color: hsl(40 12% 40%); }

/* Inline spinner */
.s3-dm-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 1.5px solid hsl(40 30% 35% / 0.4);
  border-top-color: hsl(40 50% 52%);
  border-radius: 50%;
  vertical-align: middle;
  margin-left: 8px;
  animation: s3SpinnerRotate 800ms linear infinite;
}

@media (max-width: 1080px) {
  .s3-dp-header { flex-direction: column; gap: 4px; }
  .s3-dm-meta { width: 110px; }
  .s3-dm { padding: 8px 14px; }
}
```

### 2.4 `s3DialogueAppend(...)` Helper

```js
function s3DialogueAppend(agentClass, fromLabel, directionLabel, bodyText, showSpinner) {
  const body = $("s3-dp-body");
  if (!body) return null;

  const row = elem("div", { className: "s3-dm s3-dm--" + agentClass });

  const meta = elem("div", { className: "s3-dm-meta" });
  const now = new Date();
  const hh = now.getHours().toString().padStart(2, "0");
  const mm = now.getMinutes().toString().padStart(2, "0");
  const ss = now.getSeconds().toString().padStart(2, "0");
  meta.appendChild(elem("span", { className: "s3-dm-time", text: hh + ":" + mm + ":" + ss }));
  meta.appendChild(elem("span", { className: "s3-dm-from", text: fromLabel }));
  row.appendChild(meta);

  const bubble = elem("div", { className: "s3-dm-bubble" });
  bubble.appendChild(elem("span", { className: "s3-dm-direction", text: directionLabel }));
  bubble.appendChild(document.createTextNode(bodyText));

  if (showSpinner) {
    const spin = document.createElement("span");
    spin.className = "s3-dm-spinner";
    spin.setAttribute("aria-hidden", "true");
    bubble.appendChild(spin);
  }

  row.appendChild(bubble);
  body.appendChild(row);

  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      row.classList.add("s3-dm--visible");
    });
  });

  return row;
}
```

### 2.5 The Five Scripted Messages

**Message 1 — step 2, after `s3SetStep(2)` and the narrative beat:**

```js
s3DialogueAppend(
  "iris",
  "iris → marius",
  "proposal",
  "“Iris wants 30 minutes on Tuesday at 14:00. Are you available?”",
  false
);
```

**Message 2 — step 3, after `s3SetStep(3)` and narrative beat, before reasoning trace activates:**

```js
let s3ThinkingRow = s3DialogueAppend(
  "marius s3-dm--thinking",
  "marius (thinking…)",
  "internal",
  "scheduled conflict: project-sync with atlas at 14:00. Evaluating whether to move it…",
  true
);
```

`s3ThinkingRow` declared with `let` at runScenario3's scope.

**Message 3 — step 4, after `s3SetStep(4)` and narrative beat, before `s3StopReasoningSpinner()`:**

```js
if (s3ThinkingRow) {
  s3ThinkingRow.classList.remove("s3-dm--visible");
  const _tRow = s3ThinkingRow;
  setTimeout(function () { if (_tRow.parentNode) _tRow.parentNode.removeChild(_tRow); }, 360);
  s3ThinkingRow = null;
}
s3DialogueAppend(
  "marius",
  "marius → atlas",
  "proposal",
  "“We’re booked for project-sync at 14:00. Iris just asked for that slot. Can we move our sync to 16:00?”",
  false
);
```

**Message 4 — step 5, after `$("s3-arrow-atlas-marius").classList.add("s3-arrow--active")` and the `await sleep(700)`:**

```js
s3DialogueAppend(
  "atlas",
  "atlas → marius",
  "acceptance",
  "“Confirmed. 16:00 works for me.”",
  false
);
```

**Message 5 — step 6, after `$("s3-arrow-marius-iris").classList.add("s3-arrow--active")`:**

```js
s3DialogueAppend(
  "marius",
  "marius → iris",
  "acceptance",
  "“Confirmed. Tuesday 14:00 is yours.”",
  false
);
```

### 2.6 `s3Reset()` Addition

Add after `clearChildren(s3BadgesEl)` in `s3Reset()`:

```js
clearChildren($("s3-dp-body"));
```

---

## 3. Atlas Calendar Fix

### 3.1 New Initial Markup

Replace the contents of `<div class="calendar" id="s3-cal-atlas">` (the existing `s3-cal-atlas-empty` placeholder).

New content:

```html
<div class="event s3-blocking" data-slot="s3-atlas-1400">
  <span class="time">14:00</span>
  <div>
    <div class="title">synthetic-project-sync</div>
    <div class="attendees">45 min · marius</div>
  </div>
</div>
```

### 3.2 `s3MoveAtlasSlot()` Helper

Add after `s3MoveSlot()`:

```js
function s3MoveAtlasSlot() {
  const slot = document.querySelector('[data-slot="s3-atlas-1400"]');
  if (!slot) return;
  slot.classList.add("s3-slot-moving-out");
  setTimeout(function () { if (slot.parentNode) slot.parentNode.removeChild(slot); }, 400);
}
```

### 3.3 Step 8 Updates in `runScenario3()`

Add `s3MoveAtlasSlot();` immediately after the existing `s3MoveSlot();` line in the step 8 block.

Remove these two lines from the step 8 block (they refer to the deleted placeholder):

```js
const atlasEmpty = $("s3-cal-atlas").querySelector(".s3-cal-atlas-empty");
if (atlasEmpty) atlasEmpty.remove();
```

The existing `s3GainSlot("s3-cal-atlas", "s3-atlas-1600", ...)` call stays unchanged.

### 3.4 `s3Reset()` — Atlas Restore Block Replacement

Replace the existing Atlas restore block in `s3Reset()`:

```js
const a1600 = document.querySelector('[data-slot="s3-atlas-1600"]');
if (a1600) a1600.remove();
const atlasCal = $("s3-cal-atlas");
if (atlasCal && !document.querySelector('[data-slot="s3-atlas-1400"]')) {
  clearChildren(atlasCal);
  const evAtlas1400 = elem("div", { className: "event s3-blocking" });
  evAtlas1400.dataset.slot = "s3-atlas-1400";
  evAtlas1400.appendChild(elem("span", { className: "time", text: "14:00" }));
  const innerAtlas = elem("div");
  innerAtlas.appendChild(elem("div", { className: "title", text: "synthetic-project-sync" }));
  innerAtlas.appendChild(elem("div", { className: "attendees", text: "45 min · marius" }));
  evAtlas1400.appendChild(innerAtlas);
  atlasCal.appendChild(evAtlas1400);
}
```

---

## 4. What to Leave Untouched

- All scenario-1 and scenario-2 markup and JS.
- The existing `id="s3-reasoning-trace"` panel — additional, not replacement.
- The `CascadingResult` data flow. No backend changes.
- The cascade flow arrows, exchange badges, and `s3MoveSlot()` (only Atlas counterpart added).
- All `:root` tokens, existing keyframes (`s3SpinnerRotate` is reused — no new keyframe needed).
- Shared helpers: `elem`, `clearChildren`, `sleep`, `fakeHash`, `appendLedgerEntry`, `setLedgerEmpty`, `ledgerRow`.

---

## 5. Failure Rendering

When `fetchCascading()` throws:
- Narrative band shows `"Cascade aborted. [reason]"` (section 1.8).
- Dialogue panel shows whatever rows were appended before the throw — no cleanup needed.
- Existing abort banner unchanged.
- `s3Reset()` clears both panels back to idle.

---

## 6. Test Plan

### 6.1 Narrative band — text per step
For each step, assert `document.getElementById("s3-nb-text").textContent` equals the exact string from section 1.4. After reset: pre-run paragraph. After abort: starts with `"Cascade aborted."`.

### 6.2 Dialogue panel — message count and classes
After full run: 4 visible message rows (thinking row removed). Classes in order: `s3-dm--iris`, `s3-dm--marius`, `s3-dm--atlas`, `s3-dm--marius`. After reset: 0 rows.

### 6.3 Thinking row lifecycle
After step 3 begins: row with `s3-dm--thinking` and child `s3-dm-spinner`. 360ms after step 4 thinking removal triggers: no `s3-dm--thinking` element remains.

### 6.4 Atlas calendar initial state
On load / after reset: `[data-slot="s3-atlas-1400"]` exists with class `s3-blocking`; attendees text is `"45 min · marius"`; no `.s3-cal-atlas-empty` element.

### 6.5 Atlas calendar post-step-8
`[data-slot="s3-atlas-1400"]` is null. `[data-slot="s3-atlas-1600"]` exists with class `s3-slot-appeared`. Title is `"synthetic-project-sync"`. Attendees is `"marius · rescheduled · signed"`.

### 6.6 Atlas calendar reset restores 14:00
After step 8 then reset: `[data-slot="s3-atlas-1400"]` exists; `[data-slot="s3-atlas-1600"]` is null.

### 6.7 No innerHTML
Grep new JS additions for `innerHTML` — zero matches.

---

## Build Sequence

**Phase A — Atlas calendar fix.** Replace `#s3-cal-atlas` content, add `s3MoveAtlasSlot()`, modify step 8, replace Atlas restore in `s3Reset()`. Verify symmetry between Marius and Atlas calendars.

**Phase B — Narrative band.** Add CSS, add `s3NarrativeBeat`, insert HTML, add calls in all 8 steps plus reset and abort. Verify text advances correctly.

**Phase C — Dialogue panel.** Add CSS, add `s3DialogueAppend`, insert HTML, add 5 messages plus thinking-row removal, add reset clear. Verify 4 messages visible after run, 0 after reset.

---

*End of UI S3 Polish Design Spec.*

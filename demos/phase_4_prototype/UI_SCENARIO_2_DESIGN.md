# UI Scenario 2 Design — Four-Party Group Find

**File:** `MeshyCal/demos/phase_4_prototype/UI_SCENARIO_2_DESIGN.md`
**Track:** B (Scenario 2)
**Implementer note:** All new IDs and classes are prefixed `s2-` to avoid collisions with Track C (Scenario 3). Read every section before touching `index.html`. Do not modify anything listed in §12.

---

## 1. Goal

When the user clicks the tab labeled "ii. Four-party group find" and presses "Find group slot", the page tells the story of Iris convening a 30-minute meeting with three peers. The user watches:

1. Iris's agent send three query exchanges (A1, A2, A3) — one to each peer — using the same scoped-disclosure airlock seen in Scenario 1.
2. A funnel visualization narrow from three candidate slots down to the single slot all four can make.
3. Three confirm exchanges (B1, B2, B3) fire in rapid succession.
4. All four principals' calendars flip to "booked" at the chosen time.
5. A bilateral receipt table fills with six rows, one per exchange, each showing real (or fake-fallback) cryptographic hashes.
6. A single summary tessera-fit overlay fires at the end with a "6 fits · all matched" indicator.

If the backend returns `success: false`, the funnel's right column shows "no overlap" in terracotta and no calendar writes happen.

---

## 2. Stage Layout

### Concept

Scenario 1 uses a three-column grid: left party / wire / right party. Scenario 2 needs four principals. The design is a hub-and-spoke: Iris in the center, three peers arrayed around her. This is rendered as a 3-column × 2-row CSS grid, not a free-float SVG diagram, so it degrades gracefully on narrow viewports.

```
┌─────────────────────────────────────────────────────────────┐
│  [MARIUS panel]      [IRIS panel — center]   [WREN panel]   │
│  col-left            col-center              col-right       │
├─────────────────────────────────────────────────────────────┤
│  [exchange log]      [ATLAS panel — bottom]  [funnel panel] │
│  col-left            col-center              col-right       │
└─────────────────────────────────────────────────────────────┘
```

More precisely, the outer container `#s2-stage` is:

```
grid-template-columns: 1fr 1.15fr 1fr
grid-template-rows:    auto auto
gap: 0
```

- **`#s2-panel-marius`** — row 1, col 1. Left peer. Border-right.
- **`#s2-panel-iris`** — row 1, col 2. Center hub.
- **`#s2-panel-wren`** — row 1, col 3. Right peer. Border-left.
- **`#s2-panel-exchange-log`** — row 2, col 1. Running bilateral log. Border-right, border-top.
- **`#s2-panel-atlas`** — row 2, col 2. Bottom peer. Border-left, border-right, border-top.
- **`#s2-panel-funnel`** — row 2, col 3. Intersection funnel. Border-left, border-top.

All borders: `1px solid hsl(220 18% 22%)` — same token as `.stage` uses in Scenario 1. Outer `#s2-stage` background `hsl(220 22% 8%)`. Min-height: 660px.

### Avatar colors

- Iris — `.avatar` default (paper bg, ink text): initial "I"
- Marius — terracotta bg (`var(--terracotta)`), paper text: initial "M"
- Wren — `hsl(240 25% 52%)`, paper text: initial "W"
- Atlas — `hsl(30 55% 42%)`, paper text: initial "A"

### Responsive

At `max-width: 1080px`, `#s2-stage` collapses to a single column. Add to the existing `@media`:

```css
#s2-stage { grid-template-columns: 1fr; }
```

---

## 3. Step Indicator Extension

Scenario 2 gets its own step indicator: `#s2-step-indicator`. Same `.step-indicator` class structure. Nine steps:

| data-step | .n text | Label text |
|-----------|---------|------------|
| 1 | i.    | Build & send A1 → Marius |
| 2 | ii.   | Build & send A2 → Wren |
| 3 | iii.  | Build & send A3 → Atlas |
| 4 | iv.   | Compute intersection (local) |
| 5 | v.    | Confirm B1 → Marius |
| 6 | vi.   | Confirm B2 → Wren |
| 7 | vii.  | Confirm B3 → Atlas |
| 8 | viii. | Tessera fit · six receipts |
| 9 | ix.   | Meeting Object written · all four calendars |

Steps 1–3 use `.active` during each query, transition to `.done` when complete. Step 4 fires during the funnel animation. Steps 5–7 mirror 1–3 for confirm. Steps 8–9 fire at end.

---

## 4. Bilateral Receipt Table

Located below `#s2-step-indicator`, above the ledger block.

### `.s2-receipt-table` (paper + ruled-line pattern, like `.ledger`)

```css
.s2-receipt-table {
  font-family: var(--mono);
  font-size: 11.5px;
  background: var(--paper);
  color: var(--ink);
  border: 1px solid var(--ink-soft);
  margin-top: 48px;
  position: relative;
  overflow: hidden;
}
.s2-receipt-table::before {
  content: "";
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    to bottom,
    transparent 0 30px,
    hsl(34 25% 72% / 0.18) 30px 31px
  );
  pointer-events: none;
}
.s2-receipt-table > * { position: relative; z-index: 1; }
```

### Header row: `.s2-receipt-head`

```css
.s2-receipt-head {
  display: grid;
  grid-template-columns: 48px 120px 72px 200px 200px 80px;
  gap: 0;
  padding: 10px 16px;
  border-bottom: 2px solid var(--ink);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--ink-mute);
}
```

Columns: `ID`, `Peer`, `Phase`, `Iris hash`, `Peer hash`, `Status`.

### Data rows: `.s2-receipt-row`

```css
.s2-receipt-row {
  display: grid;
  grid-template-columns: 48px 120px 72px 200px 200px 80px;
  gap: 0;
  padding: 12px 16px;
  border-bottom: 1px solid hsl(34 18% 76%);
  align-items: center;
  transition: background 300ms ease;
  opacity: 0;
}
.s2-receipt-row:last-child { border-bottom: none; }
.s2-receipt-row.s2-populated {
  opacity: 1;
  animation: s2RowAppear 350ms ease forwards;
}
.s2-receipt-row .s2-exid {
  font-family: var(--display);
  font-style: italic;
  font-size: 16px;
  color: var(--ink-soft);
}
.s2-receipt-row .s2-peer { color: var(--ink); }
.s2-receipt-row .s2-phase-badge {
  font-size: 9.5px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  padding: 3px 8px;
  display: inline-block;
}
.s2-receipt-row .s2-phase-badge.query   { background: var(--jade-deep);       color: var(--paper); }
.s2-receipt-row .s2-phase-badge.confirm { background: var(--terracotta-deep); color: var(--paper); }
.s2-receipt-row .s2-hash {
  font-size: 10.5px;
  color: var(--ink-mute);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}
.s2-receipt-row .s2-verified {
  font-size: 9px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--jade);
}
@keyframes s2RowAppear {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

### Pre-built rows

Six `.s2-receipt-row` divs in HTML from page load, with `data-exchange-id` `A1` through `B3` and placeholder dashes. Skeleton for A1:

```html
<div class="s2-receipt-row" id="s2-row-A1" data-exchange-id="A1">
  <span class="s2-exid">A1</span>
  <span class="s2-peer">—</span>
  <span class="s2-phase-badge">—</span>
  <span class="s2-hash" title="">—</span>
  <span class="s2-hash" title="">—</span>
  <span class="s2-verified"></span>
</div>
```

### JS populator

```js
function s2PopulateReceiptRow(exchangeId, { peer, phase, irisHash, peerHash }) {
  const row = document.getElementById('s2-row-' + exchangeId);
  if (!row) return;
  row.querySelector('.s2-peer').textContent = peer.split('@')[0];
  const badge = row.querySelector('.s2-phase-badge');
  badge.textContent = phase;
  badge.classList.add(phase);
  const hashes = row.querySelectorAll('.s2-hash');
  hashes[0].textContent = irisHash.slice(0, 16) + '…';
  hashes[0].title = irisHash;
  hashes[1].textContent = peerHash.slice(0, 16) + '…';
  hashes[1].title = peerHash;
  row.querySelector('.s2-verified').textContent = '✓ verified';
  row.classList.add('s2-populated');
}
```

---

## 5. Intersection Visualization

### Container: `#s2-funnel` inside `#s2-panel-funnel`

```css
#s2-funnel {
  display: flex;
  gap: 0;
  align-items: flex-start;
  font-family: var(--mono);
  font-size: 11px;
  padding: 16px 0 0;
}
.s2-funnel-col {
  flex: 1;
  padding: 0 10px;
  border-right: 1px solid hsl(220 18% 22%);
  min-height: 120px;
}
.s2-funnel-col:last-child { border-right: none; }
.s2-funnel-col-head {
  font-size: 9px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: hsl(40 20% 55%);
  margin-bottom: 10px;
}
```

### Column 1 — Iris's candidates (`#s2-funnel-col1`)

Three `.s2-slot-chip` chips, always visible:

```css
.s2-slot-chip {
  padding: 6px 10px;
  border: 1px solid hsl(220 18% 24%);
  background: hsl(220 22% 11%);
  margin-bottom: 5px;
  color: hsl(40 25% 75%);
  font-size: 11px;
  transition: all 400ms ease;
}
.s2-slot-chip.eliminated {
  color: hsl(13 40% 45%);
  text-decoration: line-through;
  background: hsl(220 22% 9%);
  opacity: 0.5;
}
.s2-slot-chip.chosen {
  background: hsl(155 30% 18%);
  border-color: var(--jade);
  color: hsl(155 40% 75%);
  border-left: 3px solid var(--jade);
}
```

Format: `"tue 13:00"`, `"tue 15:30"`, `"wed 11:30"`.

Header: "Iris proposes".

### Column 2 — Per-peer filter (`#s2-funnel-col2`)

Three sub-columns stacked, one per peer (M / W / A initial), each with three chips mirroring column 1. As each query result arrives, blocked chips get `.eliminated`.

```css
.s2-funnel-peer-group {
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid hsl(220 18% 18%);
}
.s2-funnel-peer-group:last-child { border-bottom: none; }
.s2-funnel-peer-initial {
  font-size: 9px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: hsl(40 25% 55%);
  margin-bottom: 5px;
}
```

Header: "per peer response".

### Column 3 — Chosen slot (`#s2-funnel-col3`)

Initially `— awaiting —`. When resolved, replaces with `s2FormatSlot(chosen_slot)` and `.chosen` class. If `success: false`, gets `.s2-no-overlap`:

```css
.s2-slot-chip.s2-no-overlap {
  color: var(--terracotta);
  border-color: var(--terracotta);
  background: hsl(13 40% 10%);
}
```

Header: "chosen slot".

Gold flash on `.chosen`:

```css
@keyframes s2ChipChosenFlash {
  0%   { background: hsl(155 30% 18%); }
  35%  { background: hsl(40 70% 35%); }
  100% { background: hsl(155 30% 18%); }
}
.s2-slot-chip.chosen { animation: s2ChipChosenFlash 700ms ease forwards; }
```

---

## 6. Calendar Update Animations

Add `data-slot` attributes to each principal's free 13:00 event:

- Iris: `data-slot="s2-iris-tue-1300"`
- Marius: `data-slot="s2-marius-tue-1300"`
- Wren: `data-slot="s2-wren-tue-1300"`
- Atlas: `data-slot="s2-atlas-tue-1300"`

Reuse existing `bookSlot()` and `unbookSlot()`. At step 9, stagger four `bookSlot` calls with 200ms gaps:

```js
bookSlot('s2-iris-tue-1300',   { title: 'Meeting with the group', attendees: 'marius · wren · atlas · signed' });
// 200ms delay
bookSlot('s2-marius-tue-1300', { title: 'Meeting with the group', attendees: 'iris · wren · atlas · signed' });
// 200ms delay
bookSlot('s2-wren-tue-1300',   { title: 'Meeting with the group', attendees: 'iris · marius · atlas · signed' });
// 200ms delay
bookSlot('s2-atlas-tue-1300',  { title: 'Meeting with the group', attendees: 'iris · marius · wren · signed' });
```

The existing `.event.booking` / `.event.booked` styles handle the visual.

`s2Reset()` calls `unbookSlot` on all four slots restoring free state.

---

## 7. Tessera-Fit Moments

**Recommendation: one summary tessera-fit at the end with "6 fits · all matched" verdict.**

Rationale: six rapid overlay flashes would diminish the moment. The receipt table is the per-exchange evidence; the overlay lands the payoff once at the natural peak (after the funnel resolves and before the calendar writes).

### Implementation

Add `#s2-tessera-fit` inside `#s2-stage` with the same internal structure as `#tesseraFit` (identical SVG halves, `.tessera-seam`, `.verdict`). All existing CSS (`.tessera-fit-overlay`, `.tessera-half-l/r`, `.tessera-seam`, `.verdict`, keyframes `slideInL`, `slideInR`, `seamGrow`, `fadeIn`, `fadeInLate`) reused unchanged.

Set the static `.verdict` text to `"6 fits · all matched"`.

Fires at step 8, stays 2200ms, then `.active` removed.

---

## 8. HTML and CSS Additions

All new rules prefixed `s2-` (IDs) or `.s2-` (classes). Add in one block clearly commented `/* SCENARIO 2 */` after the existing media queries.

Token reuse: `var(--paper)`, `var(--paper-deep)`, `var(--ink)`, `var(--ink-soft)`, `var(--ink-mute)`, `var(--rule)`, `var(--terracotta)`, `var(--terracotta-deep)`, `var(--jade)`, `var(--jade-deep)`, `var(--gold)`, `var(--gold-deep)`, `var(--display)`, `var(--body)`, `var(--mono)`.

Existing classes reused without modification: `.party`, `.party.left`, `.party.right`, `.who`, `.avatar`, `.name`, `.id`, `.panel-label`, `.calendar`, `.event`, `.event.free`, `.event.booking`, `.event.booked`, `.bookingFlash`, `.step-indicator`, `.step`, `.step.active`, `.step.done`, `.run-controls`, `.status`, `.ledger`, `.ledger-head`, `.ledger-body`, `.ledger-entry`, `.ledger-empty`, `.tessera-fit-overlay`, `.tessera-half-l`, `.tessera-half-r`, `.tessera-seam`, `.verdict`.

Failure banner:
```css
#s2-failure-banner {
  display: none;
  background: hsl(13 50% 14%);
  border: 1px solid var(--terracotta);
  color: var(--terracotta);
  font-family: var(--mono);
  font-size: 12px;
  letter-spacing: 0.14em;
  padding: 16px 20px;
  margin-top: 24px;
  text-transform: uppercase;
}
#s2-failure-banner.s2-visible { display: block; animation: fadeIn 400ms ease forwards; }
```

---

## 9. JS Runner

### Function signature

```js
async function runScenario2() { ... }
```

Located in the same IIFE as `runScenario1()`, after it. Uses shared helpers `sleep`, `elem`, `clearChildren`, `fakeHash`, `bookSlot`, `unbookSlot`, `appendLedgerEntry`, `ledgerRow`.

### New helpers

```js
async function fetchFourParty() {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 20000);
  try {
    const res = await fetch(API_BASE + '/scenarios/four-party/run', {
      method: 'POST',
      signal: ctrl.signal,
      headers: { 'content-type': 'application/json' },
    });
    clearTimeout(t);
    if (!res.ok) throw new Error('non-2xx from /scenarios/four-party/run');
    return await res.json();
  } finally {
    clearTimeout(t);
  }
}

function s2FormatSlot(iso) {
  const d = new Date(iso);
  const days = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
  const day = days[d.getUTCDay()];
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  return day + ' ' + hh + ':' + mm;
}

let lastReal4 = null;

function setStep2(n) {
  document.querySelectorAll('#s2-step-indicator .step').forEach((el) => {
    const s = parseInt(el.dataset.step, 10);
    el.classList.toggle('active', s === n);
    el.classList.toggle('done', s < n);
  });
}

function s2SetStatus(msg) {
  document.getElementById('s2-run-status').textContent = msg;
}
```

### Step sequence in `runScenario2()`

1. Disable `s2-run-btn`. Kick off `fetchFourParty()` in background if `backendOk`.
2. `setStep2(1)`. Status: "A1 · Iris → Marius · query". sleep(900). Populate receipt row A1 (peer: "marius", phase: "query"). Mark Marius's funnel chips. sleep(700).
3. `setStep2(2)`. Status: "A2 · Iris → Wren · query". sleep(900). Populate A2. Mark Wren's chips. sleep(700).
4. `setStep2(3)`. Status: "A3 · Iris → Atlas · query". sleep(900). Populate A3. Mark Atlas's chips. sleep(700).
5. Await `backendPromise`. If failed, `lastReal4 = null`.
6. `setStep2(4)`. Status: "computing intersection locally…". sleep(800). Animate col-1 eliminations. sleep(400). Animate col-3 chosen chip. sleep(500). If `success: false`, show failure banner, set col-3 `.s2-no-overlap`, return early.
7. `setStep2(5)`. Status: "B1 · confirm". sleep(700). Populate B1. sleep(500).
8. `setStep2(6)`. Populate B2. sleep(500).
9. `setStep2(7)`. Populate B3. sleep(500).
10. `setStep2(8)`. Status: "six receipts — tessera fit". Add `.active` to `#s2-tessera-fit`. sleep(2200). Remove `.active`.
11. `setStep2(9)`. Status: "writing meeting object to all four calendars". Stagger `bookSlot` × 4 with 200ms delays.
12. Populate `#s2-ledger-body-iris` and `#s2-ledger-body-peers` from `lastReal4` or fake entries.
13. Status: tail with `duration_ms` if real. Re-enable button as "Run again".

### Consuming `FourPartyResult`

```js
lastReal4.exchanges.forEach((ex) => {
  s2PopulateReceiptRow(ex.exchange_id, {
    peer: ex.peer,
    phase: ex.phase,
    irisHash: ex.iris_payload_hash,
    peerHash: ex.peer_payload_hash,
  });
});

const ix = lastReal4.intersection;
// column-1 eliminations from after_atlas
// column-2 peer chips from each *_available
// column-3 from chosen_slot

lastReal4.iris_ledger.map((r) => ({
  seq: r.sequence, ts: r.timestamp, action: r.action_type,
  op: r.operation, actor: r.actor, counterpart: r.counterpart, hash: r.payload_hash,
}));
```

### `s2Reset()`

Restores all four slots to free, clears all receipt rows back to placeholders, clears funnel eliminations, hides failure banner, clears ledgers, removes tessera-fit `.active`.

---

## 10. Tab Activation

### Markup pattern

Each scenario's content lives in its own container div immediately after `.scenarios-tabs`:

```html
<div data-scenario-content="1" id="scenario-1-content">
  <!-- existing #stage, #stepIndicator, #runControls, .ledger-block -->
</div>

<div data-scenario-content="2" id="scenario-2-content" aria-hidden="true" style="display:none">
  <!-- #s2-stage, #s2-step-indicator, controls, .s2-receipt-table, #s2-failure-banner, .s2-ledger-block -->
</div>

<div data-scenario-content="3" id="scenario-3-content" aria-hidden="true" style="display:none">
  <!-- Track C: future -->
</div>
```

Wrapping existing Scenario 1 markup in `<div data-scenario-content="1" id="scenario-1-content">` is the ONLY structural change to Scenario 1 — purely additive.

### Tab handler replacement

```js
document.querySelectorAll('.scenarios-tabs button').forEach((tab) => {
  tab.addEventListener('click', () => {
    const sc = parseInt(tab.dataset.scenario, 10);

    document.querySelectorAll('.scenarios-tabs button').forEach((b) =>
      b.setAttribute('aria-selected', b === tab ? 'true' : 'false')
    );

    document.querySelectorAll('[data-scenario-content]').forEach((block) => {
      const match = parseInt(block.dataset.scenarioContent, 10) === sc;
      block.style.display = match ? '' : 'none';
      block.setAttribute('aria-hidden', match ? 'false' : 'true');
    });

    if (sc === 1) setStatus('ready — press to begin');
    else if (sc === 2) s2SetStatus('ready — press to begin');
    else if (sc === 3) { /* Track C */ }
  });
});
```

---

## 11. No-Common-Slot Failure Rendering

When `lastReal4.success === false`:

1. Steps 1–4 run normally (query exchanges complete, funnel cols 1–2 fill).
2. At step 4: col-1 chips all get `.eliminated`. Col-3 chip gets `.s2-no-overlap` with text "no overlap".
3. `#s2-failure-banner` gets `.s2-visible`.
4. Steps 5–9 skipped. No calendar writes. No tessera-fit.
5. Receipt rows A1–A3 populated; B1–B3 remain dashes.
6. Status: `"no common slot — intersection is empty. 3 exchanges, 0 confirms. press Reset."`
7. Re-enable button as "Run again".

Banner HTML:
```html
<div id="s2-failure-banner">
  <span>○ no common slot found</span> · <span id="s2-failure-detail">3 query exchanges ran · 0 confirm exchanges</span>
</div>
```

---

## 12. What to Leave Untouched

- `<head>` block.
- Hero, primitives, policy, roadmap, colophon sections.
- `:root` CSS custom properties.
- Scenario 1 markup (`.party.left`, `.wire`, `.party.right`, `#tesseraFit`, `#stepIndicator`, `#runBtn`, `#resetBtn`, `#runStatus`, `#backendStatus`, both `.ledger` blocks) — only change is wrapping in `<div data-scenario-content="1" id="scenario-1-content">`.
- `runScenario1()`, `reset()`, `bookSlot()`, `unbookSlot()`, `appendLedgerEntry()`, `ledgerRow()`, `fakeHash()`, `elem()`, `clearChildren()`, `sleep()`, `probeBackend()`, `renderBackendBadge()`, `fetchTwoParty()`, `setStep()`, `setStatus()` — shared, signatures unchanged.

---

## Appendix A: New Element Inventory

All new IDs for Scenario 2 — Track C must not reuse:

| ID | Description |
|----|-------------|
| `scenario-1-content` | Wrapper div for Scenario 1 |
| `scenario-2-content` | Wrapper for Scenario 2 |
| `s2-stage` | Four-panel hub-and-spoke grid |
| `s2-panel-iris` | Iris center |
| `s2-panel-marius` | Marius left |
| `s2-panel-wren` | Wren right |
| `s2-panel-atlas` | Atlas bottom-center |
| `s2-panel-exchange-log` | Exchange log bottom-left |
| `s2-panel-funnel` | Funnel bottom-right |
| `s2-funnel`, `s2-funnel-col1/2/3` | Funnel structure |
| `s2-tessera-fit` | Summary overlay |
| `s2-step-indicator` | Nine-step indicator |
| `s2-run-controls-row`, `s2-run-btn`, `s2-reset-btn`, `s2-run-status` | Controls |
| `s2-failure-banner`, `s2-failure-detail` | Failure notice |
| `s2-receipt-table` | Receipt table |
| `s2-row-A1` through `s2-row-B3` | Six receipt rows |
| `s2-ledger-iris`, `s2-ledger-body-iris` | Iris ledger |
| `s2-ledger-peers`, `s2-ledger-body-peers` | Combined peer ledger |
| `s2-iris-tue-1300`, `s2-marius-tue-1300`, `s2-wren-tue-1300`, `s2-atlas-tue-1300` | data-slot values |

All new CSS classes carry the `.s2-` prefix.

---

## Appendix B: Ledger Block for Scenario 2

Below the receipt table:

```html
<div class="ledger-block">
  <div class="ledger" id="s2-ledger-iris">
    <div class="ledger-head">
      <div class="who">Iris' book</div>
      <div class="label">all 6 bilateral entries</div>
    </div>
    <div class="ledger-body" id="s2-ledger-body-iris"><!-- JS-populated --></div>
  </div>
  <div class="ledger" id="s2-ledger-peers">
    <div class="ledger-head">
      <div class="who">Peers' books</div>
      <div class="label">marius · wren · atlas · combined</div>
    </div>
    <div class="ledger-body" id="s2-ledger-body-peers"><!-- JS-populated --></div>
  </div>
</div>
```

Iris's ledger shows all 12 entries from `lastReal4.iris_ledger` (or 6 fake). Peers' ledger shows entries from all three `*_summary.all_ledger_entries` concatenated and sorted by sequence. Each entry rendered with `appendLedgerEntry()`.

---

*End of UI Scenario 2 Design Spec.*

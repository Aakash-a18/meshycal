# MeshyCal Roadmap

Where we are, what's next, and the honest order. Milestones are real
stopping points — you can choose to ship at any of them.

ARCHITECTURE.md is "how it's built" (the spec).
This file is "what we're building next" (the sequence).

---

## Milestone 0 — Foundation (done)

The trust mechanic is real and proven.

- ✅ Mesherra trust layer in `../mesherra/` — cryptographic identity, signed
  messages, tamper-evident ledger, single-owner Objects, live-reference
  promotion. 685 tests, green CI.
- ✅ MeshyCal SchedulingAgent in `meshycal/scheduling_agent.py` — the AI
  domain agent. Uses real Claude (`AnthropicReasoner`), OpenAI-compatible
  providers (`OpenAICompatibleReasoner`), or a deterministic
  `ScriptedReasoner` for tests.
- ✅ Canonical agreement model — `MeetingObject` (closes the §3.2 keystone
  gap). Two agents end up sharing one signed truth both sides can verify.
- ✅ Web inbox UI shell — Next.js renderer + FastAPI api. Returns synthetic
  data; not yet wired to the agent.

Total: ~900 tests across both repos, all green on CI.

---

## Milestone 1 — "Show me the AI"

**Goal:** Open two browser tabs, watch a real LLM-powered agent negotiate a
meeting, see the signed receipt land in both inboxes. Synthetic users
(Alice / Bob). No Google login. No hosting. Runs on your laptop.

1. Wire `meshycal/api/inbox.py` to a real `SchedulingAgent` (replace the
   `InMemoryInbox` adapter with one that reads from the agent's
   `ProvenanceLedger` and `ObjectStore`).
2. Multi-principal session support — the api holds N `SchedulingAgent`
   instances (one per "user"), each with its own SQLite-backed policy
   store, ledger, and object store. Pick a principal via a simple URL
   query (`?as=alice`).
3. `POST /api/meetings` actually calls `SchedulingAgent.propose_meeting_to`.
4. Live updates — light polling (every 3–5s) so the counterpart's inbox
   refreshes when something arrives. No WebSockets yet.

**Effort:** ~1 week of code. **No external dependencies.**

**Outcome:** type "30 min coffee with Bob" in the Alice tab, switch to the
Bob tab, watch the request appear, click accept (or let the reasoner
auto-accept), watch the Alice tab refresh with a "booked" card and a real
64-hex agreement hash.

---

## Milestone 2 — "I can use it myself"

**Goal:** Real Google login. Real calendar. You use it on your laptop.

5. Sign in with Google (OAuth flow).
6. Per-user crypto identity — each user gets their own signing key,
   persisted to disk, generated on first login.
7. Google Calendar adapter — read free/busy into the `CalendarObject`,
   write confirmed bookings back as events.
8. Per-user storage — each person's policy/ledger/objects isolated in
   their own SQLite files (or per-user Postgres rows once we have a DB).

**Effort:** ~2 weeks of code + **~1 week wait** for Google API "test mode"
approval (works for you + ~100 named testers; no public review yet).

**Outcome:** log in with your Google account, real meetings get booked on
your real calendar.

---

## Milestone 3 — "A friend can use it too"

**Goal:** Hosted on the internet. Two real people, two real Google
accounts, one real signed agreement.

9. Server hosting (Vercel for the Next.js frontend, Fly.io or Render for
    the FastAPI backend).
10. Production database (Neon Postgres or similar — replaces local SQLite).
11. Identity directory — a registry mapping `email → public_key` so two
    strangers' agents can find each other.
12. Production-grade auth/session security (CSRF, secure cookies, refresh
    tokens).
13. Domain + TLS — meshycal.com → real cert.
14. Rate limiting + abuse prevention.
15. Error monitoring (Sentry or similar).

**Effort:** ~2 weeks of code + **3–4 weeks wait** for Google API
"production" approval (the slow one — verification for the calendar
scope).
**External costs:** ~$30/month hosting at first.

**Outcome:** you and a friend each sign up at meshycal.com, your two
agents negotiate, both see the receipt.

---

## Milestone 4 — "Strangers can use it" (real product)

**Goal:** Launchable. Anyone can sign up.

16. Onboarding / invite flow — invitee doesn't need MeshyCal already
    installed to accept. They get an invite link, sign up, and the
    pending agreement is already there.
17. Notifications — email and/or SMS when something needs your call.
18. Outlook + Apple Calendar adapters (not just Google).
19. Mobile-responsive polish — works well on phones (no native app yet).
20. Help docs + FAQ.
21. Privacy policy + ToS — legal requirement once you collect any data.
    GDPR if you have EU users.
22. Schema Registry wiring — Mesherra primitive that lets the protocol
    version cleanly without breaking existing receipts.

**Effort:** ~1–2 months of code + legal review.

**Outcome:** real product. Marketing-ready.

---

## Milestone 5 — "Could be a business"

Open-ended. The shape depends on what's working:

- Subscription billing / payments
- Native iOS + Android apps
- Slack / iMessage / Teams / Discord renderers (new "host surfaces" per
  Delegation rule 4)
- Multi-device sync
- Customer support tools (helpdesk, in-app chat)
- Marketing site

---

## Cumulative effort

| Milestone | Code | External wait | Cost / mo |
|-----------|------|---------------|-----------|
| M0 (done) | —    | —             | —         |
| M1        | ~1 wk | none          | $0        |
| M2        | ~2 wk | ~1 wk Google  | $0        |
| M3        | ~2 wk | ~3–4 wk Google| ~$30      |
| M4        | ~1–2 mo | legal review | ~$30+    |

Realistic total to M4 (launchable product): **3–4 months of focused work
+ ~6 weeks of external waits, much of it parallelizable.**

---

## Build discipline (forces that shape the order)

Pulled from CLAUDE.md for quick reference:

- Mesherra → MeshyCal is the only allowed direction. The trust layer
  never depends on a Delegation.
- No real user data, ever — synthetic only in repo/tests/fixtures.
- All config via environment; no hardcoded paths/keys/URLs/ports.
- Don't abstract MeshyCal prematurely. Reusable "Delegation helpers"
  emerge from Delegation #2, not from speculation inside #1.
- CalendarObject never crosses the wire — only derivatives do
  (Proposals, MeetingObject views).

This is why M2 doesn't try to ship a multi-tenant abstraction, why M4
defers Apple Calendar to its own milestone, and why M5's other-surface
renderers (Slack, iOS) wait until the web renderer has proven the
pattern.

# NEXA — Your Neighborhood, When You Need It Most

NEXA is an AI-assisted neighborhood assistance platform. It is built as an **orchestration system**, not a
request board: it understands what a person needs, weighs who is nearby and trustworthy, asks the person's
Trusted Circle first when they want that, and for emergencies stays with them through verified, voice-guided
steps until real help arrives.

```
ASK → UNDERSTAND → ASSESS → MATCH → CONNECT → CARE → RESOLVE → LEARN
```

> NEXA connects neighbours. It **does not replace emergency services** and cannot call them for you — NEXA CARE
> always tells the person to call the emergency number and shows it.

## Repository layout

| Path | What it is |
|---|---|
| `backend/` | FastAPI + SQLAlchemy API, WebSocket hub, Trust Engine, SmartMatch, NEXA CARE, 261 pytest tests |
| `frontend/` | Next.js 16 (App Router) + React 19 + TypeScript + Tailwind v4, Leaflet maps, 31 vitest tests |
| `docker-compose.yml` | Production-shaped stack (Postgres + API + web). See "Verification status" |

## Quick start (local)

Requirements: Python 3.11+, Node 20+ (developed on Python 3.13, Node 22).

```bash
# 1. API  (SQLite by default; nothing else to install)
cd backend
python -m venv .venv && .venv/Scripts/activate        # or: source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app.seed --reset                            # demo neighbourhood (Bengaluru sample data)
uvicorn app.main:app --port 8000

# 2. Web
cd ../frontend
npm install
npm run dev                                           # http://localhost:3000
```

Demo accounts (password `nexa1234`, **seed data only — never use in production**):
`nishit@nexa-demo.app` (requester with a Trusted Circle), `aarav@nexa-demo.app` (first-aid certified helper),
`rahul@nexa-demo.app` (furniture helper), `admin@nexa-demo.app` (admin).

The browser asks for location; on a desktop you can pick **"Use sample location"** (Koramangala) so the seeded
neighbourhood is nearby.

### Try the two core scenarios

1. **Home alone** — log in as Nishit → type/say *"Nexa, I need someone to help me move a cupboard."* → NEXA shows
   what it understood and "Ask my Trusted Circle first (window 5:00)". Log in as `suresh@nexa-demo.app` in another
   browser and accept → Nishit sees the assignment, ETA and Trust Card live. If nobody accepts inside the window (or
   everyone declines), NEXA says *"Nobody from your Trusted Circle is available…"* and SmartMatch takes over
   (Rahul Shah, 700 m).
2. **Critical** — press **SOS** (or say *"Nexa, I fell off my bike and my arm is bleeding"*) → emergency UI, "Call
   112", verified bleeding-control steps read aloud, circle + first-aid-trained neighbours alerted at once,
   "I'm feeling dizzy" switches to the dizziness protocol, *"Help has arrived"* ends NEXA CARE.

## Architecture

```
Next.js (client components)  ──REST──▶  FastAPI routers ─▶ services ─▶ SQLAlchemy ─▶ PostgreSQL / SQLite
        ▲   └─ Web Speech API (STT/TTS)                        │
        └────────── WebSocket /ws ◀── post-commit event hub ◀──┘
```

Backend services (`backend/app/services/`):

- **orchestrator** — request lifecycle state machine (`CREATED → … → RATED`, plus `CANCELLED/EXPIRED/ESCALATED`),
  routing policy (normal / urgent / critical), Trusted-Circle window + automatic escalation, atomic helper acceptance,
  credits, reviews. Every transition is recorded in `request_status_history`.
- **circle** — the relationship graph. Each relationship is **two directed edges** (A→B, B→A) sharing a status
  (`PENDING/ACCEPTED/DECLINED/BLOCKED`); both people control acceptance, their own label, priority, contactability
  and visibility. A circle member is only asked when *both* edges allow it.
- **smartmatch** — ranks helpers for one request: distance/ETA, skill coverage (verified certificate > declared
  skill), availability/schedule/load, trust (overall blended with category trust), relationship signal, context
  (prior similar help). Weights are configurable and boosted for distance/skills in critical cases.
  **Match score ≠ trust score ≠ relationship priority**: they are separate outputs; a certified neighbour 500 m away
  outranks an uncle 5 km away in an emergency (tested).
- **trust** — explainable Trust Engine behind a swappable `TrustModel` interface (see limits below). Signals:
  identity, credentials, responsiveness, cancellations/no-shows, ratings (Bayesian-shrunk toward a neutral prior),
  help history, upheld reports; per-category contextual trust; every score ships with its factors and a confidence.
- **care** — NEXA CARE. Medical content comes **only** from admin-managed, versioned `protocols`; the conversation
  layer is deterministic (done / can't / dizzy / help arrived / repeat / status …) and relays approved steps. Every
  turn and state change is written to `incident_steps` (audit log).
- **nlu** — rule-based understanding always available; optional Claude call validated against strict enums. A
  **safety floor** means neither the LLM nor the user can lower a detected critical urgency.
- **voice** — stateless conversation manager (client echoes a small validated context).
- **realtime** — WebSocket hub; events are queued on the DB session and pushed only **after commit** (nothing is
  pushed for rolled-back work).

### Privacy rules that are enforced server-side (and tested)

- Strangers see "Verified nearby helper", never "Nishit's cousin" — unless the requester opts to reveal it.
- Relationship visibility: only me / Trusted Circle members / nobody; a circle member the requester unticked (or who
  opted out) is never contacted, including through the community path.
- Non-assigned people get an approximate location (~1 km); exact coordinates only go to the requester, admins, and an
  assigned helper **when the requester consented**. Maps and the radar are anonymised.
- Non-participants get `404` (not `403`) so request/incident existence is not revealed.

## API

74 endpoints; interactive docs at `http://localhost:8000/docs` (disabled when `NEXA_ENVIRONMENT=production`).
Groups: `/api/auth`, `/api/users`, `/api/requests`, `/api/relationships`, `/api/trusted-circle`, `/api/matching`,
`/api/ai`, `/api/voice`, `/api/incidents` (NEXA CARE), `/api/directory`, `/api/events`, `/api/credits`,
`/api/notifications`, `/api/reports`, `/api/admin/*`, WebSocket `/ws?token=…`. All endpoints in the brief are
implemented (plus `/progress`, `/withdraw`, `/no-show`, `/review`, chat, radar, admin).

## Configuration

Everything tunable is an environment variable — see `backend/.env.example` (response windows, radii, batch sizes,
weights, emergency number, credits, optional LLM / STT). `frontend/.env.example` has `NEXT_PUBLIC_API_URL`.
Production **must** set `NEXA_JWT_SECRET` (the app refuses to start with the default), `NEXA_DATABASE_URL`
(PostgreSQL) and `NEXA_CORS_ORIGINS`. No secrets are committed; `.env*` is git-ignored.

## Testing

```bash
cd backend  && python -m pytest                 # 261 tests, ~3-7 min (per-test schema reset)
cd frontend && npm test && npm run typecheck && npm run lint && npm run build
```

Backend coverage follows the brief: auth, request lifecycle (create/edit/cancel/complete/expire), every Trusted
Circle branch (no contacts, unavailable, accept, decline, timeout, community fallback, custom, urgent, critical),
SmartMatch factors, NEXA CARE (protocol selection, steps, "can't do that", situation change, escalation, helper
assignment, arrival, closure, audit log, protocol versioning), Trust Engine (new user, few interactions,
cancellations, response, certifications, reports, explainability, per-category), security (every non-public route
rejects anonymous calls; every `/api/admin` route rejects normal users — generated from the OpenAPI schema), input
validation, location/relationship privacy, WebSockets, LLM/STT failure fallbacks, a real multi-threaded
**simultaneous-acceptance race**, and the two end-to-end demo scenarios.

Run the backend suite against real PostgreSQL: `python scripts/pg_test_server.py` (embedded Postgres, dev only),
then `NEXA_TEST_DATABASE_URL=<printed url> python -m pytest`.

## Verification status — what has and hasn't been verified

Verified in the authoring environment (Windows, Python 3.13, Node 22):

- **Backend: 261 tests pass on SQLite and on a real PostgreSQL server** (embedded Postgres via
  `scripts/pg_test_server.py`), including the multi-threaded simultaneous-acceptance race. Running on Postgres
  caught one real bug (timestamps came back in the session timezone), now normalised to UTC.
- **Frontend:** `tsc`, ESLint, production build, and 31 unit tests (API client failure modes, speech unsupported/denied
  paths, geolocation permission states, Trust Card, UI primitives).
- **The real app driven in Chrome** against the real API: login → request → Trusted Circle → live acceptance (WebSocket)
  → complete → rate; SOS → NEXA CARE → steps → "dizzy" protocol switch → helper assignment → "help has arrived";
  admin dashboard/analytics/heatmap; API outage screen and recovery. This found and fixed real defects (naive
  timestamps breaking the countdown, offline bounce to login, several responsive and contrast problems).
- **Accessibility:** automated axe-core (WCAG 2.1 A/AA) reports zero violations on Home, Request, Tracking, Trusted
  Circle, Radar, Directory, Profile, Notifications, NEXA CARE (start + session) and the admin tabs, in the dark theme
  and the emergency theme. This is an automated check, not a full audit (no screen-reader pass, light theme checked
  only by token contrast).
- **Responsive:** phone-width (390 px) layouts checked visually for Home, Request, Tracking, Circle, Radar; no
  horizontal overflow after fixes.

**Not** verified (be honest before relying on these):

- `docker-compose.yml` / Dockerfiles were never run (no Docker available).
- **Voice**: speech recognition/synthesis use the browser's Web Speech API. The code paths and failure handling are
  unit-tested with mocks, but real microphone input was not exercised end to end. Support varies by browser
  (Chrome/Edge best). Server-side transcription (`/api/voice/transcribe`) is wired to an OpenAI-compatible endpoint
  but was tested only with mocks; it returns `501` when unconfigured rather than faking text.
- **LLM understanding** (Claude) was tested with mocked responses and failure modes, not against the live API.
- **Push notifications**: in-app notifications + WebSockets are real; OS/mobile push (FCM/APNs/Web Push) is not built.
- Phone layouts were checked at 390 px in a desktop browser, not on physical devices. No screen-reader pass was done; the
  UI uses semantic landmarks, labelled controls, focus rings, `aria-live` regions and reduced-motion support.
- **Geolocation** permission states are unit-tested with a mocked browser API; the real browser prompt was not
  automated (the "sample location" button was used for desktop testing).

## Honest limits (read before real-world use)

- **Trust Engine is a transparent heuristic, not a trained ML model.** There is no real outcome data to train
  LightGBM/XGBoost on. The `TrustModel` interface (`services/trust.py`) lets a trained model replace it without
  touching callers; until then scores are explainable weighted evidence with Bayesian shrinkage. Scores are
  *indicators, not guarantees* and are labelled so in the UI.
- **First-aid protocols are seed content** drafted from general public first-aid principles and deliberately
  conservative (no drugs/dosing; always lead with emergency services). **They must be reviewed and approved by a
  qualified clinician before any real-world use.** The admin UI publishes new versions; old incidents keep the
  version they started with.
- **NEXA cannot contact emergency services.** It advises, shows the number (`NEXA_EMERGENCY_NUMBER`, default `112`),
  and records what the user reports.
- Seeded users, directory entries (hospitals, pharmacies, …) and events are **sample data** and are labelled as such.
  Replace them with real data/services.
- ETAs are straight-line distance × road factor at a configured average speed — not a routing engine.
- **Scaling:** the WebSocket hub, login throttle and the timeout sweeper are in-process. Run a single API process
  or move them to Redis (pub/sub + shared rate limit + a single scheduler) before scaling horizontally. The
  acceptance race is safe across processes (it is a conditional `UPDATE`).
- **Schema migrations:** tables are created with `create_all` at startup. Add Alembic before evolving a production
  database.
- **Auth:** JWT bearer tokens in `localStorage` (logout revokes the token server-side). A cookie-based session with
  CSRF protection would be stronger against XSS; email/phone verification is admin-driven (no SMS/email provider is
  integrated), so "verified" means an administrator approved it.
- Help Credits are a thank-you ledger, not money: a low balance never blocks a request (receiving is clamped at 0).

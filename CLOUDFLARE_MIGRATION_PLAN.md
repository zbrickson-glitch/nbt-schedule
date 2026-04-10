# NBT Schedule Cloudflare Migration Plan

Last updated: 2026-04-09

## Goal

Move the public NBT schedule website off the current k3s deployment and onto Cloudflare in a way that is:

- reliable
- easy to deploy
- easy to maintain
- reversible during rollout

This plan assumes we will migrate the public site first and keep the ingest/parser pipeline on a separate backend during phase 1.

## Executive summary

Recommended end state for phase 1:

- Public site hosted on Cloudflare Workers Static Assets
- Public API implemented in a Cloudflare Worker
- PostgreSQL retained initially
- Worker connects to Postgres through Hyperdrive
- Existing Python ingest/parser/admin stack remains separate until phase 2

This is the best balance of speed, safety, and maintainability.

## Why this shape

The current app is not just a static website.

It includes:

- a FastAPI app
- direct Postgres access via `psycopg2`
- PDF parsing code
- Gmail/SSH-driven backfill and ingest
- Docker and k3s-specific deployment assumptions

That makes a direct Cloudflare Pages deploy unrealistic without a major rewrite.

The public-facing side, however, is small and clean:

- render static app shell
- fetch schedule JSON
- fetch casting JSON
- fetch season JSON
- submit feedback
- serve calendar feed

That public surface is ideal for Cloudflare.

## Target architecture

### Phase 1 target

Cloudflare will serve the public site only.

Components:

- Static assets
  - `index.html`
  - `sw.js`
  - `manifest.json`
  - icons and future assets
- Worker API
  - read-only public schedule endpoints
  - feedback endpoint
  - calendar feed endpoint
- Database
  - existing PostgreSQL
  - access via Hyperdrive
- Legacy backend
  - Python ingest/parser/admin stays outside Cloudflare for now

### Phase 2 target

Optional later improvements:

- move admin to Cloudflare
- migrate some or all write-path APIs
- split ingestion into queue-based workers
- reduce or eliminate legacy app dependency

## Source of truth in current repo

Public frontend:

- `/Volumes/workspace/work/nbt-schedule/app/static/index.html`
- `/Volumes/workspace/work/nbt-schedule/app/static/sw.js`
- `/Volumes/workspace/work/nbt-schedule/app/static/manifest.json`
- `/Volumes/workspace/work/nbt-schedule/app/static/icon.svg`

Current public API behavior:

- `/Volumes/workspace/work/nbt-schedule/app/routers/public.py`

Current data model:

- `/Volumes/workspace/work/nbt-schedule/sql/001_schema.sql`

Current deployment reference:

- `/Volumes/workspace/work/nbt-schedule/deploy.sh`
- `/Volumes/workspace/work/nbt-schedule/build-and-push.sh`
- `/Volumes/workspace/infra/manifests/nbt/deployment.yaml`

## Migration strategy

We will not “port the server”.

We will:

1. extract the frontend into a Cloudflare-ready app package
2. reimplement the public API routes in a Worker
3. keep the legacy Python system alive for ingestion and data maintenance
4. cut over the public hostname only after validation

## Proposed new project layout

Inside `/Volumes/workspace/work/nbt-schedule`, create a Cloudflare app area:

```text
cloudflare/
  public/
    index.html
    sw.js
    manifest.json
    icon.svg
  src/
    index.ts
    routes/
      schedule.ts
      casting.ts
      season.ts
      feedback.ts
      calendar.ts
    db/
      postgres.ts
      queries.ts
    lib/
      cors.ts
      cache.ts
      ics.ts
  wrangler.jsonc
  package.json
  tsconfig.json
```

Why TypeScript:

- best fit for Workers
- simplest ecosystem for Hyperdrive and routing
- easier than forcing Python into Workers constraints

## Route-by-route migration map

### Public routes to move in phase 1

#### `/`

Current source:

- `app/static/index.html`

Cloudflare target:

- static asset

Notes:

- frontend should stop assuming same-origin forever
- add runtime-configurable API base if we want easier testing

#### `/sw.js`

Current source:

- `app/static/sw.js`

Cloudflare target:

- static asset

#### `/static/*`

Current source:

- `app/static/*`

Cloudflare target:

- static assets folder

#### `/public/schedule/date/{event_date}`

Current source:

- `app/routers/public.py`

Cloudflare target:

- Worker route

Implementation notes:

- preserve existing “latest source_email_id for the date” behavior
- cache short-term at edge
- return same JSON shape as current frontend expects

#### `/public/casting`

Current source:

- `app/routers/public.py`

Cloudflare target:

- Worker route

Implementation notes:

- mostly straight SQL query port
- can likely cache aggressively

#### `/public/casting/shows`

Current source:

- `app/routers/public.py`

Cloudflare target:

- Worker route

Implementation notes:

- small payload
- high cacheability

#### `/public/season`

Current source:

- `app/routers/public.py`

Cloudflare target:

- Worker route or static JSON asset

Recommendation:

- make season data a static JSON asset in Cloudflare if possible
- only use Worker logic if the source remains dynamic

#### `/public/feedback`

Current source:

- `app/routers/public.py`

Cloudflare target:

- Worker route

Implementation notes:

- write into Postgres or alternative sink
- optional Discord forwarding should become a queued or fire-and-forget integration
- add rate limiting / bot protection in Cloudflare

#### `/public/calendar.ics`

Current source:

- `app/routers/public.py`

Cloudflare target:

- Worker route

Implementation notes:

- generate ICS in Worker
- likely cache per minute or short interval

### Routes not moving in phase 1

- `/api/ingest`
- `/api/backfill`
- `/api/casting/import`
- `/api/subscribers`
- `/cal/{token}.ics`
- `/api/pipeline/nbt`
- admin CRUD routes

These remain on the legacy backend for now.

## Database plan

### Phase 1

Keep the current PostgreSQL database.

Use Hyperdrive in front of Postgres for Worker access.

Benefits:

- avoids data migration risk
- preserves existing parser/ingest writes
- minimizes schema churn

### DB access design

Worker query layer should be intentionally narrow:

- `getScheduleForDate(date)`
- `getCasting()`
- `getCastingShows()`
- `getSeason()`
- `createFeedback(message, metadata)`
- `getCalendarFeed()`

Do not expose raw SQL across route files.

### Query compatibility note

The current SQL uses Postgres-specific behavior and should translate fine.

Important items to preserve:

- `ORDER BY max(created_at) DESC` dedupe logic
- schema search path or explicit `nbt.` qualification
- stable column names expected by frontend

### Optional DB improvement

For the Worker rewrite, prefer explicit table names like `nbt.schedule_events` rather than relying on search path.

## Frontend plan

### Phase 1 frontend changes

Minimal changes only:

1. copy current static files into the new Cloudflare asset folder
2. keep the UI intact
3. replace hard-coded relative API calls with a small API helper
4. add environment-driven API base URL support for local testing if useful

### Recommended frontend cleanup during migration

- split giant `index.html` script into modules later, not first
- keep HTML/CSS/JS mostly unchanged for initial cutover
- preserve current UX and language toggles
- add graceful error handling for API failures

### Suggested API wrapper

Add a tiny helper:

```js
const API_BASE = window.__NBT_API_BASE__ || '';
async function apiFetch(path, init) {
  return fetch(`${API_BASE}${path}`, init);
}
```

Then replace existing `fetch()` calls gradually.

## Worker API design

### Recommended routing

Single Worker with:

- static assets
- API routes under `/public/*`

Suggested route table:

- `GET /public/schedule/date/:date`
- `GET /public/casting`
- `GET /public/casting/shows`
- `GET /public/season`
- `POST /public/feedback`
- `GET /public/calendar.ics`

### Response compatibility

Public Worker routes should preserve the current JSON contract exactly where possible.

This avoids frontend rewrites.

### Caching strategy

Suggested cache policy:

- schedule by date: short TTL, e.g. 60 to 300 seconds
- casting: medium TTL, e.g. 5 to 15 minutes
- casting shows: medium TTL
- season: long TTL if static
- calendar feed: short TTL
- feedback: no cache

### Security

For `/public/feedback`:

- enable Cloudflare WAF/bot protections
- validate body size and length strictly
- rate limit by IP
- optionally use Turnstile later if abuse appears

## Legacy system plan

Keep the current Python service alive initially for:

- ingest
- parser
- backfill
- admin
- subscriber-specific feeds if still needed

During phase 1, legacy service becomes an internal data maintenance system instead of the public website.

## Migration phases

## Phase 0: Discovery and freeze

Goal:

- stabilize understanding before rewriting anything

Tasks:

- confirm production schema and data shape
- verify whether current live deployment still writes to the same Postgres
- confirm desired public hostname and Cloudflare account/project
- confirm whether subscriber calendars matter for phase 1
- confirm whether admin should stay private on legacy stack

Deliverables:

- validated schema notes
- env inventory
- route inventory
- go/no-go checklist

## Phase 1: Cloudflare scaffold

Goal:

- create Cloudflare project skeleton

Tasks:

- create `cloudflare/` project
- add Wrangler config
- configure static assets
- stand up a hello-world Worker route
- configure local development and preview

Deliverables:

- deployable Cloudflare shell
- preview URL

## Phase 2: Frontend lift

Goal:

- run the existing public UI from Cloudflare assets

Tasks:

- copy static files
- make sure `index.html`, service worker, manifest, icons all resolve correctly
- verify tab switching and settings behavior
- verify no broken asset paths

Deliverables:

- static app shell renders on Cloudflare

## Phase 3: Public API rewrite

Goal:

- replace Python public routes with Worker routes

Tasks:

- implement Hyperdrive-backed DB client
- port schedule route
- port casting routes
- port season route
- port feedback route
- port calendar feed
- preserve response shape

Deliverables:

- all public frontend fetches served by Worker

## Phase 4: Integration and parity testing

Goal:

- ensure Cloudflare output matches current app behavior

Tasks:

- compare sample dates between legacy API and Worker API
- compare casting payloads
- compare season payloads
- compare calendar feed outputs
- test feedback submission
- test mobile rendering
- test service worker behavior

Deliverables:

- parity checklist
- bug list resolved

## Phase 5: Cutover

Goal:

- point public hostname at Cloudflare

Tasks:

- create production Cloudflare project
- attach custom domain
- verify DNS and SSL
- enable analytics/observability
- perform staged rollout if possible
- keep legacy backend available for rollback

Deliverables:

- public hostname served by Cloudflare

## Phase 6: Post-cutover hardening

Goal:

- make operations safe and boring

Tasks:

- add alerts
- add request/error dashboards
- tune cache headers
- add rate limiting rules
- document deploy process
- document rollback process

Deliverables:

- production runbook

## Phase 7: Phase 2 migration decisions

Possible follow-up work:

- migrate admin UI
- replace subscriber feed flow
- redesign ingestion architecture
- evaluate D1/R2/Queues where useful
- retire k3s public deployment

## Detailed execution checklist

### Workstream A: Cloudflare app bootstrap

- create new `cloudflare/` directory
- add `package.json`
- add `wrangler.jsonc`
- add Worker entrypoint
- add assets directory
- add local dev scripts

### Workstream B: Frontend extraction

- copy static files from `app/static/`
- verify all references are root-safe
- decide whether to keep monolithic `index.html`
- add API base abstraction

### Workstream C: DB connectivity

- provision Hyperdrive
- create Worker env bindings
- verify local development strategy
- create query helpers
- test schedule query

### Workstream D: API route implementation

- schedule endpoint
- casting endpoints
- season endpoint
- feedback endpoint
- calendar feed endpoint

### Workstream E: Testing

- visual smoke tests
- API parity tests
- mobile viewport tests
- failure state tests
- cutover rehearsal

### Workstream F: DNS and launch

- create staging subdomain
- create production custom domain
- verify SSL issuance
- confirm redirects if needed
- define rollback DNS procedure

## Risks and mitigations

### Risk: database access from Workers is slower or more complex than expected

Mitigation:

- keep query surface tiny
- use Hyperdrive
- cache read-heavy endpoints

### Risk: response shape drift breaks the frontend

Mitigation:

- preserve payload contract exactly
- add parity fixtures and endpoint diffs

### Risk: feedback route gets abused

Mitigation:

- Cloudflare rate limiting
- WAF rules
- optional Turnstile

### Risk: subscriber or admin features quietly depend on the public app

Mitigation:

- explicitly inventory all non-public consumers before cutover

### Risk: current production behavior differs from this repo snapshot

Mitigation:

- compare live route behavior and DB data before migration
- avoid assuming repo is fully current

## Acceptance criteria

The migration is successful when:

- the public site loads from Cloudflare
- Daily tab works for valid dates
- Casting tab works
- Season tab works
- feedback submission works
- calendar feed works
- mobile layout matches or improves on current site
- public hostname no longer depends on the k3s app
- rollback remains available for at least one launch cycle

## Rollback plan

If the Cloudflare cutover fails:

1. switch DNS/custom-domain routing back to legacy public origin
2. disable Cloudflare public Worker routes if needed
3. leave legacy ingest/admin untouched
4. log root cause and retry after fix

Rollback must be rehearsed before production cutover.

## Recommended order of implementation

The order I would actually build this in:

1. scaffold Cloudflare app
2. move static frontend unchanged
3. port `GET /public/schedule/date/:date`
4. port casting endpoints
5. port season endpoint
6. port calendar feed
7. port feedback
8. do parity testing
9. cut over staging hostname
10. cut over production hostname

## What I would do next

If we start implementation immediately, the next concrete step should be:

1. create the `cloudflare/` project scaffold in this repo
2. copy the public static assets into it
3. add a Worker with one route: `GET /public/schedule/date/:date`

That gives us the fastest path to something real we can test.

# NBT Schedule Working Notes

Last updated: 2026-04-09

## What this project is

This repo is a FastAPI app plus a static frontend for the Nevada Ballet Theatre schedule site.

- Repo: `/Volumes/workspace/work/nbt-schedule`
- App entrypoint: `/Volumes/workspace/work/nbt-schedule/app/main.py`
- Public site frontend: `/Volumes/workspace/work/nbt-schedule/app/static/index.html`
- Admin UI source: `/Volumes/workspace/work/nbt-schedule/app/static/admin.html`
- Public hostname: `https://schedule.naenaewhipwhip.com`

## Current status

What I verified on 2026-04-09:

- The public hostname still resolves and has a valid TLS cert.
- `https://schedule.naenaewhipwhip.com/` is currently broken for users.
- Browser automation shows the live site renders as a blank white page.
- Browser console on the live site shows a failed resource load with HTTP `502`.
- `https://schedule.naenaewhipwhip.com/api/health` returns `403` from Caddy instead of the FastAPI JSON health response.
- `http://schedule.k3s.local/api/health` timed out from this machine.

My current read:

- The edge/proxy is still up.
- The app behind it is down, unreachable, or misrouted.

## How the website works

### High level

The site is mostly a single static page that fetches JSON from the backend.

- `/` serves `app/static/index.html`
- `/sw.js` serves the service worker
- `/static/*` serves static assets
- The frontend uses relative `fetch()` calls, so it expects to be hosted on the same origin as the API

### Main UI sections

The public site has four tabs:

- `Daily`
- `Casting`
- `Season`
- `Month` (placeholder / coming soon)

It also includes:

- Display settings panel
- Calendar subscribe buttons
- Install-app banner
- Suggestions / feedback form

### Frontend data flow

From `app/static/index.html`, the main frontend requests are:

- Daily schedule: `GET /public/schedule/date/{YYYY-MM-DD}`
- Casting shows: `GET /public/casting/shows`
- Casting data: `GET /public/casting`
- Season data: `GET /public/season`
- Suggestions: `POST /public/feedback`
- Calendar feed: `GET /public/calendar.ics`

Other frontend behaviors:

- Registers a service worker at `/sw.js`
- Loads a web manifest from `/static/manifest.json`
- Uses `webcal://.../public/calendar.ics` for Apple Calendar
- Uses Google Calendar subscribe URL built from `/public/calendar.ics`

## Backend route map

Registered in the current app:

- `/`
- `/api/health`
- `/api/ingest`
- `/api/backfill`
- `/api/schedule`
- `/api/schedule/date/{event_date}`
- `/api/compare`
- `/api/casting`
- `/api/casting/show/{show}`
- `/api/casting/import`
- `/api/subscribers`
- `/api/subscribers/{token}`
- `/api/pipeline/nbt`
- `/public/schedule/date/{event_date}`
- `/public/casting`
- `/public/casting/shows`
- `/public/season`
- `/public/subscribe`
- `/public/subscribe/shows`
- `/public/feedback`
- `/public/calendar.ics`
- `/cal/{token}.ics`

## Important finding: admin exists in code but is not live in this app

There is admin code in the repo:

- `/Volumes/workspace/work/nbt-schedule/app/routers/admin.py`
- `/Volumes/workspace/work/nbt-schedule/app/static/admin.html`

But the current app entrypoint does not include that router:

- `/Volumes/workspace/work/nbt-schedule/app/main.py`

That means, in the repo as it exists now:

- `GET /admin` returns `404`
- The admin CRUD endpoints are not registered either

This may mean one of two things:

- The deployed site is running an older or different image than this repo snapshot
- The admin work was started locally but never wired into the app

## Local behavior from this repo

I ran the app locally with:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8017
```

Observed behavior:

- `/api/health` works
- `/` renders the actual app shell correctly
- `/admin` returns `404`
- The daily schedule tab shows `Failed to load schedule. Please try again.`

That last failure is expected locally right now because the frontend tries to fetch schedule data from the database-backed API, and this local app is not connected to a working NBT database from this machine.

The concrete local error was:

- `psycopg2.OperationalError: could not translate host name "zachdb-postgres.zachdb.svc.cluster.local"`

So the default database setting is currently assuming in-cluster DNS.

## Data model and ingestion

The backend stores data in PostgreSQL under schema `nbt`.

Main tables in `sql/001_schema.sql`:

- `nbt.roster`
- `nbt.casting`
- `nbt.schedule_events`
- `nbt.subscribers`
- `nbt.schedule_history`

The system appears to ingest PDFs and email data from Brooke / Gmail, parse them, and write schedule and casting rows into Postgres.

Main ingestion-related files:

- `/Volumes/workspace/work/nbt-schedule/app/routers/ingest.py`
- `/Volumes/workspace/work/nbt-schedule/app/routers/backfill.py`
- `/Volumes/workspace/work/nbt-schedule/nbt-parser/`
- `/Volumes/workspace/work/nbt-schedule/n8n-workflow-brooke-gmail.json`

## Deploy path

The repo includes deploy helpers:

- `/Volumes/workspace/work/nbt-schedule/build-and-push.sh`
- `/Volumes/workspace/work/nbt-schedule/deploy.sh`

The Kubernetes manifest currently lives outside this repo:

- `/Volumes/workspace/infra/manifests/nbt/deployment.yaml`

What that manifest shows:

- Namespace: `nbt`
- Deployment name: `nbt-schedule-service`
- Service name: `nbt-schedule-service`
- Ingress host: `schedule.k3s.local`
- Container port: `8080`
- `imagePullPolicy: Never`

Important deploy implication:

- New images have to be built and manually imported onto worker nodes before restart

## Most useful files to edit

Frontend:

- `/Volumes/workspace/work/nbt-schedule/app/static/index.html`
- `/Volumes/workspace/work/nbt-schedule/app/static/admin.html`
- `/Volumes/workspace/work/nbt-schedule/app/static/sw.js`

Backend:

- `/Volumes/workspace/work/nbt-schedule/app/main.py`
- `/Volumes/workspace/work/nbt-schedule/app/routers/public.py`
- `/Volumes/workspace/work/nbt-schedule/app/routers/schedule.py`
- `/Volumes/workspace/work/nbt-schedule/app/routers/admin.py`
- `/Volumes/workspace/work/nbt-schedule/app/routers/ingest.py`
- `/Volumes/workspace/work/nbt-schedule/app/db.py`
- `/Volumes/workspace/work/nbt-schedule/app/config.py`

Infra:

- `/Volumes/workspace/work/nbt-schedule/deploy.sh`
- `/Volumes/workspace/work/nbt-schedule/build-and-push.sh`
- `/Volumes/workspace/infra/manifests/nbt/deployment.yaml`

## Open questions

- Is the live domain still supposed to point at this exact app?
- Is the current production image older than the code in this repo?
- Should `/admin` be re-enabled in `app/main.py`?
- Is the cluster still reachable from this machine, or has access changed?
- Is the database still intact and populated?

## Good next steps

1. Wire the admin router into `app/main.py` if we want the built-in admin UI back.
2. Add a proper `README.md` for setup and deployment if we decide this repo is the source of truth.
3. Verify Kubernetes access and inspect the live `nbt-schedule-service` pod, service, ingress, and logs.
4. Confirm whether `schedule.naenaewhipwhip.com` is still reverse-proxying to `schedule.k3s.local` or something else.
5. Decide whether to repair this deployment or rebuild a fresh local/dev setup first.

## Cloudflare portability assessment

Short answer:

- The public website can be moved to Cloudflare.
- The current repo cannot be deployed to Cloudflare Pages unchanged.
- The best Cloudflare target is probably `Workers Static Assets + Worker API`, not a pure static Pages deploy.

### Why it is not a straight lift-and-shift

This repo is not just static HTML. It depends on a Python backend and PostgreSQL.

Current backend assumptions:

- FastAPI app in `/Volumes/workspace/work/nbt-schedule/app/main.py`
- Postgres access via `psycopg2` in `/Volumes/workspace/work/nbt-schedule/app/db.py`
- Default DB host is a Kubernetes service DNS name in `/Volumes/workspace/work/nbt-schedule/app/config.py`
- Parser / ingest flow uses Python tooling and machine-level workflows in:
  - `/Volumes/workspace/work/nbt-schedule/app/routers/ingest.py`
  - `/Volumes/workspace/work/nbt-schedule/app/routers/backfill.py`
  - `/Volumes/workspace/work/nbt-schedule/nbt-parser/`
- Docker image installs `poppler-utils` in `/Volumes/workspace/work/nbt-schedule/Dockerfile`

That means the current app assumes:

- a Python server runtime
- direct database connectivity
- native/binary tooling
- background-ish ingestion workflows

### Best Cloudflare fit

Best likely architecture:

1. Move the public frontend to Cloudflare static hosting.
2. Rebuild the public API routes as Cloudflare Worker endpoints.
3. Keep ingestion / PDF parsing as a separate non-Cloudflare service for now.
4. Either keep Postgres and access it from Cloudflare using Hyperdrive, or replace the data layer later.

### What should move first

The public read-only surface is a good Cloudflare candidate:

- `/`
- `/public/schedule/date/{event_date}`
- `/public/casting`
- `/public/casting/shows`
- `/public/season`
- `/public/feedback`
- `/public/calendar.ics`

These endpoints are much simpler than the ingest side and mostly read or write normal app data.

### What should probably not move in phase 1

These parts are poor first candidates for Cloudflare Pages migration:

- Gmail / SSH backfill flow in `/Volumes/workspace/work/nbt-schedule/app/routers/backfill.py`
- PDF ingestion pipeline in `/Volumes/workspace/work/nbt-schedule/app/routers/ingest.py`
- Parser code in `/Volumes/workspace/work/nbt-schedule/nbt-parser/`
- Docker / k3s-specific deploy flow

### Practical migration options

Option A: Frontend only on Cloudflare

- Put `index.html`, `sw.js`, manifest, and static assets on Cloudflare.
- Keep the API elsewhere.
- Update the frontend to use a configurable API base URL instead of same-origin-only relative fetches.

Pros:

- Fastest path
- Lowest rewrite cost

Cons:

- Still need another place for the backend
- CORS / env / routing cleanup required

Option B: Public site fully Cloudflare-native, ingest stays elsewhere

- Serve the public frontend from Cloudflare.
- Rewrite the public endpoints as Worker routes.
- Connect Workers to Postgres via Hyperdrive or another supported path.
- Keep admin + ingest + parsing on a separate service for now.

Pros:

- Good long-term shape
- Public site becomes simple and globally cacheable
- Removes dependency on the current k3s app for user-facing pages

Cons:

- Requires backend rewrite work
- Requires careful DB access design

Option C: Full port of everything

- Rebuild public site, admin, API, and ingest to run on Cloudflare-compatible architecture.

Pros:

- Cleanest end state if fully completed

Cons:

- Highest risk
- Most work by far
- Current parser / ingest tooling is the least natural fit

### My recommendation

If we want something realistic and maintainable:

- Do Option B.

That means:

- Cloudflare for the public site
- separate service for ingestion/parser in the near term
- shared Postgres underneath at first

### Cloudflare doc notes

Relevant current Cloudflare guidance I checked:

- Pages Functions can run server-side code on the Workers runtime:
  https://developers.cloudflare.com/pages/functions/
- Workers Static Assets is the recommended path for new static/full-stack apps, with Pages still supported:
  https://developers.cloudflare.com/workers/best-practices/workers-best-practices/
- Workers can serve static assets and API routes together:
  https://developers.cloudflare.com/workers/static-assets/
- Hyperdrive supports PostgreSQL-compatible databases:
  https://developers.cloudflare.com/hyperdrive/reference/supported-databases-and-features/
- Python Workers exist, but they run under Pyodide and sockets are not functional:
  https://developers.cloudflare.com/workers/languages/python/stdlib/

### Bottom line

Yes, this can be ported to your Cloudflare setup, but not as a direct deploy of the current FastAPI service.

The sensible path is:

- move the frontend
- rewrite only the public API routes for Cloudflare
- leave ingest/parser on a separate backend until later

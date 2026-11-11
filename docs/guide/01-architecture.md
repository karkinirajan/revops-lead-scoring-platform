# 1. How it is built

The platform scores B2B leads from product-usage and engagement signals, ranks them, and tells sales which to call first. A FastAPI service holds the data and the rules, Celery workers do the scheduled and heavy work, and a Next.js app is the interface.

## The pieces

| Piece | What it is | Port (compose, bound to 127.0.0.1) |
|---|---|---|
| `api` | FastAPI: the data, the auth, the scoring rules, the AI endpoints | 8000 |
| `worker` | Celery worker: ingest, feature building, scoring, CRM sync, webhook delivery | none |
| `beat` | Celery beat: the schedule below | none |
| `web` | Next.js 16: pages, plus the proxy (`/bff`) that is the browser's only way to the API | 3000 |
| `postgres` | PostgreSQL 18: all state | 5432 |
| `redis` | Redis 8: the Celery broker, rate-limit counters, the AI report cache | 6379 |
| `flower` | Celery monitoring, only with `--profile monitoring` | 5555 |
| `nginx` | Production only: TLS, rate limits, the one public entry point | 80, 443 |

```
 browser ──► nginx ──► web (Next.js) ──/bff/…──► api ──► postgres
                │                                  │  └──► redis ◄── worker ◄── beat
                └──/api/…────────────────────────► api            │
        other systems (HubSpot webhook, scripts)                    └──► CRMs, webhook receivers
```

Two paths reach the API. **People** go through the web app: the browser talks only to its own origin, and `/bff` adds the access token from an httpOnly cookie (chapter 2). **Other systems** (HubSpot's deal-won webhook, ingestion scripts) call `/api/` with their own credentials.

## The repository

```
apps/api/        FastAPI service (app/), Alembic migrations, tests, Dockerfile
apps/web/        Next.js app (app/, components/, lib/), tests, Dockerfile
workers/         Celery app, tasks, CRM connectors, model training
infra/nginx/     the production reverse proxy
docs/            this guide
```

It is a `uv` workspace: one `uv.lock` for the API and the workers, which share the models and the settings. The API imports the worker tasks to queue them, and the workers import the API's models, so both are installed in one environment.

## The data

| Table | Holds |
|---|---|
| `users` | people who can sign in, with a role: `viewer`, `analyst` or `admin` |
| `companies`, `contacts` | the accounts and people being scored, from a CRM or a CSV |
| `raw_events` | events as they arrived (product usage, email, web), kept before processing |
| `contact_features` | the signals built from the events, one row per contact |
| `scoring_runs`, `lead_scores` | each scoring pass, and the score, tier and reason it gave each contact |
| `model_registry` | machine-learning models: version, stage, accuracy, training rows |
| `conversions` | deals won, to measure how good the tiers are |
| `webhooks`, `webhook_delivery_logs` | outbound subscriptions and every delivery attempt |
| `crm_connections`, `crm_sync_logs` | HubSpot and Salesforce connections (credentials encrypted) and their sync history |
| `audit_logs`, `worker_checkpoints` | an audit trail, and where long jobs resume |

Migrations are Alembic (`apps/api/migrations`). Revision 003 reconciles a drift between the models and revisions 001 and 002: it adds the missing foreign key from `webhook_delivery_logs` to `webhooks`, creates indexes the models declared on four tables, and drops a redundant one (four boolean columns the models declared as integers were corrected in the models). `tests/test_schema.py` creates the schema from the migrations and compares it with the models, so the two cannot drift apart unnoticed again.

## How a lead gets a score

1. **Events in.** `POST /api/v1/ingest` (one) or `/ingest/batch` (up to 500) store the events, then queue them. A CSV file can be loaded with the CLI (`python -m app.cli ingest`).
2. **Features.** `workers.tasks.features` turns events into a row of signals per contact: API calls in the last 7 days, page views, email opens and clicks, docs visits, sessions, whether a demo was requested, the pricing page visited, a free trial is active, an integration is connected, and days since last activity.
3. **Score.** Two engines can score a contact.
   * **v1, a formula** (`services/scoring_engine.py`). Bands and capped per-unit points for usage and engagement, bonuses for a demo request (20), a free trial (15), the pricing page (10) and an integration (8), multiplied by a recency factor (1.0 within a week down to 0.2 after 60 days) and a company-size factor from the contact's company record (enterprise 1.15, mid-market 1.05, SMB 0.95, unknown 1.0). The configuration is versioned (`SCORE_CONFIG`); the tier boundaries are the `SCORING_*_THRESHOLD` settings, shared with the model. It is always available and is the live score. The scheduled task and `make score` build their input and their stored rows with the same code (`services/lead_scoring.py`).
   * **v2, an XGBoost model** (`services/ml_scoring_engine.py`, trained by `workers/training`). Models are stored as JSON, never pickled, and move through stages in `model_registry`: `training`, `shadow`, `champion`, `archived`. A **shadow** model scores every contact too, but its scores are stored with `is_shadow` set and never shown as the live score; once its accuracy is trusted it is promoted (`POST /models/{id}/promote`), and it then replaces the formula.
4. **Tier and action.** The score maps to HOT (75 and up), WARM (50), COOL (25) or COLD, and each tier has a recommended action (immediate outreach, nurture sequence, re-engagement).
5. **Out.** The ranked list is on the Leads page and `GET /scoring/leads`; every lead scoring 50 or more (up to 1,000, best first) is pushed to HubSpot daily; webhooks fire when a live score changes a lead's tier, makes it a new hot lead, changes its score or finds a new demo request, and when a conversion is recorded (a contact's first score is a baseline and fires nothing); the CLI exports a daily CSV.

The **simulator** (`POST /scoring/simulate`, the Simulate page) scores a hand-entered set of signals without storing anything, to show why a lead scores as it does.

### The schedule (Celery beat)

| Job | Every | Queue |
|---|---|---|
| Recompute features | hour | `features` |
| Score all contacts (v1, live) | hour | `scoring` |
| Score all contacts (v2, shadow) | hour | `scoring` |
| Push leads scoring 50+ to HubSpot | day | `sync` |
| Retry failed webhook deliveries | 30 minutes | `sync` |
| Reprocess the dead-letter queue | 30 minutes | `dlq` |
| Retrain the ML model | 7 days | `scoring` |

Queues: `ingest`, `features`, `scoring`, `sync`, `dlq`. The schedule and the routing are `workers/celery_app.py`; a test checks every scheduled task exists and has a route.

## AI intelligence

`GET /contacts/{id}/intelligence` streams a short analysis of a lead (why it scores as it does, a suggested next step, an outreach draft) from Claude as server-sent events; `/intelligence/sync` returns the whole report and caches it for six hours. `POST /leads/search` turns a plain-English query into a filter. The model is `AI_MODEL`; without `ANTHROPIC_API_KEY` the endpoints answer 503 "not configured" and the rest of the platform is unaffected. Reports are rate-limited per user.

## The web app

Pages (`apps/web/app/(app)`): Dashboard, Leads (filter by tier and score, page, export CSV, per-lead AI report), Companies, Analytics (precision per tier, score distribution, conversions), Integrations (HubSpot and Salesforce sync), Run History (and "Run scoring"), Simulate, Settings (what the server is configured with, webhooks, models).

* Server components fetch through `lib/server/api.ts` (the token comes from the cookie); client components through `lib/api.ts`, which calls `/bff`.
* `proxy.ts` (Next 16's replacement for middleware) guards every page: signed out goes to `/login`, an expiring access token is refreshed before the page renders.
* The layout is a fixed side navigation from tablet width up and a menu button below it.
* Colours are tokens in `app/globals.css`; the text and accent tokens were chosen to clear WCAG AA contrast (4.5:1) on every surface, measured in the rendered app.

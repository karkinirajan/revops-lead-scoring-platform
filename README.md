# RevOps Lead Scoring Platform v2

A production-ready, queue-based lead scoring platform that ingests millions of records per day from multiple GTM sources, scores them with both deterministic and ML-powered logic, delivers real-time webhook notifications, and syncs enriched leads back to Salesforce and HubSpot — all powered by AI-driven intelligence.

```
Sources (HubSpot, Salesforce, CSV, Webhooks)
         │
         ▼
  Connector Layer  ──►  Raw Landing (raw_events table)
         │
         ▼
  Redis + Celery Queue Bus
  ┌──────┬──────────┬─────────┬──────┬──────────┬─────┐
  ingest features  scoring   sync   webhooks   dlq
         │
         ▼
  PostgreSQL  ──►  Scoring Engine (v1 + XGBoost v2)
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
         Lead Scores   Webhooks   Model Registry
              │
     ┌────────┴────────┐
     ▼                 ▼
HubSpot Sync    Salesforce Sync
                          │
                          ▼
              Conversion Feedback Loop
                    (precision/recall per tier)
```

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.115, Python 3.11, Pydantic v2, Uvicorn/Gunicorn |
| Database | PostgreSQL 16 (Neon-compatible), SQLAlchemy 2.x, Alembic |
| Queue / Cache | Redis 7, Celery 5.4 |
| Workers | Celery workers — `ingest`, `features`, `scoring`, `sync`, `webhooks`, `dlq` |
| ML | XGBoost 2.x, scikit-learn, joblib — champion/shadow model registry |
| AI Intelligence | Anthropic Claude (`claude-sonnet-4-6`) — SSE streaming + NL search |
| Frontend | Next.js 15 App Router, TypeScript, Tailwind CSS |
| Auth | JWT (HS256) with RBAC — `admin`, `analyst`, `viewer` |
| Proxy | Nginx (TLS termination, rate limiting, security headers) |
| CI/CD | GitHub Actions — lint, test, SAST, dependency audit, Docker builds |

---

## What's New in v2

### Feature 1 — ML Scoring Engine (XGBoost)
An XGBoost gradient-boosting model trained on historical conversion data runs alongside the deterministic v1 engine in **shadow mode**. Once promoted to champion (via the Model Registry API), all new scores use the ML model. The v1 engine remains the fallback when no champion artifact exists.

- 16-feature input vector (API usage, engagement signals, company size one-hot encoding)
- Training pipeline: `python -m workers.training.train_model`
- Champion/shadow/archived lifecycle via `/api/v1/models` endpoints
- Weekly automatic retraining via Celery beat
- Shadow scoring task runs hourly in parallel for model evaluation

### Feature 2 — Conversion Feedback Loop
Track closed deals to measure how accurately the scoring model predicts real conversions. Capture conversions via REST API or HubSpot deal webhooks, then query per-tier precision and recall over any time window.

- `POST /api/v1/analytics/conversions` — record a conversion with deal value and tier/score at time of conversion
- `POST /api/v1/analytics/conversions/hubspot` — HMAC-verified HubSpot deal-won webhook receiver
- `GET /api/v1/analytics/model-accuracy` — precision/recall/conversion-rate per tier
- `GET /api/v1/analytics/score-distribution` — histogram of lead scores across the database
- Analytics dashboard page in the operations console

### Feature 3 — Webhook Delivery Engine
Register HTTP endpoints to receive real-time notifications on lead events. Payloads are signed with HMAC-SHA256. Failed deliveries retry automatically with exponential backoff (30s → 5min → 30min).

- Events: `tier_crossed`, `score_updated`, `demo_requested`, `hot_lead`, `conversion`
- Optional tier filter (e.g., fire only for HOT leads)
- Full CRUD via `/api/v1/webhooks` with per-webhook delivery audit log
- Test endpoint (`POST /{id}/test`) sends a live delivery synchronously
- Manual retry via `POST /{id}/deliveries/{did}/retry`
- Webhook management UI in the Settings page

### Feature 4 — Salesforce Connector
Bidirectional sync with Salesforce Sales Cloud via REST API v59 and incremental SOQL pulls. Reads contacts modified since the last watermark and writes lead scores back via Composite API batch updates.

- Incremental pull using `LastModifiedDate` watermark — no full scans
- Maps `Id`, `Email`, `FirstName`, `LastName`, `Title`, `AccountId`, `LeadSource`
- Pushes `RevOps_Lead_Score__c`, `RevOps_Priority_Tier__c`, `RevOps_Score_Reason__c` fields back to Salesforce
- OAuth callback endpoint at `POST /api/v1/integrations/salesforce/oauth/callback`
- Managed from the Integrations page (Pull / Push Scores buttons)

### Feature 5 — AI Lead Intelligence
Each lead gets an AI-generated analysis powered by Claude. Explains *why* the lead is hot, what signals are driving the score, and recommends next best actions. Also exposes natural language search: type "HOT leads who visited the pricing page and connected an integration" and get back a structured filter.

- `GET /api/v1/contacts/{id}/intelligence` — SSE streaming response (real-time text generation)
- `GET /api/v1/contacts/{id}/intelligence/sync` — cached non-streaming response (1h TTL)
- `POST /api/v1/leads/search` — natural language → structured filter object
- LeadIntelligencePanel component in the leads list — "AI Intel" button triggers live stream
- Rate-limited by `ai_intelligence_rate_limit_per_minute` (default: 20 req/min)

---

## Quick Start (Docker Compose)

**Requirements:** Docker ≥ 24, Docker Compose v2

```bash
# 1. Clone and configure
git clone https://github.com/kneeraazon404/revops-lead-scoring-platform.git
cd revops-lead-scoring-platform
cp .env.example .env            # fill in at minimum: APP_SECRET_KEY, JWT_SECRET_KEY

# 2. Start all services
make up
# API     → http://localhost:8000/docs
# Web     → http://localhost:3000
# Flower  → http://localhost:5555  (queue monitor)

# 3. Seed the database with synthetic data
make seed                       # creates admin user + 100 test contacts

# 4. Run the pipeline end to end
make score                      # score all contacts
make export                     # export top 50 to data/processed/daily_top_50.csv
make sync-hubspot               # sync top leads to HubSpot (requires HUBSPOT_ACCESS_TOKEN)

# 5. Train and register the ML model (optional)
make train-ml                   # python -m workers.training.train_model
```

---

## Project Structure

```
revops-lead-scoring-platform/
├── apps/
│   ├── api/                        # FastAPI backend
│   │   ├── app/
│   │   │   ├── api/v1/             # REST endpoints
│   │   │   │   ├── auth.py             # JWT login/refresh, user management
│   │   │   │   ├── contacts.py         # Contact CRUD + feature lookup
│   │   │   │   ├── companies.py        # Company browser
│   │   │   │   ├── scoring.py          # Scoring runs, simulation, ranked leads
│   │   │   │   ├── ingest.py           # Raw event ingestion (single + batch)
│   │   │   │   ├── analytics.py        # Conversions, model accuracy, score distribution
│   │   │   │   ├── webhooks.py         # Webhook CRUD + delivery logs + retry
│   │   │   │   ├── model_registry.py   # ML model lifecycle (promote/shadow/archive)
│   │   │   │   ├── integrations.py     # CRM connection management + OAuth
│   │   │   │   └── intelligence.py     # AI lead intelligence + NL search
│   │   │   ├── auth/               # JWT utilities and FastAPI dependencies
│   │   │   ├── models/             # SQLAlchemy 2.x ORM models
│   │   │   │   ├── contact.py
│   │   │   │   ├── company.py
│   │   │   │   ├── lead_score.py
│   │   │   │   ├── conversion.py       # NEW: deal-won feedback records
│   │   │   │   ├── webhook.py          # NEW: webhook targets + delivery audit log
│   │   │   │   ├── model_registry.py   # NEW: ML model registry with stage lifecycle
│   │   │   │   └── crm_connection.py   # NEW: HubSpot/Salesforce OAuth credentials
│   │   │   ├── services/
│   │   │   │   ├── scoring_engine.py   # Deterministic v1 scoring formula
│   │   │   │   ├── ml_scoring_engine.py  # NEW: XGBoost v2 scoring engine
│   │   │   │   ├── webhook_service.py    # NEW: HMAC signing + delivery + retry
│   │   │   │   ├── ai_intelligence.py    # NEW: Claude SSE streaming + NL search
│   │   │   │   └── crm_sync.py           # HubSpot batch upsert client
│   │   │   ├── middleware/         # Structured logging, rate limiting
│   │   │   ├── cli.py              # Typer CLI (ingest, score, export, sync, seed)
│   │   │   ├── config.py           # Pydantic settings from environment
│   │   │   ├── database.py         # SQLAlchemy engine and session
│   │   │   └── main.py             # FastAPI app factory
│   │   ├── migrations/
│   │   │   └── versions/
│   │   │       ├── 001_initial_schema.py       # 10 core tables
│   │   │       └── 002_conversions_webhooks_ml_crm.py  # NEW: 5 v2 tables
│   │   └── tests/                  # 71 pytest unit tests (0 failures)
│   │       ├── conftest.py
│   │       ├── test_conversions.py
│   │       ├── test_webhooks.py
│   │       ├── test_ml_scoring_engine.py
│   │       ├── test_salesforce_connector.py
│   │       └── test_ai_intelligence.py
│   │
│   └── web/                        # Next.js 15 operations console
│       ├── app/(app)/
│       │   ├── dashboard/          # KPI cards + top HOT leads + recent runs
│       │   ├── leads/              # Filterable ranked leads table + AI Intel panel
│       │   ├── companies/          # Company browser
│       │   ├── runs/               # Scoring run history
│       │   ├── simulate/           # What-if score simulator
│       │   ├── analytics/          # NEW: tier accuracy, score distribution, conversions
│       │   ├── integrations/       # NEW: CRM connection management (HubSpot + Salesforce)
│       │   └── settings/           # UPDATED: env vars, webhook CRUD, ML model registry
│       ├── components/
│       │   ├── leads/
│       │   │   └── LeadIntelligencePanel.tsx  # NEW: SSE streaming AI intel
│       │   └── layout/Sidebar.tsx  # UPDATED: Analytics + Integrations nav items
│       └── lib/
│           ├── api.ts              # API client
│           └── types.ts            # TypeScript types (incl. v2 types)
│
├── workers/
│   ├── celery_app.py               # Queue config, routing, extended beat schedule
│   ├── tasks/
│   │   ├── ingest.py               # Validate → normalize → upsert → trigger features
│   │   ├── features.py             # Incremental feature aggregation per contact
│   │   ├── scoring.py              # UPDATED: v1 + ML scoring, shadow mode
│   │   ├── sync.py                 # HubSpot CRM batch sync
│   │   ├── webhooks.py             # NEW: Celery webhook delivery + retry sweep
│   │   └── dlq.py                  # Dead-letter reprocessor (every 30 min)
│   ├── connectors/
│   │   ├── base.py                 # BaseConnector interface
│   │   ├── hubspot.py              # HubSpot v3 incremental connector
│   │   ├── csv_connector.py        # Local filesystem + S3-compatible CSV connector
│   │   └── salesforce.py           # NEW: Salesforce REST v59 connector + sync service
│   └── training/
│       └── train_model.py          # NEW: XGBoost training pipeline + model registration
│
├── infra/
│   └── nginx/nginx.conf            # Reverse proxy, TLS, rate limiting
├── docker-compose.yml
├── docker-compose.prod.yml
├── Makefile
└── .env.example                    # Full environment variable reference (v1 + v2)
```

---

## Data Model

Four-layer warehouse model (v2):

```
raw_events              ← immutable append-only source snapshots
    │
    ▼
contacts + companies + contact_features   ← normalized core entities
    │
    ▼
lead_scores + scoring_runs                ← scored outputs with lineage
    │
    ▼
conversions + webhooks + webhook_delivery_logs
model_registry + crm_connections          ← v2 feedback + delivery + ML
    │
    ▼
crm_sync_logs + audit_logs               ← observability and compliance
```

**All 15 tables:**

| Table | Purpose |
|---|---|
| `contacts` | Normalized contact records |
| `companies` | Company master |
| `contact_features` | Aggregated behavioral signals per contact |
| `raw_events` | Immutable ingest landing zone |
| `lead_scores` | Scored outputs with model version + tier |
| `scoring_runs` | Batch run audit (contacts processed, errors, duration) |
| `crm_sync_logs` | Per-contact sync outcomes to HubSpot/Salesforce |
| `audit_logs` | Score overrides and privileged action log |
| `users` | Platform user accounts with RBAC roles |
| `api_keys` | Programmatic API key management |
| `conversions` | Deal-won records linking contact → score → tier at time of close |
| `webhooks` | Registered HTTP endpoints with event filters |
| `webhook_delivery_logs` | Immutable delivery attempt audit with retry tracking |
| `model_registry` | ML model versions with metrics and stage lifecycle |
| `crm_connections` | OAuth credentials and sync settings per CRM connection |

---

## API Reference

Base URL: `http://localhost:8000/api/v1`  
Interactive docs: `http://localhost:8000/docs`

### Auth
| Method | Path | Description |
|---|---|---|
| POST | `/auth/login` | Get JWT access + refresh tokens |
| GET | `/auth/me` | Current user info |
| POST | `/auth/users` | Create user (admin only) |

### Contacts & Companies
| Method | Path | Description |
|---|---|---|
| GET | `/contacts` | List contacts (paginated, filterable) |
| POST | `/contacts` | Create contact |
| GET | `/contacts/{id}` | Get contact with features |
| PATCH | `/contacts/{id}` | Update contact |
| GET | `/companies` | List companies (paginated) |
| POST | `/companies` | Create company |

### Scoring
| Method | Path | Description |
|---|---|---|
| GET | `/scoring/leads` | Ranked leads — latest score per contact |
| POST | `/scoring/simulate` | What-if score simulation (no persistence) |
| POST | `/scoring/runs` | Trigger a scoring run (async) |
| GET | `/scoring/runs` | List recent runs |
| GET | `/scoring/runs/{id}` | Get run status |

### Ingest
| Method | Path | Description |
|---|---|---|
| POST | `/ingest` | Accept a single raw event |
| POST | `/ingest/batch` | Accept up to 500 raw events |

### Analytics (v2)
| Method | Path | Description |
|---|---|---|
| POST | `/analytics/conversions` | Record a deal-won conversion |
| GET | `/analytics/conversions` | List conversion records (paginated) |
| POST | `/analytics/conversions/hubspot` | HMAC-verified HubSpot deal webhook receiver |
| GET | `/analytics/model-accuracy` | Precision/recall/rate per tier (optional date range) |
| GET | `/analytics/score-distribution` | Lead score histogram (10-point buckets) |

### Webhooks (v2)
| Method | Path | Description |
|---|---|---|
| GET | `/webhooks` | List registered webhooks |
| POST | `/webhooks` | Register a new webhook |
| GET | `/webhooks/{id}` | Get webhook details |
| PATCH | `/webhooks/{id}` | Update webhook (URL, events, filters, status) |
| DELETE | `/webhooks/{id}` | Delete webhook |
| GET | `/webhooks/{id}/deliveries` | Delivery history (paginated) |
| POST | `/webhooks/{id}/test` | Send a live test delivery (synchronous) |
| POST | `/webhooks/{id}/deliveries/{did}/retry` | Manually retry a failed delivery |

### ML Model Registry (v2)
| Method | Path | Description |
|---|---|---|
| GET | `/models` | List all registered model versions |
| GET | `/models/champion/features` | Feature importances for current champion |
| GET | `/models/{id}` | Get model details and metrics |
| POST | `/models/{id}/promote` | Promote model to champion (archives existing) |
| POST | `/models/{id}/shadow` | Demote model to shadow mode |

### Integrations (v2)
| Method | Path | Description |
|---|---|---|
| GET | `/integrations` | List CRM connections |
| POST | `/integrations` | Register a CRM connection |
| PATCH | `/integrations/{id}` | Update credentials or settings |
| DELETE | `/integrations/{id}` | Remove connection |
| GET | `/integrations/{id}/status` | Test connectivity + last sync timestamps |
| POST | `/integrations/{id}/sync-inbound` | Trigger a pull from the CRM |
| POST | `/integrations/{id}/sync-outbound` | Push scores to the CRM |
| POST | `/integrations/salesforce/oauth/callback` | Exchange Salesforce auth code for tokens |

### AI Intelligence (v2)
| Method | Path | Description |
|---|---|---|
| GET | `/contacts/{id}/intelligence` | SSE streaming AI lead analysis (text/event-stream) |
| GET | `/contacts/{id}/intelligence/sync` | Cached non-streaming analysis (1h TTL) |
| POST | `/leads/search` | Natural language → structured filter parsing |

### System
| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/ready` | Readiness check (DB ping) |
| GET | `/metrics` | Process resource metrics |

---

## Scoring Models

### v1 — Deterministic (always available as fallback)

Scores are reproducible: the same feature vector always produces the same score.

| Signal | Points |
|---|---|
| API calls 7d: 5–50 (sweet spot) | 30 |
| API calls 7d: 1–4 | 10 |
| API calls 7d: 51–500 | 18 |
| API calls 7d: 500+ | 8 |
| Page views 7d | +2 per view (cap 14) |
| Email clicks 7d | +5 per click (cap 15) |
| Email opens 7d | +1 per open (cap 5) |
| Demo requested | +20 |
| Pricing page visited | +10 |
| Free trial active | +15 |
| Integration connected | +8 |
| Integrations count | +2 each (cap 10) |

**Recency decay:** ×1.0 (0–7d) → ×0.9 (8–14d) → ×0.7 (15–30d) → ×0.45 (31–60d) → ×0.2 (60d+)

**Company size multiplier:** Enterprise ×1.15 · Mid-market ×1.05 · SMB ×0.95

### v2 — XGBoost ML Model

Trained on `contact_features` joined with `conversions`, optimizing for deal-won prediction.

**Feature vector (16 columns):**
`api_calls_7d`, `api_calls_30d`, `page_views_7d`, `pricing_page_visited`, `email_opens_7d`, `email_clicks_7d`, `docs_page_visits_7d`, `demo_requested`, `free_trial_active`, `integration_connected`, `integrations_count`, `sessions_7d`, `days_since_last_activity`, `company_size_enterprise`, `company_size_mid_market`, `company_size_smb`

**Training:**
```bash
python -m workers.training.train_model
# Trains on all contacts with conversion labels
# Saves artifact to $ML_MODELS_DIR/v<version>.pkl
# Registers entry in model_registry with metrics
# Defaults to shadow stage — promote manually when satisfied
```

**Priority tiers (both models):** HOT ≥ 75 · WARM ≥ 50 · COOL ≥ 25 · COLD < 25

Every score output includes `feature_contributions` (per-signal breakdown), `score_reason` (human-readable summary), and `model_version`.

---

## Webhook Payload Format

All webhook deliveries include an `X-RevOps-Signature` header for HMAC-SHA256 verification.

```json
{
  "event": "tier_crossed",
  "contact_id": "abc123",
  "contact_email": "alice@acme.com",
  "lead_score": 88,
  "priority_tier": "HOT",
  "previous_tier": "WARM",
  "score_reason": "demo_requested (+20), api_calls_7d (+30)",
  "timestamp": "2026-04-08T10:00:00Z",
  "delivery_id": "d1e2f3..."
}
```

**Verifying the signature (Python):**
```python
import hmac, hashlib
expected = hmac.new(
    secret.encode(), raw_body, hashlib.sha256
).hexdigest()
assert hmac.compare_digest(expected, request.headers["X-RevOps-Signature"])
```

**Retry schedule:** 30s → 5 min → 30 min (max 4 attempts total). After exhaustion the delivery log status is `failed`.

---

## Queue Architecture

| Queue | Purpose | Consumer |
|---|---|---|
| `ingest` | Raw event normalization and deduplication | `process_raw_event` |
| `features` | Incremental feature aggregation | `compute_features_for_contact_task` |
| `scoring` | Per-contact score computation (v1 + v2) | `score_single_contact` |
| `sync` | Outbound HubSpot / Salesforce CRM upserts | `sync_contact_to_hubspot` |
| `webhooks` | Asynchronous webhook delivery | `deliver_webhook` |
| `dlq` | Dead-letter reprocessing (retry exhausted) | `reprocess_dlq` |

**Beat schedule (v2):**

| Task | Schedule |
|---|---|
| Feature recompute | Every hour |
| Scoring run (v1) | Every hour |
| Shadow ML scoring | Every hour (parallel, shadow=True) |
| HubSpot sync | Daily |
| Webhook retry sweep | Every 30 minutes |
| DLQ reprocessor | Every 30 minutes |
| ML model retrain | Weekly |

---

## Environment Variables

See [`.env.example`](.env.example) for the full reference.

### Core (required)
```bash
APP_SECRET_KEY=          # openssl rand -hex 32
JWT_SECRET_KEY=          # openssl rand -hex 32
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/revops
REDIS_URL=redis://localhost:6379/0
```

### HubSpot
```bash
HUBSPOT_ACCESS_TOKEN=
HUBSPOT_PORTAL_ID=
HUBSPOT_WEBHOOK_SECRET=  # for deal-won webhook verification
```

### Salesforce (v2)
```bash
SALESFORCE_CLIENT_ID=
SALESFORCE_CLIENT_SECRET=
SALESFORCE_REDIRECT_URI=https://your-domain/api/v1/integrations/salesforce/oauth/callback
SALESFORCE_LOGIN_URL=https://login.salesforce.com   # or sandbox URL
```

### AI Intelligence (v2)
```bash
ANTHROPIC_API_KEY=       # get from console.anthropic.com
AI_INTELLIGENCE_CACHE_TTL_SECONDS=3600
AI_INTELLIGENCE_RATE_LIMIT_PER_MINUTE=20
```

### ML Model (v2)
```bash
ML_MODELS_DIR=data/models   # directory for .pkl artifacts
```

---

## CLI Reference

```bash
# Ingest raw records
python -m app.cli ingest --source-dir data/raw/

# Recompute feature aggregations
python -m app.cli build-views

# Run a full scoring pass (v1 deterministic)
python -m app.cli score-leads

# Run in shadow mode (scores stored but not promoted)
python -m app.cli score-leads --shadow

# Export top N leads to CSV
python -m app.cli export-daily-list --top-n 50 --out data/processed/daily_top_50.csv

# Sync to HubSpot
python -m app.cli sync-hubspot --csv data/processed/daily_top_50.csv

# Seed database with synthetic data
python -m app.cli seed --count 500

# Train ML model and register in model registry
python -m workers.training.train_model
```

---

## Development

```bash
# Install dependencies locally (without Docker)
make install-api    # pip install -e ".[dev]" in apps/api
make install-web    # npm install in apps/web

# Run migrations (includes v2 tables)
make migrate

# Run tests (71 tests, 0 failures)
make test-api       # pytest with coverage
make lint           # ruff + mypy + eslint
make format         # ruff format + ruff --fix

# Individual services
make api-dev        # uvicorn --reload on :8000
make worker-dev     # celery worker (local)
make web-dev        # next dev on :3000

# Train ML model
make train-ml       # python -m workers.training.train_model
```

---

## Production Deployment

```bash
# Build all images
docker build -t revops-api:latest    --target production apps/api
docker build -t revops-worker:latest --target production workers
docker build -t revops-web:latest    --target production apps/web

# Deploy
IMAGE_TAG=latest docker compose -f docker-compose.prod.yml up -d

# Rollback
IMAGE_TAG=<previous-sha> docker compose -f docker-compose.prod.yml up -d
```

The production compose file runs 2 API replicas and 2 worker replicas behind Nginx, with internal-only database networking and Redis password auth.

---

## Security

- All secrets managed via environment variables — never committed to source control
- JWT HS256 tokens with configurable expiry
- RBAC with three roles: `admin`, `analyst`, `viewer`
- Webhook payloads signed with HMAC-SHA256 per-secret
- PII fields redacted from structured logs (`Authorization`, `password`, `token`, `secret`)
- Append-only `audit_logs` table for score overrides and privileged actions
- HubSpot and Salesforce webhook receivers verified with HMAC before processing
- TLS termination at Nginx with TLSv1.2/1.3 only
- Rate limiting at both Nginx (zone-based) and API (slowapi + Redis)
- Dependency vulnerability scanning via `pip-audit` in CI
- Static analysis via Bandit in CI
- Container images run as non-root user

---

## CI/CD (GitHub Actions)

On every push to `main` / `develop` and all PRs:

1. **API lint** — Ruff check + format check
2. **API tests** — pytest (71 tests) against live Postgres + Redis services
3. **Security scan** — Bandit SAST + pip-audit dependency audit
4. **Web lint** — ESLint + TypeScript type check
5. **Web build** — `next build` production build verification
6. **Docker builds** — All three images built for `production` target

All jobs must pass before merge.

---

## License

See [LICENSE](LICENSE).

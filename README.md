# RevOps Lead Scoring Platform

A production-ready, queue-based lead scoring pipeline that ingests millions of records per day from multiple GTM sources, scores them with deterministic and explainable logic, and syncs ranked leads to HubSpot.

```
Sources (HubSpot, Salesforce, CSV, Webhooks)
         │
         ▼
  Connector Layer  ──►  Raw Landing (raw_events table)
         │
         ▼
  Redis + Celery Queue Bus
  ┌──────┬──────────┬─────────┬──────┬─────┐
  ingest features  scoring   sync   dlq
         │
         ▼
  PostgreSQL  ──►  Scoring Engine  ──►  Lead Scores
                                          │
                                          ▼
                              HubSpot Batch Upsert
```

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.115, Python 3.11, Pydantic v2, Uvicorn/Gunicorn |
| Database | PostgreSQL 16 (Neon-compatible), SQLAlchemy 2.x, Alembic |
| Queue / Cache | Redis 7, Celery 5.4 |
| Workers | Celery workers — `ingest`, `features`, `scoring`, `sync`, `dlq` |
| Frontend | Next.js 15 App Router, TypeScript, Tailwind CSS |
| Auth | JWT (HS256) with RBAC — `admin`, `analyst`, `viewer` |
| Proxy | Nginx (TLS termination, rate limiting, security headers) |
| CI/CD | GitHub Actions — lint, test, SAST, dependency audit, Docker builds |

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
# API  → http://localhost:8000/docs
# Web  → http://localhost:3000
# Flower (queue monitor) → http://localhost:5555

# 3. Seed the database with synthetic data
make seed                       # creates admin user + 100 test contacts

# 4. Run the pipeline end to end
make score                      # score all contacts
make export                     # export top 50 to data/processed/daily_top_50.csv
make sync-hubspot               # sync top leads to HubSpot (requires HUBSPOT_ACCESS_TOKEN)
```

---

## Project Structure

```
revops-lead-scoring-platform/
├── apps/
│   ├── api/                        # FastAPI backend
│   │   ├── app/
│   │   │   ├── api/v1/             # REST endpoints (auth, contacts, companies, scoring, ingest)
│   │   │   ├── auth/               # JWT utilities and FastAPI dependencies
│   │   │   ├── models/             # SQLAlchemy 2.x ORM models
│   │   │   ├── schemas/            # Pydantic v2 request/response schemas
│   │   │   ├── services/
│   │   │   │   ├── scoring_engine.py   # Deterministic v1 scoring formula
│   │   │   │   └── crm_sync.py         # HubSpot batch upsert client
│   │   │   ├── middleware/         # Structured logging, rate limiting
│   │   │   ├── cli.py              # Typer CLI (ingest, score, export, sync, seed)
│   │   │   ├── config.py           # Pydantic settings from environment
│   │   │   ├── database.py         # SQLAlchemy engine and session
│   │   │   └── main.py             # FastAPI app factory
│   │   ├── migrations/
│   │   │   └── versions/
│   │   │       └── 001_initial_schema.py   # All 10 core tables
│   │   └── tests/                  # pytest unit tests
│   │
│   └── web/                        # Next.js 15 operations console
│       ├── app/(app)/
│       │   ├── dashboard/          # KPI cards + top HOT leads + recent runs
│       │   ├── leads/              # Filterable ranked leads table with CSV export
│       │   ├── companies/          # Company browser
│       │   ├── runs/               # Scoring run history
│       │   ├── simulate/           # What-if score simulator
│       │   └── settings/           # Platform configuration reference
│       ├── components/             # Sidebar, TierBadge, ScoreBar, StatCard, tables
│       └── lib/                    # API client (lib/api.ts), shared types
│
├── workers/
│   ├── celery_app.py               # Queue config, routing, beat schedule
│   ├── tasks/
│   │   ├── ingest.py               # Validate → normalize → upsert → trigger features
│   │   ├── features.py             # Incremental feature aggregation per contact
│   │   ├── scoring.py              # Fan-out per-contact scoring tasks
│   │   ├── sync.py                 # HubSpot CRM batch sync
│   │   └── dlq.py                  # Dead-letter reprocessor (every 30 min)
│   └── connectors/
│       ├── base.py                 # BaseConnector interface (fetch / normalize / checkpoint / publish)
│       ├── hubspot.py              # HubSpot v3 incremental connector (contacts + companies)
│       └── csv_connector.py        # Local filesystem + S3-compatible CSV connector
│
├── infra/
│   └── nginx/nginx.conf            # Reverse proxy, TLS, rate limiting, security headers
├── docker-compose.yml              # Local development (hot reload)
├── docker-compose.prod.yml         # Production (replicas, internal network, blue/green ready)
├── Makefile                        # All developer commands
└── .env.example                    # Full environment variable reference
```

---

## CLI Reference

```bash
# Ingest raw records from a local directory (JSON or CSV files)
python -m app.cli ingest --source-dir data/raw/

# Recompute feature aggregations for all contacts
python -m app.cli build-views

# Run a full scoring pass (all contacts, default model version)
python -m app.cli score-leads

# Run scoring for a specific segment only
python -m app.cli score-leads --segment enterprise

# Run in shadow mode (scores stored but not promoted)
python -m app.cli score-leads --shadow

# Export top N leads to CSV
python -m app.cli export-daily-list --top-n 50 --out data/processed/daily_top_50.csv

# Sync exported CSV to HubSpot
python -m app.cli sync-hubspot --csv data/processed/daily_top_50.csv

# Seed database with synthetic data for local development
python -m app.cli seed --count 500
```

---

## API Endpoints

Base URL: `http://localhost:8000/api/v1`  
Interactive docs: `http://localhost:8000/docs`

| Method | Path | Description |
|---|---|---|
| POST | `/auth/login` | Get JWT access + refresh tokens |
| GET | `/auth/me` | Current user info |
| POST | `/auth/users` | Create user (admin only) |
| GET | `/contacts` | List contacts (paginated, filterable) |
| POST | `/contacts` | Create contact |
| GET | `/contacts/{id}` | Get contact with features |
| PATCH | `/contacts/{id}` | Update contact |
| GET | `/companies` | List companies (paginated) |
| POST | `/companies` | Create company |
| GET | `/scoring/leads` | Ranked leads — latest score per contact |
| POST | `/scoring/simulate` | What-if score simulation (no persistence) |
| POST | `/scoring/runs` | Trigger a scoring run (async) |
| GET | `/scoring/runs` | List recent runs |
| GET | `/scoring/runs/{id}` | Get run status |
| POST | `/ingest` | Accept a single raw event |
| POST | `/ingest/batch` | Accept up to 500 raw events |
| GET | `/health` | Liveness check |
| GET | `/ready` | Readiness check (includes DB ping) |
| GET | `/metrics` | Process resource metrics |

---

## Scoring Model (v1)

Scores are deterministic — the same feature vector always produces the same score.

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

**Priority tiers:** HOT ≥ 75 · WARM ≥ 50 · COOL ≥ 25 · COLD < 25

Every score output includes `feature_contributions` (per-signal breakdown) and `score_reason` (human-readable summary).

---

## Queue Architecture

| Queue | Purpose | Consumer |
|---|---|---|
| `ingest` | Raw event normalization and deduplication | `process_raw_event` task |
| `features` | Incremental feature aggregation | `compute_features_for_contact_task` |
| `scoring` | Per-contact score computation | `score_single_contact` task |
| `sync` | Outbound HubSpot CRM upserts | `sync_contact_to_hubspot` task |
| `dlq` | Dead-letter reprocessing (retry exhausted) | `reprocess_dlq` task |

**Beat schedule** (default):  
- Feature recompute: every hour  
- Scoring run: every hour  
- HubSpot sync: daily  
- DLQ reprocessor: every 30 minutes  

All tasks use `ack_late=True`, idempotency keys (Redis TTL 24h), and exponential backoff with jitter.

---

## Data Model

Three-layer warehouse model:

```
raw_events          ← immutable append-only source snapshots
    │
    ▼
contacts + companies + contact_features   ← normalized core entities
    │
    ▼
lead_scores + scoring_runs                ← scored outputs with lineage
    │
    ▼
crm_sync_logs + audit_logs               ← observability and compliance
```

---

## Environment Variables

See [`.env.example`](.env.example) for the full reference. Critical variables:

```bash
# Security (required — use: openssl rand -hex 32)
APP_SECRET_KEY=
JWT_SECRET_KEY=

# Database
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/revops

# Redis
REDIS_URL=redis://localhost:6379/0

# HubSpot (optional for local dev, required for sync)
HUBSPOT_ACCESS_TOKEN=
HUBSPOT_PORTAL_ID=
```

---

## Development

```bash
# Install dependencies locally (without Docker)
make install-api    # pip install -e ".[dev]" in apps/api
make install-web    # npm install in apps/web

# Run migrations
make migrate

# Run tests
make test-api       # pytest with coverage
make lint           # ruff + mypy + eslint
make format         # ruff format + ruff --fix

# Individual services
make api-dev        # uvicorn --reload on :8000
make worker-dev     # celery worker (local)
make web-dev        # next dev on :3000
```

---

## Production Deployment

```bash
# Build all images
docker build -t revops-api:latest    --target production apps/api
docker build -t revops-worker:latest --target production workers
docker build -t revops-web:latest    --target production apps/web

# Deploy (requires .env with production values)
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
- PII fields redacted from structured logs (`Authorization`, `password`, `token`, `secret`)
- Append-only `audit_logs` table for score overrides and privileged actions
- TLS termination at Nginx with TLSv1.2/1.3 only
- Rate limiting at both Nginx (zone-based) and API (slowapi + Redis)
- Dependency vulnerability scanning via `pip-audit` in CI
- Static analysis via Bandit in CI
- Container images run as non-root user

---

## CI/CD (GitHub Actions)

On every push to `main` / `develop` and all PRs:

1. **API lint** — Ruff check + format check
2. **API tests** — pytest against live Postgres + Redis services
3. **Security scan** — Bandit SAST + pip-audit dependency audit
4. **Web lint** — ESLint + TypeScript type check
5. **Web build** — `next build` production build verification
6. **Docker builds** — All three images built for `production` target

All jobs must pass before merge.

---

## License

See [LICENSE](LICENSE).

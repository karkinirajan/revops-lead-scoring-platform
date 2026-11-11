# RevOps API

The FastAPI service behind the platform: the data, the authentication, the scoring rules, the CRM and AI integrations. Python 3.12 or newer (3.14 is pinned), SQLAlchemy 2, Alembic, PyJWT, bcrypt, Celery for the work it hands to the workers.

## Run it

From the repository root (this is one package in a `uv` workspace with `workers/`):

```bash
make install                 # uv sync for the workspace, npm ci for the web app
make migrate                 # alembic upgrade head (needs DATABASE_URL)
make api-dev                 # uvicorn with reload on http://localhost:8000, docs at /docs
```

Settings are environment variables (a `.env` file is read too); `app/config.py` lists every one with its default, and [chapter 3 of the guide](../../docs/guide/03-running-and-operating.md) explains the ones you will set. Outside `APP_ENV=development` the API refuses to start with placeholder secrets.

## Layout

```
app/main.py            the app, middleware, /health /ready /metrics
app/config.py          settings, and the checks that refuse an insecure deployment
app/auth/              password hashing, tokens, the role dependencies
app/security/          crypto (secrets at rest), urls (what the server may call), hubspot (request signatures)
app/api/v1/            one module per area of the API
app/services/          scoring engines, webhook delivery, CRM sync, AI intelligence
app/models/            SQLAlchemy models        app/schemas/   request and response models
app/cli.py             the command-line tool
migrations/            Alembic revisions        tests/         pytest, and tests/mutation
```

Code that is shared with the Celery workers (models, services, settings) lives here; `workers/` imports it, and this package imports `workers.tasks` to queue work. Run `uvicorn` from the repository root, as the Docker image does, so both are importable.

## Endpoints

All under `/api/v1`, JSON, bearer token (`Authorization: Bearer <access token>`). **V** needs any signed-in user, **A** an analyst or admin, **Adm** an admin.

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/refresh` (public, rate-limited); `GET /auth/me` (V); `POST /auth/users` (Adm) |
| Contacts | `GET` (V), `POST` (A), `GET /{id}` (V), `PATCH /{id}` (A), `DELETE /{id}` (A) on `/contacts` |
| Companies | `GET` (V), `POST` (A), `GET /{id}` (V), `PATCH /{id}` (A) on `/companies` |
| Scoring | `GET /scoring/leads` (V, ranked, filter by tier, score, company), `POST /scoring/simulate` (V), `POST /scoring/runs` (A, 202), `GET /scoring/runs` and `/{id}` (V) |
| Ingest | `POST /ingest` (A, one event), `POST /ingest/batch` (A, up to 500) |
| Analytics | `POST /analytics/conversions` (A), `GET /analytics/conversions` (V), `GET /analytics/model-accuracy` (V), `GET /analytics/score-distribution` (V), `POST /analytics/conversions/hubspot` (HubSpot's signature) |
| Webhooks | `GET /webhooks`, `/{id}`, `/{id}/deliveries` (V); `POST`, `PATCH /{id}`, `DELETE /{id}`, `POST /{id}/test`, `POST /{id}/deliveries/{did}/retry` (A) |
| Models | `GET /models`, `/{id}`, `/champion/features` (V); `POST /{id}/promote`, `/{id}/shadow` (Adm) |
| Integrations | `GET /integrations`, `/{id}`, `/{id}/status` (V); `POST /{id}/sync-inbound`, `/sync-outbound` (A); `POST`, `PATCH`, `DELETE`, and the Salesforce `oauth/authorize` and `oauth/callback` (Adm) |
| AI | `GET /contacts/{id}/intelligence` (V, server-sent events), `GET /contacts/{id}/intelligence/sync` (V), `POST /leads/search` (V, plain English to a filter) |
| System | `GET /system/config` (V: the settings that are safe to show, and whether each secret is set) |
| Operations (no prefix) | `GET /health`, `GET /ready` (database), `GET /metrics` (Adm) |

Lists are paginated: `?page=1&page_size=50`, answered as `{ items, total, page, page_size, pages }`. Errors are `{ "detail": "..." }` (a 422 lists the fields and what was wrong, never what was sent).

## Webhooks out

Subscribe in the interface (Settings, Webhooks) or with `POST /webhooks`:

```json
{ "name": "Slack bridge", "url": "https://hooks.example.com/revops", "events": "tier_crossed,hot_lead", "tier_filter": "HOT,WARM" }
```

The response carries the signing `secret` once; it is never shown again. The target must be a public `https` URL (chapter 2 of the guide says why).

| Event | Fires when |
|---|---|
| `tier_crossed` | a live re-score puts a contact in a different tier |
| `hot_lead` | a live re-score moves a contact into the HOT tier from another |
| `score_updated` | a live re-score changes the score |
| `demo_requested` | a live re-score finds a demo request that the contact's previous score did not have |
| `conversion` | a deal-won conversion is recorded (by an analyst or by HubSpot's webhook) |

The score events describe a **change**, so a contact's first score is a baseline and fires none of them: otherwise the first scoring pass would announce every HOT lead and every demo request already in the database. `tier_filter` keeps only events whose lead is in one of the listed tiers (for `conversion`, the tier the lead had when it converted). Shadow scores never fire events, and are never what a live score is compared with. The scheduled scoring and `make score` both fire them, after the score is saved and at most once: a worker that dies in between loses the event rather than repeating it.

Every delivery is a `POST` with `Content-Type: application/json` and these headers: `X-Webhook-Event`, `X-Delivery-ID`, and, when the webhook has a secret, `X-Revops-Signature: sha256=<hex>`, the HMAC-SHA256 of the **raw request body** under the secret.

```json
{
  "id": "0f6b1c1e-6f0e-4a4e-9a3e-1f0d5b7c9a21",
  "event": "tier_crossed",
  "contact_id": "6d1e8c1a-...",
  "timestamp": "2026-11-11T09:30:00+00:00",
  "data": {
    "contact_email": "alice@acme.com",
    "lead_score": 88,
    "previous_score": 61,
    "priority_tier": "HOT",
    "previous_tier": "WARM",
    "score_reason": "demo_requested (+20), api_calls_7d (+30)",
    "recommended_action": "immediate_outreach",
    "model_version": "1.0.0"
  }
}
```

Verifying it, in Python:

```python
import hashlib
import hmac


def is_genuine(secret: str, raw_body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
```

Deliveries that fail (a non-2xx answer, a timeout, a target that no longer resolves to a public address) are retried after 30 seconds, 5 minutes and 30 minutes, four attempts in all, and then marked failed; `GET /webhooks/{id}/deliveries` shows each attempt, and a failed one can be retried by hand. Redirects are not followed.

## The CLI

`python -m app.cli` (or `make` targets), run where the database is reachable:

| Command | Does |
|---|---|
| `ingest --source-dir data/raw/` | load raw event files (`make ingest`) |
| `build-views` | rebuild the feature rows (`make build-views`) |
| `score-leads [--shadow]` | a scoring pass (`make score`); `--shadow` stores scores without making them live |
| `export-daily-list --top-n 50 --out ...` | the best leads as CSV; cells that start like a formula are neutralised (`make export`) |
| `sync-hubspot --csv ...` | push an exported list to HubSpot (`make sync-hubspot`) |
| `seed --count 100` | synthetic contacts, and the admin user if there is none (`make seed`) |
| `set-password --email ...` | set a user's password; asks for it, twice, without echoing (`make set-password EMAIL=...`) |

Training the machine-learning model: `uv run --package revops-workers python -m workers.training.train_model [--min-rows 200] [--promote]`. It trains on every contact, the ones with a recorded conversion being the positive examples (and refuses to run on fewer than `--min-rows` rows), writes `v<version>.json` under `ML_MODELS_DIR`, and registers the model in the shadow stage, or as champion with `--promote`. Otherwise promote it with `POST /models/{id}/promote` once its accuracy is trusted.

## Tests

`make test-api` (a PostgreSQL is needed; a throwaway one is started if `TEST_DATABASE_URL` is unset). `tests/mutation/` holds the mutation check for the authentication, encryption, URL, signature and settings code (`make mutation-api`). See [chapter 4](../../docs/guide/04-testing.md).

## Docker

```bash
docker build -f apps/api/Dockerfile --target production -t revops-api .   # from the repository root
```

Multi-stage, non-root, with a health check on `/health`. The worker image is `workers/Dockerfile`.

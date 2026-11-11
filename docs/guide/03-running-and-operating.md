# 3. Running and operating it

## Start it with Docker

```bash
cp .env.example .env          # then set the values below
make up                       # postgres, redis, api, worker, beat, web
make migrate                  # create the schema
make seed                     # 100 synthetic contacts, and the admin user from ADMIN_EMAIL / ADMIN_PASSWORD
make score                    # a scoring pass
```

Open <http://localhost:3000> and sign in with the admin user. The API is on <http://localhost:8000> (interactive docs at `/docs`; they are switched off when `APP_ENV=production`), Celery's monitor with `docker compose --profile monitoring up flower` on <http://localhost:5555>. Everything is bound to `127.0.0.1`.

## Start it without Docker

You need Python 3.12 or newer (3.14 is pinned in `.python-version`), [uv](https://docs.astral.sh/uv/), Node 24 or newer (`apps/web/.nvmrc` says 26), PostgreSQL and Redis.

```bash
make install                  # uv sync for the API and workers, npm ci for the web app
export DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/revops   # and the rest of the settings
make migrate
make api-dev                  # uvicorn with reload, on :8000
make worker-dev               # celery worker
make web-dev                  # next dev, on :3000 (API_INTERNAL_URL defaults to http://localhost:8000)
```

## Configuration

All settings are environment variables, read by `apps/api/app/config.py` (and listed with their defaults there); a `.env` file is read too. The ones you will set:

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `staging` and `production` switch on the startup checks below |
| `JWT_SECRET_KEY`, `APP_SECRET_KEY` | placeholders | **required in production, at least 32 characters.** `APP_SECRET_KEY` encrypts the CRM tokens in the database |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | placeholders | the user `seed` creates; the password may not be the placeholder in production |
| `DATABASE_URL` | local PostgreSQL | |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | local Redis | `RATE_LIMIT_STORAGE_URI` overrides where the limits are counted (`memory://` for one process) |
| `CORS_ORIGINS` | `http://localhost:3000` | comma-separated; `*` is refused outside development. The browser app does not need it (it uses `/bff`); other browser clients do |
| `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_PORTAL_ID` | empty | to sync with HubSpot |
| `HUBSPOT_WEBHOOK_SECRET` | empty | the HubSpot app's client secret; **the deal-won webhook is refused without it** |
| `PUBLIC_API_URL` | empty | the public base URL HubSpot calls, e.g. `https://example.com`. Needed behind a proxy so the signature can be checked |
| `SALESFORCE_CLIENT_ID`, `_SECRET`, `_REDIRECT_URI` | empty | to connect Salesforce; `SALESFORCE_ALLOWED_DOMAINS` limits where the token is sent |
| `ANTHROPIC_API_KEY`, `AI_MODEL` | empty, `claude-sonnet-5-5` | the AI reports; without the key those endpoints answer 503 and nothing else is affected |
| `BCRYPT_ROUNDS`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | 12, 60, 7 | |
| `RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_LOGIN_PER_MINUTE` | 100, 10 | per client address |
| `WEBHOOK_ALLOW_PRIVATE_TARGETS` | `false` | development only (see chapter 2) |
| `SCORING_HOT_THRESHOLD`, `_WARM_`, `_COOL_` | 75, 50, 25 | tier boundaries |
| `ML_MODELS_DIR` | `data/models` | where trained model files are written and read |

The web server reads two more: `API_INTERNAL_URL` (where it reaches the API; `http://api:8000` in compose) and `COOKIE_SECURE=false` (only for a deployment served over plain http).

**Startup checks.** Outside development the API refuses to start, and says why, if a secret is still the placeholder or shorter than 32 characters, or `CORS_ORIGINS` is `*`. Fix the message and start again.

## Deploy

`docker-compose.prod.yml` is the production layout: PostgreSQL and Redis on an internal network (Redis with a password and an append-only file), a one-shot `migrate` service that runs `alembic upgrade head` before the API and worker start, the API and worker (the only containers that can reach the internet, for the CRMs and the AI), beat, the web app, and nginx as the only published service.

```bash
# certificates: infra/nginx/certs/fullchain.pem and privkey.pem
IMAGE_TAG=2026-11-11 docker compose -f docker-compose.prod.yml build
IMAGE_TAG=2026-11-11 docker compose -f docker-compose.prod.yml up -d
```

Set `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `REDIS_PASSWORD` and the secrets above in the environment (`.env`). The nginx here is the edge: it overwrites `X-Forwarded-For` with the address that connected. If you put a CDN or load balancer in front of it, configure nginx's `real_ip_header` and `set_real_ip_from` first, or every client will look like the load balancer.

## Day-to-day

| To | Run |
|---|---|
| Watch logs | `make logs`, `make logs-api`, `make logs-worker` |
| Add a migration | `make migrate-new MSG="add foo table"` (then check it: `tests/test_schema.py` fails if the models and migrations disagree) |
| Roll the last migration back | `make migrate-down` |
| Load a CSV of events | `make ingest` (reads `data/raw/`) |
| Rebuild features, then score | `make build-views`, `make score` |
| Export the best 50 leads | `make export` |
| Push them to HubSpot | `make sync-hubspot` |
| Set a user's password | `make set-password EMAIL=...` |

Health: `GET /health` (the process is up), `GET /ready` (the database answers; 503 if not), `GET /metrics` (admin only, process counters).

## Rotating secrets

* **`JWT_SECRET_KEY`**: sign-ins end for everyone, who then sign in again. Nothing else is affected.
* **`APP_SECRET_KEY`**: stored CRM tokens become unreadable. Reconnect HubSpot and Salesforce afterwards. Do it deliberately, not by accident.
* **`HUBSPOT_WEBHOOK_SECRET`**: change it in HubSpot's app settings and here at the same time.
* **A webhook's signing secret** is shown once at creation; to rotate it, delete and recreate the webhook.
* **A user's password**: `make set-password EMAIL=someone@example.com` asks for a new one (twice, hidden) and sets it. There is no password-change endpoint yet. `ADMIN_PASSWORD` is used only by `seed`, and only when the admin does not exist yet, so changing it later changes nothing.

## When something is wrong

| Symptom | Look at |
|---|---|
| The API will not start, naming a setting | the startup checks above |
| Every scoring run says 0 contacts | features have not been built: `make build-views` |
| HubSpot's webhook gets 401 or 503 | `HUBSPOT_WEBHOOK_SECRET` is unset (503) or the signature does not match: is `PUBLIC_API_URL` the exact public URL (401)? |
| A webhook never delivers | its delivery log (`GET /webhooks/{id}/deliveries`): the target may resolve to a non-public address, which is refused |
| Reports say "not configured" | `ANTHROPIC_API_KEY` |
| After rotating `APP_SECRET_KEY`, syncs fail with "cannot be decrypted" | reconnect the integration |
| Sign-in works but every page sends you back to it | the browser is dropping the `Secure` cookie: the site is on plain http (`COOKIE_SECURE=false`) or TLS is not terminating in front of the web app |
| Users get 429s | nginx's per-address limits (chapter 2); behind a load balancer see the note under Deploy |

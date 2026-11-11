# RevOps Lead Scoring Platform

Scores B2B leads from product-usage and engagement signals, ranks them HOT, WARM, COOL or COLD, and tells sales which to call first. It ingests events, builds features, scores every contact on a schedule, pushes the best leads to HubSpot or Salesforce, tells other systems when a lead changes tier, and explains each lead in plain English with Claude.

* **Scoring.** A transparent formula is always live; an XGBoost model scores in *shadow* alongside it and is promoted only when its accuracy is trusted. The Simulate page shows why a set of signals scores as it does.
* **Interface.** Dashboard, ranked leads (filter, export, per-lead AI report), companies, analytics (precision per tier, score distribution, conversions), CRM integrations, run history, settings.
* **Integrations.** HubSpot (batch sync out, signed deal-won webhook in), Salesforce (OAuth), outbound webhooks with signatures and retries, S3-compatible raw imports.
* **Built to run in production.** Refuses to start with placeholder secrets, encrypts stored CRM tokens, keeps tokens out of the browser, checks every URL it calls on a user's behalf. See [the security model](docs/guide/02-security-model.md).

## Quick start

```bash
cp .env.example .env     # set JWT_SECRET_KEY, APP_SECRET_KEY, ADMIN_PASSWORD (any values are fine for a local try-out)
make up                  # PostgreSQL, Redis, API, worker, scheduler, web app
make migrate seed score  # schema, 100 synthetic contacts and an admin user, a first scoring pass
```

Open <http://localhost:3000> and sign in as the admin (`ADMIN_EMAIL` / `ADMIN_PASSWORD`). The API and its interactive docs are on <http://localhost:8000/docs>.

Without Docker, or for production, see [Running and operating it](docs/guide/03-running-and-operating.md).

## Documentation

| | |
|---|---|
| [docs/](docs/README.md) | the guide, in four chapters: architecture, security model, running it, testing |
| [apps/api/README.md](apps/api/README.md) | the API: endpoints, the CLI, the webhook format |
| [apps/web/README.md](apps/web/README.md) | the web app |
| [VERSIONS.md](VERSIONS.md) | what it runs on, and why |
| [work-done.md](work-done.md) | what the modernisation found and changed, and what was not verified |

## Repository

```
apps/api/      FastAPI service, Alembic migrations, tests
apps/web/      Next.js 16 app, tests
workers/       Celery tasks, CRM connectors, model training
infra/nginx/   production reverse proxy
docs/          the guide
```

One `uv` workspace holds the API and the workers (one `uv.lock`); the web app has its own `package-lock.json`.

## Everyday commands

| | |
|---|---|
| `make up` / `down` / `logs` | the stack |
| `make migrate` / `seed` / `score` | schema, demo data, a scoring pass |
| `make install` | dependencies for local development (Python 3.12 or newer, Node 24 or newer) |
| `make api-dev` / `worker-dev` / `web-dev` | each service locally, with reload |
| `make check` | lint, format, types and every test (what CI runs) |
| `make mutation` | the mutation check of the security-critical code (slow) |
| `make help` | all of them |

## Status

The API and web test suites and the mutation check pass (see [chapter 4](docs/guide/04-testing.md) for the numbers). Nothing here has been run against a live HubSpot, Salesforce or Anthropic account, or load-tested; [work-done.md](work-done.md) lists exactly what was and was not verified.

## License

No licence file is included in this repository. Add one before distributing it.

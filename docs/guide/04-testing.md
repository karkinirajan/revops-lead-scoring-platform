# 4. Tests and the mutation check

```bash
make check             # lint, format, types, then every test (what CI runs)
make test-api          # API and workers: pytest
make test-web          # web: Vitest
make lint              # ruff, mypy, eslint, tsc
make mutation          # the mutation check, API then web (slow: one test run per mutant)
```

As of the modernisation: **810 API and worker tests** (on Python 3.12.16 and 3.14.9) and **473 web tests**, all passing.

## API and workers

`pytest apps/api/tests`. The suite runs against **a real PostgreSQL**, not SQLite: the schema comes from the Alembic migrations, and each test runs in a transaction that is rolled back (a savepoint per test, so code that commits is still isolated). If `TEST_DATABASE_URL` is not set, `conftest.py` starts a throwaway cluster with the PostgreSQL binaries it finds (`initdb` and `pg_ctl` on your `PATH`, or under `/usr/lib/postgresql/*/bin`), and stops it afterwards. **If it finds none, the tests that need a database are skipped, not failed**, and pytest prints the skip count: a run that reports a few hundred skips has not tested the application. Install PostgreSQL, or point `TEST_DATABASE_URL` at one (CI does).

Things the harness does for you, so a test cannot quietly depend on the outside world:

* **No outbound network.** Any attempt to connect to a non-local address fails the test, so a code path that would call HubSpot, Salesforce or Anthropic has to be given a fake.
* **DNS is faked on demand.** The `public_dns` fixture makes names resolve to a public address, so the SSRF checks can be exercised without a network.
* **Rate limits** count in memory (`memory://`), and the AI limit is raised for tests that are not about it; one test checks that it is enforced.
* **Celery tasks** run directly against the test session (`worker_db`).

| Area | Files |
|---|---|
| Authentication, roles, rate limits | `test_auth.py`, `test_routes.py` |
| Data routes: contacts, companies, scoring, analytics, models | `test_routes.py`, `test_conversions.py` |
| Scoring: the formula, the ML engine, model files | `test_scoring_engine.py`, `test_ml_scoring_engine.py`, `test_ml_artifacts.py`, `test_pipeline.py` |
| Webhooks, in and out | `test_webhooks.py`, `test_webhooks_api.py`, `test_webhook_dispatch.py`, `test_hubspot_signature.py`, `test_hubspot_webhook_api.py` |
| Integrations and connectors | `test_integrations_api.py`, `test_salesforce_connector.py` |
| Security primitives | `test_crypto.py`, `test_security_urls.py` |
| AI | `test_ai_intelligence.py`, `test_intelligence_api.py` |
| Workers, schedule, CLI, schema | `test_workers.py`, `test_cli.py`, `test_schema.py`, `test_health.py`, `test_ingest_api.py`, `test_system_config.py` |

## Web

`cd apps/web && npm test`. Vitest with Testing Library in jsdom.

* The **route handlers** (`/session/login`, `/session/logout`, `/bff/...`) and **`proxy.ts`** are called directly as functions with real `Request` objects, and `fetch` replaced by a fake. `routeFetch` in `test/helpers.ts` answers by URL and fails the test on a request it was not given.
* **Components** are rendered and driven through what a user sees: roles, labels and text, not class names. jsdom has no layout engine and loads no stylesheet, so how things *look* is not tested here (see below).
* `server-only` is stubbed so server modules can be imported.

## What the tests cannot see, and what was done instead

Layout, colour and keyboard behaviour were checked **by hand against a production build** (`next build` and `next start`, the API on a throwaway database with seeded data), with a real browser. That is a record of one pass, not an automated check:

* all eight pages, signed out and signed in, the sign-in error and empty-submit states;
* **contrast**: every text node on all eight pages measured against WCAG AA (4.5:1); this found and fixed the secondary text colour (2.2:1), the primary button (4.47:1), the tier badges (3.0 to 3.9:1) and the error text (3.95:1);
* **responsive**: 1280, 768 and 390 pixels wide; the first pass found that the fixed side navigation left 166 pixels for content on a phone, which became the menu button;
* **keyboard**: every tab stop on three pages shows a focus indicator; this found that an unchecked switch lost its focus ring;
* **page weight against the rate limit**: a full load of the dashboard was measured at 27 requests, which set the nginx limits (chapter 2).

If you change the interface, repeat them: `apps/web/test/browser/audit.js` is the contrast, overflow and focus-indicator check as one script to paste into the browser's console (instructions at the top of the file).

## The mutation check

Passing tests do not show the tests would catch a bug. The mutation check does: `tests/mutation/mutants.py` (API) and `test/mutation/mutants.py` (web) list deliberate bugs, each as a line, the exact text to replace and what to replace it with: flip a comparison, drop a check, swap a constant. For each one the driver, `mutate.py`, applies it alone, runs the whole suite, and the mutant **counts as killed only if the suite fails**. It first checks the suite passes unmutated (otherwise everything would look killed), requires each pattern to occur exactly once, and restores every file afterwards.

```bash
python3 apps/api/tests/mutation/mutate.py apps/api/tests/mutation/mutants.py -- \
    uv run --package revops-api pytest apps/api/tests -x -q -p no:cacheprovider
cd apps/web && python3 test/mutation/mutate.py test/mutation/mutants.py -- npx vitest run --bail 1
# a name filter limits the run: ... mutants.py jwt hubspot -- <test command>
```

Do not edit the repository while it runs: it rewrites the files it mutates, in place.

**Results.** API: **239 of 239 killed** in one run. Web: **289 of 289 killed** in one run (about 15 minutes).

**What it found.** The first full runs left 28 survivors in the API list and 12 in the web list. Almost all were tests that were too loose, for example a settings test that set all four secrets at once (so two flags swapped by mistake still matched), a "null stays null" test that checked the raw column and never read it back through the ORM, an error-message match that bcrypt's own message also satisfied, and a response-header check that passed vacuously on an empty list. Each got a test that fails without the line it guards.

Survivors also turned out to be worth *distrusting as redundant code*. Twice a survivor looked like a line that could be deleted and was not: an empty `sub` in a signed token reached the database as a malformed UUID and answered 500, and a `.lower()` that looked needed was already done by `urlsplit`. The first became a rule (the subject must be a UUID, on the access and the refresh path); the second was removed. A few survivors are true equivalents, for example the explicit `//` check in `safeNext` next to the origin comparison that also refuses it; those are kept as deliberate layers and each is listed with its reason in the header of the mutant list.

What it covers: passwords and tokens, the role checks and the sign-in and refresh routes, the HubSpot signature (the window, every signed part, every decoded escape), encryption at rest, the URL checks (scheme, credentials, resolution, mapped IPv6, Salesforce domains), the startup checks, the configuration endpoint; on the web side the session cookies, the same-origin check, the proxy's allow-list and refresh logic, the page guard, the sign-in route, the CSV export, the filters and the chart arithmetic.

Not covered: the rest of the API's routes and services are covered by tests but have no mutants; the mutants are written for code where a wrong comparison or a dropped check is a security or data-integrity bug.

When a mutant **survives**, one of three things is true: the test is too weak (add a test; most of the survivors found while writing this list were that), the code is redundant (delete it; several lines were removed this way), or the mutant is a true equivalent, which is listed with the reason in the header of `mutants.py`.

## CI

`.github/workflows/ci.yml`: Python 3.12 and 3.14 (lint, format, mypy, the suite with coverage against a PostgreSQL 18 service, and a dependency audit on 3.14); Node 24 and 26 (lint, type-check, tests, production build, and `npm audit` for production dependencies); then the three production images are built (not pushed). The mutation check is not in CI: it takes tens of minutes. Run it before changing the code it covers.

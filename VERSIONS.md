# Versions

What this project runs on, and why, as of 2026-11-11. The numbers below come from `uv.lock`, `apps/web/package-lock.json`, `uv tree --outdated`, `npm outdated`, the compose files and Dockerfiles, and endoflife.date (fetched that day); none is quoted from memory.

## Runtime

| | Version | Notes |
|---|---|---|
| Python | **3.14** (`.python-version`); `requires-python >=3.12` | 3.12 is the floor because the code uses PEP 695 generics. 3.14: latest 3.14.10 (3.14.9 installed here), bug fixes to 2027-10-01, security fixes to 2030-10-31. 3.12: latest 3.12.16, security fixes only, end of life 2028-10-31. The API suite passes on **3.12.16 and 3.14.9**; 3.13 was not run. CI runs 3.12 and 3.14. |
| Node | **26** (`apps/web/.nvmrc`); `engines >=24` | 26 became LTS on 2026-10-28 (latest 26.13.0, active support to 2027-10-27, end of life 2029-04-30). 24 is in maintenance (since 2026-10-20, end of life 2028-04-30). CI runs 24 and 26. |
| uv | 0.13.7 | Pinned in CI; installs and locks the Python side. |
| PostgreSQL | **18** (`postgres:18-alpine`) | Latest 18.6, end of life 2030-11-14. The tests need a PostgreSQL; they do not use SQLite. |
| Redis | **8** (`redis:8-alpine`) | The newest series is 8.10 (8.10.3 on 2026-07-29); no end of life is announced for it. Broker, rate-limit counters, AI report cache. |
| nginx | **1.30** (`nginx:1.30-alpine`) | Latest 1.30.6. |
| Flower | `mher/flower:2.2` | Optional monitoring (`--profile monitoring`). **Not checked against upstream's latest release.** |
| Base images | `python:3.14-slim`, `node:26-alpine` | |
| GitHub Actions | checkout v7, setup-node v7, setup-uv v10, docker/setup-buildx-action v4, docker/build-push-action v7 | Checked against each action's latest release page; the workflow has not run on this branch. |

## API and workers (`pyproject.toml`, locked in `uv.lock`)

The `pyproject.toml` files list dependencies without version bounds and `uv.lock` pins them: one lock for the API and the workers (a `uv` workspace). `uv lock --upgrade` leaves every direct dependency at its latest release (`uv tree --outdated` lists none). `python-jose`, `passlib` and the old per-package requirements files are gone.

| Package | Locked | Notes |
|---|---|---|
| fastapi | 0.162.4 | with starlette 1.10.0 and uvicorn 0.54.0 |
| sqlalchemy | 2.1.8 | 2.1; the models use the 2.0 typed `Mapped` style |
| alembic | 1.20.1 |  |
| psycopg2-binary | 2.9.13 |  |
| pydantic | 2.14.3 | v2; `pydantic[email]` for `EmailStr` |
| pydantic-settings | 2.16.2 |  |
| pyjwt | 2.15.1 | replaces `python-jose` (which went from June 2021 to February 2025 without a release) |
| bcrypt | 5.0.0 | used directly; replaces `passlib`, whose last release (1.7.4) is from October 2020 |
| cryptography | 50.0.2 | Fernet, for secrets stored in the database |
| slowapi | 0.1.10 | rate limiting |
| redis | 8.1.0 |  |
| celery | 5.7.0 |  |
| httpx | 0.28.1 | outbound calls; the tests replace it |
| structlog | 26.1.0 |  |
| typer | 0.29.1 | the CLI |
| rich | 15.0.0 |  |
| anthropic | 2.8.0 | AI reports |
| boto3 | 1.44.0 | S3-compatible raw imports (workers) |
| xgboost | 3.4.1 | the v2 model; models are stored as JSON, never pickled |
| scikit-learn | 1.9.1 | training metrics |
| numpy | 2.5.4 |  |

Development (`[dependency-groups] dev`):

| Package | Locked | Notes |
|---|---|---|
| pytest | 9.2.0 |  |
| pytest-cov | 7.1.0 |  |
| ruff | 0.17.4 | lint and format, `E4 E7 E9 F B I UP`, Python 3.12 target |
| mypy | 2.4.1 | with the pydantic plugin; run over `apps/api/app` and `workers` |
| faker | 40.54.0 | `seed` only |

## Web (`apps/web/package.json`, locked in `package-lock.json`)

| Package | Locked | Notes |
|---|---|---|
| next | 16.4.6 | App Router, Turbopack, `proxy.ts`; was 15.1.0 |
| react | 19.3.1 | was ^19.0.0 |
| react-dom | 19.3.1 |  |
| tailwindcss | 4.3.5 | 4; was ^3.4.17, with a `tailwind.config.ts` |
| @tailwindcss/postcss | 4.3.5 |  |
| typescript | 6.0.3 | **held on 6.0**; see below |
| eslint | 10.14.0 | flat config with `eslint-config-next` |
| eslint-config-next | 16.4.6 |  |
| vitest | 5.1.0 | with `@vitest/coverage-v8` |
| jsdom | 31.0.0 |  |
| @testing-library/react | 16.3.3 |  |
| @testing-library/user-event | 14.6.9 |  |
| @testing-library/jest-dom | 7.0.1 |  |
| date-fns | 4.4.0 |  |
| clsx | 2.1.1 |  |
| server-only | 0.0.1 | keeps server modules out of the browser bundle |

`@tanstack/react-table`, `@tanstack/react-virtual` and `swr` were removed: nothing imported them.

**TypeScript is held on 6.0.** `npm outdated` reports 7.0.2 as the latest; it was **not tried** in this project, so nothing here says whether the rest of the toolchain (Next 16, `eslint-config-next`, Vitest) is ready for it. Revisit it as its own change.

## Checks run

* `uv lock --upgrade` and `npm outdated`: every direct dependency is at its latest release, except TypeScript (above).
* `uv audit --preview-features audit-command`: no known vulnerabilities and no adverse project statuses in 99 packages. `npm audit --omit=dev`: 0 vulnerabilities.
* The API suite on Python 3.12.16 and 3.14.9; the web suite and production build on Node 26.13.0; the three production images build from the repository root.
* On Python 3.14 pytest reports 5 `DeprecationWarning`s from inside `slowapi` (`asyncio.iscoroutinefunction`, removal slated for Python 3.16); they are not from this repository's code.

# RevOps web app

The interface for the lead scoring platform: Next.js 16 (App Router, Turbopack), React 19, TypeScript, Tailwind CSS 4. It talks to the API **only from its own server**: the browser never sees a token or the API's address.

## Run it

```bash
npm ci
API_INTERNAL_URL=http://localhost:8000 npm run dev      # http://localhost:3000 (the API's default address is used if the variable is unset)
```

Sign in with a user the API knows (`make seed` creates the admin from `ADMIN_EMAIL` / `ADMIN_PASSWORD`).

| Variable | Used for |
|---|---|
| `API_INTERNAL_URL` | where this server reaches the API (`http://api:8000` in compose). Never sent to the browser |
| `COOKIE_SECURE` | set to `false` only when the site is served over plain http; the session cookies are `Secure` in production otherwise |

## Scripts

| | |
|---|---|
| `npm run dev` / `build` / `start` | development server, production build, production server |
| `npm run check` | `tsc --noEmit`, ESLint with no warnings allowed, and the tests |
| `npm run ci` | `check`, the production build, and `npm audit --omit=dev` |
| `npm test` / `test:watch` / `test:coverage` | Vitest |

Node 24 or newer (`.nvmrc` says 26).

## How it is laid out

```
proxy.ts                    guards every page; renews an expiring access token before the page renders
app/login/                  the sign-in page
app/session/login|logout/   route handlers that set and delete the session cookies
app/bff/[...path]/          the proxy to the API: the only way the browser reaches it
app/(app)/                  the signed-in pages: dashboard, leads, companies, analytics, integrations, runs, simulate, settings
components/                 layout (AppShell, Sidebar), leads, companies, simulate, dashboard, ui
lib/auth/                   tokens, cookies, the same-origin check, the proxy's allow-list, refresh
lib/server/                 the API client for server components, session helpers
lib/api.ts                  the API client for the browser (through /bff)
lib/                        csv, leads filters, chart arithmetic, formatting, SSE parsing, shared types
test/                       Vitest tests, a mutation check (test/mutation), a browser audit script (test/browser)
```

## How sign-in works

1. `POST /session/login` sends the credentials to the API and puts the two tokens in **httpOnly, SameSite=Lax cookies**. The page's JavaScript only ever gets `{ ok: true }`.
2. Server components call the API with the access token from the cookie (`lib/server/api.ts`); client components call `/bff/...` (`lib/api.ts`), which adds the token. An expired session sends the user to `/login?next=...`.
3. `proxy.ts` and `/bff` refresh the access token from the refresh cookie when it is about to expire.
4. Every request that changes something must carry an `Origin` naming this site. `/bff` forwards only an allow-list of API paths: sign-in, refresh, user creation and the webhook receivers are not reachable through it.

The reasoning and what it does not cover are in [`docs/guide/02-security-model.md`](../../docs/guide/02-security-model.md).

## Styling

Tailwind 4 with the design tokens in `app/globals.css` (`@theme` for utilities, `:root` for the CSS variables the components use). Text and accent colours were chosen to meet WCAG AA contrast (4.5:1) on every surface; `--primary-strong` is for buttons under white text and `--primary-fg` for indigo text on the dark surfaces.

## Tests

`npm test`: the route handlers and `proxy.ts` called directly with mocked `fetch`, components rendered with Testing Library, and the helpers. `test/mutation/` holds the mutation check for the session, proxy and helper code (`make mutation-web` from the repository root). `test/browser/audit.js` is a script for the browser console that checks contrast, overflow and focus indicators on a running build, which jsdom cannot do. See [`docs/guide/04-testing.md`](../../docs/guide/04-testing.md).

## Docker

Built from the repository root, like the other images:

```bash
docker build -f apps/web/Dockerfile --target production -t revops-web .
```

Multi-stage, runs as a non-root user, and serves the Next standalone output.

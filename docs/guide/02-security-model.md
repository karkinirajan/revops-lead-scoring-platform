# 2. The security model

What protects what, and what to do about the parts that depend on you. Each claim here is tested; chapter 4 says how, and `apps/api/tests/mutation/` and `apps/web/test/mutation/` hold the deliberate bugs that the tests were checked against.

## Signing in from a browser

* The browser never holds a token. `POST /session/login` checks the credentials with the API and keeps the access and refresh tokens in two **httpOnly, SameSite=Lax cookies** (`Secure` in production), so no script on the page, and so no XSS, can read them.
* The browser calls the API only through **`/bff/...`**, a route of the web app, same origin, which adds `Authorization: Bearer` from the cookie. There is no CORS to configure for it.
* `/bff` forwards only the parts of the API the interface uses (`lib/auth/paths.ts`: contacts, companies, scoring, analytics, webhooks, models, integrations, the current user, the system configuration). Sign-in, token refresh, user creation, ingestion and the HubSpot webhook receiver are **not reachable** from a browser through it, and path tricks (`..`, encoded slashes, empty segments) are refused.
* **CSRF.** SameSite=Lax keeps the cookies off cross-site POSTs; on top of that every request that changes something must carry an `Origin` that names this site (`lib/auth/origin.ts`). A request with no Origin is refused.
* **Refresh.** `proxy.ts` and `/bff` renew an access token that is about to expire from the refresh cookie, once, and retry a call once if the API says the token is bad. A refused refresh ends the session (both cookies deleted).
* **Sign-out** deletes the cookies. The API keeps no session, so it cannot revoke a token that was already issued: it stops being sent and expires (access: 60 minutes, refresh: 7 days, both settings).
* Error messages from sign-in are fixed texts; the API's own wording, stack traces and addresses never reach the page.

## The API's authentication

* **Passwords** are hashed with bcrypt (cost `BCRYPT_ROUNDS`, default 12). bcrypt reads only 72 bytes, so a longer password is refused rather than silently truncated. A login for an unknown email does the work of a password check anyway, so the answer takes as long as for a known one.
* **Tokens** are JWTs signed with `JWT_SECRET_KEY`. The algorithm is fixed on decode (never read from the token); `exp`, `iat`, `sub` and `type` are required; and a token must be the right kind: an access token is refused where a refresh token is expected and the reverse. Each token also carries `pwv`, a keyed tag (HMAC under the signing key) of the user's stored password hash: when the password changes the tag no longer matches, so **every session opened under the old password ends** at its next request, refresh included. A token without the tag is refused, so sessions open when this was first deployed ended then.
* **Roles.** `viewer` reads; `analyst` also writes contacts, companies and webhooks, ingests events, starts scoring runs and syncs; `admin` also creates users, manages CRM connections and the Salesforce authorisation, promotes models, and reads `/metrics`. Roles are read from the database on every request, not from the token, so deactivating or demoting a user takes effect immediately.
* **Rate limits.** Per client address (`RATE_LIMIT_PER_MINUTE`; sign-in and refresh `RATE_LIMIT_LOGIN_PER_MINUTE`, default 10; AI reports their own), stored in Redis. Because the limit is per address, the address has to be true: nginx sets `X-Forwarded-For` to the address that connected rather than appending to what a client sent, and the web app passes it on when it calls the API for a user. The web app reads the **last** entry of the header (the one the nearest proxy added, which a client cannot choose), so if the header were ever appended to it would fail closed, with users sharing a limit, rather than open; and the web app and the API must be reachable only through nginx.
* **A deployment that is not development refuses to start** with the placeholder secrets, with `JWT_SECRET_KEY` or `APP_SECRET_KEY` shorter than 32 characters, or with `CORS_ORIGINS=*`.

## Secrets stored in the database

CRM access and refresh tokens are **encrypted at rest** (Fernet, key derived from `APP_SECRET_KEY`) and stored as `enc:v1:...`. Values written before encryption existed are still read and are encrypted the next time they are saved. **Changing `APP_SECRET_KEY` makes the stored tokens unreadable**: reconnect the integrations after rotating it. The API never returns a secret: `/system/config` reports only whether each is set, and a webhook's signing secret is shown once, at creation.

## Calls the server makes to addresses a user supplies

Webhook targets and Salesforce instance URLs are URLs a user chooses and the server then calls, which would let that user reach whatever the server can reach (cloud metadata, the database, Redis). So a target must be `https`, without a user name or password, and its host must resolve **only to public addresses** (loopback, private, link-local, reserved and multicast are refused; an IPv4 address written as IPv6 is judged as IPv4; the IPv6 ranges that wrap an IPv4 address, NAT64, 6to4 and Teredo, are refused outright, since on a network with a translator the connection would end at the wrapped address). The check is repeated immediately before each delivery, and redirects are never followed. A Salesforce instance URL must also end in one of `SALESFORCE_ALLOWED_DOMAINS` (it receives the stored access token). The default is `.salesforce.com` only: the `force.com` domains (the Lightning interface, customer-built sites) are not API hosts, and anyone can publish a site there, so they are left out unless you add them yourself. `WEBHOOK_ALLOW_PRIVATE_TARGETS=true` lifts the address and `http` limits for development against a local receiver; never set it in production. One thing this does not defend against: a DNS answer that changes between the check and the connection.

## Webhooks in and out

* **HubSpot to us.** The deal-won webhook is accepted only with a valid **v3 signature**: HMAC-SHA256 over method, public URL, body and timestamp under `HUBSPOT_WEBHOOK_SECRET`, Base64, compared in constant time, and no more than five minutes old. Behind a proxy the URL HubSpot called is not the one the API sees, so set `PUBLIC_API_URL`. Without the secret the endpoint refuses everything.
* **Us to others.** Deliveries carry `X-Revops-Signature: sha256=<HMAC of the body>` under the webhook's own secret, so a receiver can check it.

## Untrusted content

* **AI.** Lead data from CRMs is placed between `<lead_data>` tags that the system prompt names as data, not instructions; the search prompt does the same for the user's query. A failure inside a stream reaches the browser as one generic message ("The AI service could not complete this request."); the only specific answer is "not configured", which says which setting is missing and nothing about its value.
* **CSV.** A lead's name or company can start with `=`, `+`, `-` or `@`, which a spreadsheet would run as a formula. The CSV export in the web app and the CLI prefix such values with an apostrophe.
* **Models** are JSON, never pickle: loading one cannot run code.

## The edge (nginx) and the containers

* TLS 1.2/1.3 only; port 80 redirects. Rate limits per address: the API 30 requests a minute, sign-in 10, pages and `/bff` 120 (the build's static files are exempt: a page load fetches about a dozen). Over the limit is a 429.
* The API container is reachable only through nginx; the database and Redis are on an internal network; only the API and the worker, which call the CRMs, are on the egress network.
* The images run as a non-root user (uid 1001).

## What is not covered

* **Revoking a session.** See sign-out above.
* **Brute force across many addresses.** Limits are per address.
* **A compromised `APP_SECRET_KEY`** decrypts the stored CRM tokens; rotate it and reconnect.
* **The web app's cookie `Secure` flag** assumes TLS terminates in front of it. Set `COOKIE_SECURE=false` only for a plain-http deployment.
* **Not penetration-tested.** The checks here are tests the author wrote, plus the mutation check; nobody attacked a running deployment.

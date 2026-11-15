# Security

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private vulnerability reporting
(**Security → Report a vulnerability** on this repository). Include steps to reproduce and the affected version.
You can expect an acknowledgement within a few days.

## Security model

### Authentication and sessions

- **Passwords** are hashed with **Argon2id** (`argon2-cffi`, RFC 9106 defaults) and re-hashed automatically when
  parameters change. Policy: 10–128 characters with at least three character classes.
- **Login protection:** identical errors for unknown e-mail and wrong password, constant-time work for unknown users,
  account lockout after 5 consecutive failures (15 minutes), rate limiting per e-mail and per client IP.
- **Client IP** for rate limiting is taken from the `X-Forwarded-For` entry appended by the trusted proxy
  (`TRUSTED_PROXY_HOPS`), never from the client-controlled left-most value.
- **Access tokens:** HS256 JWTs, 15-minute lifetime, kept only in browser memory. Each token carries the user's
  `token_version`; changing the password or signing out everywhere increments it, invalidating all outstanding tokens.
- **Refresh tokens:** 384-bit random values stored as SHA-256 hashes, delivered in an `httpOnly`, `Secure` (production),
  `SameSite=Strict` cookie restricted to `/api/v1/auth`. They rotate on every use. Re-using a rotated token outside a
  20-second grace window (concurrent tabs) is treated as theft and revokes every session of the user.

### Authorisation and data isolation

- Every management query filters by the authenticated user's ID; resources owned by other users return **404**.
- Gateway calls are authorised by **project API keys** and only ever use the credentials of the key's owner, and only
  for providers the project allows.
- The AI Analyst cannot run SQL or choose a user: it calls a fixed set of read-only, argument-validated functions and
  the user ID is injected by the server.
- Isolation is covered by automated tests (`tests/test_isolation.py`, `tests/test_analyst.py`).

### Secrets

- **Provider API keys** are encrypted with Fernet (AES-128-CBC + HMAC-SHA256). The Fernet key is derived with
  HKDF-SHA256 from `MASTER_ENCRYPTION_KEY`. Only a masked hint (`sk-p…9xQa`) is ever returned to the browser.
  Key rotation: set `MASTER_ENCRYPTION_KEY="new,old"`, run `python -m app.cli rotate-keys`, then remove the old key.
- **Project API keys** (`mk_…`, 256-bit random) are shown once and stored as SHA-256 hashes.
- Server secrets (`JWT_SECRET_KEY`, `MASTER_ENCRYPTION_KEY`, database URL, analyst key) come from environment variables.
  The app refuses to start without them; there are no insecure defaults. `.env` is git-ignored; `.env.example` holds
  placeholders only.

### Transport, browser and input protections

- HTTPS is terminated by the platform (Render); HSTS is sent in production.
- Security headers: `Content-Security-Policy` (scripts and connections from `self` only), `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`,
  `Cache-Control: no-store` on API responses.
- **CORS:** in production the UI is served from the same origin, so no cross-origin access is granted unless
  `CORS_ORIGINS` explicitly lists origins.
- **Input validation** with Pydantic on every endpoint; numeric bounds and length limits; request bodies are capped
  (`MAX_REQUEST_BYTES`, default 2 MB) including chunked uploads.
- **SQL injection:** all queries use SQLAlchemy expressions with bound parameters; search input is LIKE-escaped.
- **Rate limiting:** per IP for authentication, per user for the API and analyst, per project key for the gateway.
- **Errors** are sanitised: clients receive a code, a message and a request ID — never stack traces or submitted
  values. Unhandled exceptions are logged server-side with the request ID.

### Privacy-conscious logging policy

1. Request and response **bodies are never logged or stored** — this includes prompts, completions, images and tool
   payloads. The database stores metadata only: provider, model, endpoint, status, token counts, latency, cost
   estimate and a truncated, redacted error message.
2. **Headers are never logged.** Uvicorn access logs are reduced to warnings so URLs with query strings are not written.
3. A logging filter **redacts** anything resembling an API key, project key, bearer token or JWT before output, as a
   second line of defence.
4. Every log line carries the request ID for tracing; users can quote it to support without sharing content.
5. Provider error messages stored in request logs are passed through the same redaction and truncated to 500 characters.

### Operational notes and known limitations

- The rate limiter is in-process. With several instances or workers each one enforces its own window; use a shared
  store (e.g. Redis) before scaling horizontally. The Docker entrypoint runs a single worker by default.
- Losing `MASTER_ENCRYPTION_KEY` makes stored provider keys unreadable (users must re-enter them). Back it up.
- The Render free PostgreSQL plan is reachable only from Render services (`ipAllowList: []`).
- Alerts are delivered in-app only; no e-mail or webhook integration is configured.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | ✅ |

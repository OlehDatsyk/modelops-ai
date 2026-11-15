# ModelOps AI — Project review

Version **1.0.0** · reviewed 2026-11-15

## 1. Completed features

| Requirement | Status | Implementation |
| --- | --- | --- |
| Registration, login, logout, JWT + refresh tokens | ✅ | `api/routes/auth.py`, rotating httpOnly refresh cookie with reuse detection and grace window |
| Protected routes (backend + frontend) | ✅ | `get_current_user` dependency on every management route; `RequireAuth` in the SPA |
| Profile, password change, account deletion, sessions, lockout | ✅ | `/auth/me`, `/auth/change-password`, `/auth/sessions`, `/auth/logout-all`, `DELETE /auth/me` |
| OpenAI, Anthropic, Gemini adapters | ✅ | `providers/*.py`: auth headers, request building, usage extraction, stream parsers, key validation + model discovery |
| Encrypted credential storage, masked display | ✅ | `core/crypto.py` (Fernet + HKDF, rotation via MultiFernet) |
| Gateway (non-streaming and streaming) | ✅ | `services/gateway.py`, `api/routes/gateway.py`; SDK-compatible paths |
| Timeouts, rate limits, invalid credentials, provider errors, malformed requests | ✅ | Mapped to 504/429/401/4xx–5xx; all recorded as failed requests |
| Request IDs | ✅ | `RequestContextMiddleware`, `x-modelops-request-id` |
| Dashboard metrics, charts, date ranges incl. custom | ✅ | `services/analytics.py`, `pages/Dashboard.tsx` |
| Pricing module with snapshots, overrides, unknown handling | ✅ | `models/pricing.py`, `services/pricing.py`, pricing columns on `api_requests` |
| Spend by provider/model/project, trends, daily/monthly summaries | ✅ | `/analytics/costs`, `usage_daily` roll-up, `pages/Costs.tsx` |
| Projects with provider config, hashed keys, revocation, stats | ✅ | `api/routes/projects.py`, `pages/Projects.tsx`, `pages/ProjectDetail.tsx` |
| Request logs: search, pagination, sorting, filtering, details | ✅ | `api/routes/requests.py`, `pages/Requests.tsx` |
| AI Analyst with controlled tool layer | ✅ | `services/analyst_tools.py`, `services/analyst.py` (OpenAI & Anthropic tool calling) |
| Budgets, thresholds, alerts, notifications, history | ✅ | `services/alerts.py`, `api/routes/alerts.py`, `pages/Alerts.tsx` |
| In-app notification system | ✅ | Bell menu + history; no external delivery claimed |
| PostgreSQL schema, migrations, FKs, indexes, transactions | ✅ | 13 tables, `alembic/versions/0001_initial_schema.py` |
| Security hardening | ✅ | See SECURITY.md |
| Docker, Compose, Render, GitHub Actions | ✅ | `Dockerfile`, `docker-compose.yml`, `render.yaml`, `.github/workflows/ci.yml` |
| Startup scripts | ✅ | `Start App.bat`, `Start App (Mac).command` |

## 2. Architecture

- **Single deployable service.** FastAPI serves the JSON API under `/api/v1` and the built React SPA from the same
  origin. This removes CORS from production, allows `SameSite=Strict` refresh cookies, and needs only one Render web
  service plus one database.
- **Layers.** `api/routes` (HTTP, validation, auth) → `services` (gateway, usage recording, pricing, analytics,
  alerts, analyst) → `models` (SQLAlchemy) ; `providers` encapsulate each upstream API; `core` holds cross-cutting
  concerns (config, security, crypto, logging, middleware, errors, rate limiting).
- **Data model.** `users`, `refresh_tokens`, `provider_credentials`, `projects`, `project_api_keys`, `api_requests`
  (metadata + pricing snapshot), `usage_daily` (UTC daily roll-up, upserted in the same transaction as each request),
  `model_pricing` (catalogue rows with `user_id NULL` + per-user overrides; unique with `NULLS NOT DISTINCT`), `budgets`,
  `alert_rules`, `notifications` (unique dedupe key), `analyst_conversations`, `analyst_messages`. All child rows
  cascade on user deletion; request history survives project deletion (`SET NULL`). Composite indexes cover
  `(user_id, created_at)` and its project/provider/status variants used by analytics and logs.
- **Gateway flow.** Sync DB work (key lookup, credential decryption, budget check, recording) runs in the thread pool;
  upstream HTTP uses a shared `httpx.AsyncClient`. Streaming responses are relayed chunk-by-chunk while a parser reads
  usage from SSE events; the record is written in a cancellation-shielded `finally`, so client disconnects are still
  logged. Budget and alert evaluation runs as a background task after the response.
- **Frontend.** React + TanStack Query (caching, loading/error states), React Router (lazy-loaded pages), URL-based
  filters (shareable views), Recharts, Tailwind design tokens. Access token in memory; automatic single-flight refresh.

## 3. Security implementation

Summarised from [SECURITY.md](SECURITY.md): Argon2id, short-lived JWTs with token versioning, rotating hashed refresh
tokens with theft detection, encrypted provider keys with rotation, hashed project keys, strict per-user scoping
(verified by tests), Pydantic validation, parameterised SQL, rate limiting, body-size limits, CSP/HSTS and other
headers, sanitised errors with request IDs, and a no-content logging policy with a redacting filter.

## 4. Testing results

Executed locally on 2026-11-15 (Windows 11, Python 3.12.10, Node 24, PostgreSQL 16 in Docker):

| Suite | Result |
| --- | --- |
| Backend `pytest` | **87 passed** |
| Backend `ruff check` / `ruff format --check` | clean |
| `alembic check` (models vs. migrations) | no drift; upgrade and downgrade exercised by tests |
| Frontend `vitest` | **16 passed** |
| Frontend `eslint` / `tsc` | clean |
| Frontend production build | succeeds |
| Docker image build + production smoke test | migrations, pricing seed, health, SPA, HSTS, `Secure` cookie, non-root user verified |
| Manual end-to-end check | registration, provider validation, projects/keys, 60 gateway requests (buffered + streaming, all three providers, against a local mock upstream), dashboard, logs, costs, budget and alert notifications, mobile layout |

Backend coverage by area: unit (hashing, JWT, encryption/rotation, redaction, rate limiter, settings), authentication
(register/login/lockout/refresh rotation/reuse/grace/logout/password change/sessions/deletion), provider credentials and
adapters (mocked validation, stream parsers, error classification), gateway (all providers, streaming, auth failures,
malformed bodies, upstream 401/429, timeouts, connection errors, unknown pricing, enforced budgets, no content
storage), pricing (resolution rules, overrides, math, snapshots, API), analytics (aggregates, filters, ranges,
summaries, logs search/sort/pagination), cross-user isolation, alerts/notifications, AI Analyst (not configured,
no-data path, OpenAI and Anthropic tool loops with mocked models, error sanitisation, tool scoping), and platform
(health, headers, request IDs, body limit, CORS, rate limit, migrations).

No test makes a paid provider call.

### Production deployment (Render, 2026-11-15)

| Item | Result |
| --- | --- |
| Web app | <https://modelops-ai.onrender.com> (Docker web service, Frankfurt, free plan) |
| API docs / health | `/api/docs` → 200 · `/api/v1/health` → `{"status":"ok","database":"ok"}` |
| Database | Dedicated `modelops` database created on the workspace's existing PostgreSQL 16 server (`render.shared-db.yaml`); migration `0001` applied, 25 reference prices seeded |
| HTTPS / headers | HTTP → HTTPS 301; HSTS, CSP, `X-Frame-Options: DENY`, `nosniff` present; foreign CORS origins rejected |
| Secrets | JWT and encryption keys generated by Render; no secrets in the frontend bundle (scanned) |
| Live functional test | register, login, wrong password, refresh via httpOnly cookie, profile, provider key validation against OpenAI (invalid key → `invalid`, no tokens used), project + key, gateway upstream 401 passthrough with request ID, `provider_not_configured`, `provider_not_allowed`, malformed body, bad project key, request logs, analytics, persistence across sessions, cross-user isolation (404), analyst `not_configured`, account deletion — all as expected; temporary test accounts were deleted |
| Pending external setup | Users add their own provider keys in the app; the AI Analyst needs `AI_ANALYST_*` set in the Render dashboard |

### QA audit — problems found and fixed

| # | Problem | Severity | Fix |
| --- | --- | --- | --- |
| 1 | Two tabs refreshing simultaneously tripped refresh-token reuse detection and logged the user out everywhere | Medium | 20-second rotation grace window (`rotated_at`), disabled after logout / revocation; tests added |
| 2 | Client-supplied `X-Request-ID` was reused as the unique request-log key, so a repeated ID made the record fail to save | Medium | Request IDs are always server-generated |
| 3 | Streaming relayed raw bytes; a gzip-encoded upstream stream would reach clients compressed and break usage parsing | Medium | Decoded byte iteration; regression test with a gzip SSE stream |
| 4 | Trusting all proxies made `X-Forwarded-For` spoofable for IP rate limits | Medium | `TRUSTED_PROXY_HOPS` (Render: 1) takes the proxy-appended entry; login limited per e-mail and per IP |
| 5 | Creating a project API key returned 500: the response model required the one-time `key` field while validating the ORM row | High | Response built explicitly; covered by gateway/isolation tests |
| 6 | SPA route rejected `HEAD` requests (some uptime monitors use them) | Low | `GET` + `HEAD` |
| 7 | Vitest 2 bundled an older Vite, breaking type-checking of `vite.config.ts` | Low | Upgraded to Vitest 3 |
| 8 | UI: model names wrapped in tables, tab bar showed a stray scrollbar, “new key” dialog reopened on refresh | Low | Fixed |
| 9 | Render allows one free database per workspace, so the standalone Blueprint could not create one | Deployment | `DATABASE_NAME` + `ensure-database` + `render.shared-db.yaml` |
| 10 | Logo rendered blank when a second (hidden) copy of the logo shared the same SVG gradient id | Low | Unique gradient id per instance |

## 5. Known limitations

- Costs are estimates: cached-input discounts, batch pricing, long-context tiers, image/audio tokens and regional
  prices are not modelled. Anthropic prompt-cache tokens are counted at the normal input price.
- Reference prices are seeded unverified and need manual upkeep; there is no automatic price feed.
- Gateway coverage: OpenAI Chat Completions, Anthropic Messages, Gemini generateContent/streamGenerateContent. The
  OpenAI Responses API, embeddings, images and audio endpoints are not proxied.
- One provider credential per provider per account (no per-project credentials).
- Rate limiting is per process (documented); horizontal scaling needs a shared store.
- Alerts are in-app only; there is no e-mail, Slack or webhook delivery.
- Day boundaries for summaries and budgets are UTC.
- The AI Analyst requires an operator-supplied OpenAI or Anthropic key; its quality depends on the chosen model.
- No organisations/teams or roles; every account is a single user.
- Screenshots in the README are placeholders until a hosted demo with real traffic exists.

## 6. Future improvements

1. Notification channels (e-mail, Slack, webhooks) with per-channel preferences.
2. Organisations, invitations and role-based access.
3. Pricing tiers (cached input, batch) and an importable price feed.
4. More endpoints (Responses API, embeddings) and providers (Azure OpenAI, Bedrock, Mistral).
5. Redis-backed rate limiting and background job queue for alert evaluation.
6. Optional, opt-in sampled payload logging with redaction and retention controls.
7. CSV/Parquet export and configurable data retention.
8. Playwright end-to-end tests in CI.

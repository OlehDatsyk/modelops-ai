# ModelOps AI — Instructions

How to install, configure, run, use, deploy and maintain ModelOps AI.

1. [Requirements](#requirements)
2. [Running locally](#running-locally)
3. [Configuration reference](#configuration-reference)
4. [Using the application](#using-the-application)
5. [Connecting your applications (gateway)](#connecting-your-applications-gateway)
6. [Enabling the AI Analyst](#enabling-the-ai-analyst)
7. [Testing and quality checks](#testing-and-quality-checks)
8. [Deploying to Render](#deploying-to-render)
9. [Maintenance](#maintenance)
10. [Troubleshooting](#troubleshooting)

---

## Requirements

| Tool | Version | Notes |
| --- | --- | --- |
| Python | 3.12+ | backend |
| Node.js | 20+ (22 recommended) | frontend build/dev server |
| PostgreSQL | 16 (15+ works) | `docker compose up -d db` provides one on port **5434** |
| Docker Desktop | optional | easiest way to run PostgreSQL or the full stack |

## Running locally

### Option A — launcher scripts (recommended)

- **Windows:** double-click **`Start App.bat`**.
- **macOS/Linux:** double-click **`Start App (Mac).command`** (first time: `chmod +x "Start App (Mac).command"`).

The launcher:

1. Checks that Python 3.12+ and Node.js are installed.
2. Creates `.env` from `.env.example` with freshly generated `JWT_SECRET_KEY` and `MASTER_ENCRYPTION_KEY`
   **only if `.env` does not exist** — an existing `.env` is never modified.
3. Creates `backend/.venv` if needed and installs backend dependencies; runs `npm install` on first run.
4. Checks the database connection; if it fails and Docker is available, runs `docker compose up -d db` and waits.
5. Runs `alembic upgrade head` and seeds the reference pricing catalogue (missing rows only).
6. Starts the backend on <http://localhost:8000> and the frontend on <http://localhost:5173>, then opens the browser.

### Option B — manual

```bash
cp .env.example .env
cd backend && python -m app.cli generate-secrets    # paste both values into .env
cd ..
docker compose up -d db

cd backend
python -m venv .venv
source .venv/bin/activate                           # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
alembic upgrade head
python -m app.cli seed-pricing
uvicorn app.main:app --reload --port 8000           # API + docs at http://localhost:8000/api/docs

# second terminal
cd frontend
npm install
npm run dev                                         # http://localhost:5173 (proxies /api to :8000)
```

### Option C — everything in Docker

```bash
docker compose up --build        # http://localhost:8000 — UI and API from the production image
```

The `app` service reads `.env` (so the two secrets must be set) and talks to the `db` service.

## Configuration reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `production` enables HSTS and `Secure` cookies |
| `DATABASE_URL` | local compose DB | Any of `postgres://`, `postgresql://`, `postgresql+psycopg://` |
| `DATABASE_NAME` | empty | Use this database on the `DATABASE_URL` server instead (created by `app.cli ensure-database`) |
| `JWT_SECRET_KEY` | — (**required**) | ≥ 32 characters |
| `MASTER_ENCRYPTION_KEY` | — (**required**) | ≥ 32 characters; comma-separated list for rotation (first encrypts) |
| `ACCESS_TOKEN_MINUTES` / `REFRESH_TOKEN_DAYS` | 15 / 14 | Token lifetimes |
| `FRONTEND_URL` / `BACKEND_URL` | localhost | Used as the default dev CORS origin |
| `CORS_ORIGINS` | empty | Comma-separated origins for a separately hosted frontend |
| `MAX_REQUEST_BYTES` | 2000000 | Request body cap (gateway payloads included) |
| `RATE_LIMIT_AUTH_PER_MINUTE` / `_API_` / `_GATEWAY_` | 10 / 300 / 120 | Per-process limits |
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCKOUT_MINUTES` | 5 / 15 | Account lockout |
| `TRUSTED_PROXY_HOPS` | 0 | Reverse proxies appending to `X-Forwarded-For` (Render: 1); used for IP rate limits |
| `PROVIDER_TIMEOUT_SECONDS` | 120 | Upstream read timeout (connect timeout 10 s) |
| `OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`, `GEMINI_BASE_URL` | official APIs | Override only for a corporate proxy |
| `AI_ANALYST_PROVIDER` / `AI_ANALYST_MODEL` / `AI_ANALYST_API_KEY` | empty | Enables the AI Analyst |
| `STATIC_DIR` | `frontend/dist` if built | Directory of the built SPA served by the backend |
| `LOG_LEVEL` | `INFO` | |

## Using the application

1. **Register** an account at `/register`, or sign in at `/login`.
2. **Providers** — add your OpenAI, Anthropic and/or Gemini API key. With *Validate now* the key is checked through the
   provider's model-list endpoint (free) and the available models are listed. Keys are encrypted; only a hint is shown.
3. **Projects** — create one project per application (e.g. *Customer Support AI*). Choose which providers it may use.
   Create an **API key** (`mk_…`) and copy it immediately — it is shown once.
4. **Gateway quickstart** — copy a cURL/Python/Node example and replace the key. Send a request.
5. **Dashboard** — totals, trends and distributions for the chosen range (24h/7d/30d/90d/custom), optionally filtered
   by project or provider. Percentage badges compare with the previous period of the same length.
6. **Request logs** — search by request ID/model/error, filter, sort, paginate; click a row for full details, the cost
   calculation and any error.
7. **Costs & pricing** — spend by provider/model/project, daily and monthly summaries. The **Pricing table** tab lists
   reference prices (unverified) and your custom prices; use *Override* to set your own price for a model, and the
   calculator to check which entry applies.
8. **Budgets & alerts** — create daily or monthly budgets (account-wide or per project) with warning thresholds;
   enable *Enforce limit* to block gateway traffic once the limit is reached. Create alert rules for error rate,
   request volume, token usage or spend. Notifications appear in the bell menu and in the history tab.
9. **AI Analyst** — ask questions in plain language; expand *Supporting data* to see the exact metrics it used.
10. **Settings** — update your name, change your password, review/revoke sessions, sign out everywhere or delete the account.

### Understanding cost estimates

- Cost = input tokens × input price + output tokens × output price (prices per 1M tokens).
- The price used is stored with each request, so later price edits never rewrite history.
- Models without a matching price show **unknown** cost and are excluded from totals (the dashboard warns you).
- Reference prices are standard-tier list prices recorded for convenience and marked **unverified**. Verify them
  against your provider's pricing page and override where needed. Cached-input, batch, long-context and regional
  pricing are not modelled.

## Connecting your applications (gateway)

| SDK | Setting |
| --- | --- |
| OpenAI (Python/Node) | `base_url = https://HOST/api/v1/gateway/openai`, `api_key = mk_…` |
| Anthropic (Python/Node) | `base_url = https://HOST/api/v1/gateway/anthropic`, `api_key = mk_…` |
| Google Gen AI | `http_options.base_url = https://HOST/api/v1/gateway/gemini`, `api_key = mk_…` |
| Plain HTTP | See [API_DOCUMENTATION.md → Gateway](API_DOCUMENTATION.md#gateway) |

Each response includes `x-modelops-request-id`, searchable in Request logs.

## Enabling the AI Analyst

The analyst uses a **platform-level** key (separate from users' provider keys), so its cost is borne by the operator.

```env
AI_ANALYST_PROVIDER=openai          # or anthropic
AI_ANALYST_MODEL=gpt-4.1-mini       # any tool-calling capable chat model available to your key
AI_ANALYST_API_KEY=sk-...
```

Restart the backend. The Analyst page shows a warning while it is not configured. Accounts without data receive a
fixed explanation without any model call.

## Testing and quality checks

```bash
docker compose up -d db            # provides the modelops_test database (created on first start)
cd backend
pytest                             # uses TEST_DATABASE_URL (default: compose DB, database modelops_test)
ruff check . && ruff format --check .
alembic check                      # models and migrations are in sync

cd ../frontend
npm run lint && npm run typecheck && npm test && npm run build
```

If your compose database volume was created before `docker/postgres-init.sql` existed, create the test database
once: `docker compose exec db createdb -U modelops modelops_test`.

## Deploying to Render

The repository contains `render.yaml` (a Render Blueprint) describing:

- **`modelops-db`** — PostgreSQL 16 (free plan, no public access).
- **`modelops-ai`** — Docker web service built from `Dockerfile`, health check `/api/v1/health`, auto-deploy on push.

Steps:

1. Push the repository to GitHub.
2. In the Render dashboard: **New → Blueprint** → connect GitHub → select the repository → **Apply**.
3. Render creates the database, generates `JWT_SECRET_KEY` and `MASTER_ENCRYPTION_KEY`, sets `DATABASE_URL`, builds
   the image and starts the service. The container runs migrations and seeds pricing on every start.
4. Optional: in **modelops-ai → Environment**, set `AI_ANALYST_PROVIDER`, `AI_ANALYST_MODEL`, `AI_ANALYST_API_KEY`
   and save (triggers a redeploy).
5. Open `https://<service>.onrender.com`, register, and verify `https://<service>.onrender.com/api/v1/health`.

### Sharing an existing PostgreSQL server

Render allows one free PostgreSQL instance per workspace. If yours is already in use, deploy with
**`render.shared-db.yaml`** (Blueprint Path field): it creates only the web service, takes the server credentials
of an existing database via `fromDatabase` (edit `name` and `region` to match yours), and sets
`DATABASE_NAME=modelops`. On start, `python -m app.cli ensure-database` creates that separate database on the shared
server, so ModelOps tables never mix with the other application's tables. Note that it shares that server's storage
and free-tier lifetime.

Notes:

- **Back up `MASTER_ENCRYPTION_KEY`** from the Render dashboard; without it stored provider keys cannot be decrypted.
- Free web services sleep after inactivity (first request takes ~30–60 s). Free PostgreSQL databases expire after a
  limited period on Render's free tier — upgrade the plan for production data.
- Keep a single instance (or add a shared rate-limit store) — see SECURITY.md.

## Maintenance

| Task | Command / action |
| --- | --- |
| Apply migrations | `alembic upgrade head` (automatic in Docker) |
| Create a migration after model changes | `alembic revision --autogenerate -m "describe change"`, review it, commit it |
| Check models vs. migrations | `alembic check` |
| Create the app database on a shared server | `python -m app.cli ensure-database` (automatic in Docker) |
| Seed missing reference prices | `python -m app.cli seed-pricing` (never overwrites) |
| Rotate the encryption key | set `MASTER_ENCRYPTION_KEY=new,old` → `python -m app.cli rotate-keys` → set `MASTER_ENCRYPTION_KEY=new` |
| Rotate the JWT secret | change `JWT_SECRET_KEY` (signs everyone out of access tokens; refresh cookies keep working) |
| Verify configuration | `python -m app.cli check` |
| Update reference prices | edit `REFERENCE_PRICES` in `backend/app/services/pricing.py` for new models, or override prices in the UI |
| Dependency updates | update pinned versions in `backend/requirements*.txt` / `frontend/package.json`, run the full test suite |
| Backups | use Render's database backups (paid plans) or `pg_dump` |

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `JWT_SECRET_KEY must be set` on start | Set both secrets in `.env` (≥ 32 characters) |
| `connection refused` / timeout to PostgreSQL | `docker compose up -d db`; on Windows use `127.0.0.1` rather than `localhost` |
| Gateway returns `provider_not_configured` | Add the provider key in **Providers** for the account that owns the project key |
| Gateway returns `provider_not_allowed` | Enable the provider in the project settings |
| Gateway returns `402 budget_exceeded` | Raise or disable the enforced budget, or wait for the next period |
| Cost shows *unknown* | Add a price for the model in **Costs & pricing → Pricing table** |
| Credential status *invalid* | The provider rejected the key; replace it |
| Stored keys cannot be decrypted | `MASTER_ENCRYPTION_KEY` changed; restore the old value or re-enter keys |
| Analyst says not configured | Set the three `AI_ANALYST_*` variables and restart |

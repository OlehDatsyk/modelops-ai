# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-11-15

### Added
- **Gateway** for OpenAI Chat Completions, Anthropic Messages and Gemini `generateContent` (simple and native paths),
  including streaming (SSE) with token-usage capture, request IDs, timeouts, provider error passthrough and
  per-key rate limiting. Compatible with the official OpenAI, Anthropic and Google SDKs via base-URL change.
- **Provider adapters** with key validation through each provider's model-list endpoint and model discovery.
- **Encrypted provider credentials** (Fernet + HKDF) with masked hints and key rotation command.
- **Projects** with allowed providers, hashed project API keys (create/revoke) and per-project statistics.
- **Analytics dashboard**: totals, previous-period comparison, spend/volume/token/error-rate charts, provider and model
  distribution, project breakdown; 24h/7d/30d/90d/custom ranges and project/provider filters.
- **Cost intelligence**: pricing catalogue (unverified reference prices) plus per-account overrides, pricing snapshot on
  every request, unknown-price handling, spend by provider/model/project, daily and monthly summaries, cost calculator.
- **Request logs** with search, filters, sorting, pagination and a detail view with error inspection.
- **Budgets** (daily/monthly, thresholds, optional enforcement), **alert rules** (error rate, volume, tokens, spend),
  de-duplicated **in-app notifications** and history.
- **AI Analyst** using OpenAI or Anthropic tool calling over a controlled, user-scoped analytics tool layer.
- **Accounts**: registration, login, logout, refresh-token rotation with reuse detection, sessions, sign-out
  everywhere, profile, password change, account deletion, login lockout.
- **Security**: security headers, CSP, body-size limits, CORS restrictions, sanitised errors, redacting log filter.
- PostgreSQL schema with Alembic migrations and a daily usage roll-up table.
- 87 backend tests (pytest + respx, real PostgreSQL) and 16 frontend tests (Vitest + Testing Library).
- Dockerfile (multi-stage, non-root), Docker Compose, Render Blueprint, GitHub Actions CI, Windows/macOS launchers.

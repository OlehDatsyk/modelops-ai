"""Controlled analytics tools exposed to the AI Analyst.

The language model never writes SQL. It can only call these functions with validated,
bounded arguments; the user ID is injected server-side and cannot be chosen by the model.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import ApiRequest, ModelPricing, Project
from app.services import analytics

Period = Literal["today", "yesterday", "last_7_days", "last_30_days", "last_90_days", "this_month", "last_month"]


def period_bounds(period: Period, now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or utcnow()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        return midnight, now
    if period == "yesterday":
        return midnight - timedelta(days=1), midnight
    if period == "this_month":
        return midnight.replace(day=1), now
    if period == "last_month":
        first_this = midnight.replace(day=1)
        return (first_this - timedelta(days=1)).replace(day=1), first_this
    days = {"last_7_days": 7, "last_30_days": 30, "last_90_days": 90}[period]
    return now - timedelta(days=days), now


class _ProjectArg(BaseModel):
    project_name: str | None = Field(default=None, max_length=100, description="Optional exact project name")


class SpendSummaryArgs(_ProjectArg):
    period: Period = Field(description="Time period to summarise (UTC)")


class CompareArgs(_ProjectArg):
    days: int = Field(default=7, ge=1, le=90, description="Compare the last N days with the N days before")


class BreakdownArgs(_ProjectArg):
    dimension: Literal["provider", "model", "project"]
    period: Period = "last_30_days"


class DailySpendArgs(_ProjectArg):
    days: int = Field(default=14, ge=1, le=90)


class ErrorsArgs(_ProjectArg):
    period: Period = "last_7_days"


class OptimisationArgs(_ProjectArg):
    period: Period = "last_30_days"


@dataclass
class ToolContext:
    db: Session
    user_id: uuid.UUID

    def project_id(self, name: str | None) -> uuid.UUID | None:
        if not name:
            return None
        pid = self.db.scalar(select(Project.id).where(Project.user_id == self.user_id, Project.name == name))
        if pid is None:
            raise ToolError(f"No project named '{name}' in this account")
        return pid

    def filters(self, start: datetime, end: datetime, project_name: str | None) -> analytics.Filters:
        return analytics.Filters(self.user_id, start, end, self.project_id(project_name))


class ToolError(Exception):
    pass


def spend_summary(ctx: ToolContext, args: SpendSummaryArgs) -> dict[str, Any]:
    start, end = period_bounds(args.period)
    s = analytics.summary(ctx.db, ctx.filters(start, end, args.project_name))
    return {"period": args.period, "start": start.isoformat(), "end": end.isoformat(), **s}


def compare_periods(ctx: ToolContext, args: CompareArgs) -> dict[str, Any]:
    end = utcnow()
    current = ctx.filters(end - timedelta(days=args.days), end, args.project_name)
    previous = current.shifted_back()

    def by_model(f: analytics.Filters) -> dict[str, dict[str, Any]]:
        return {f"{r['provider']}/{r['model']}": r for r in analytics.breakdown(ctx.db, f, "model", limit=100)}

    cur_models, prev_models = by_model(current), by_model(previous)
    changes = []
    for key in set(cur_models) | set(prev_models):
        c, p = cur_models.get(key, {}), prev_models.get(key, {})
        changes.append(
            {
                "model": key,
                "cost_now": c.get("estimated_cost_usd", 0.0),
                "cost_before": p.get("estimated_cost_usd", 0.0),
                "cost_change": round(c.get("estimated_cost_usd", 0.0) - p.get("estimated_cost_usd", 0.0), 6),
                "requests_now": c.get("requests", 0),
                "requests_before": p.get("requests", 0),
                "tokens_now": c.get("total_tokens", 0),
                "tokens_before": p.get("total_tokens", 0),
            }
        )
    changes.sort(key=lambda x: abs(x["cost_change"]), reverse=True)
    return {
        "window_days": args.days,
        "current": analytics.summary(ctx.db, current)["current"],
        "previous": analytics.summary(ctx.db, previous)["current"],
        "largest_model_changes": changes[:10],
    }


def breakdown(ctx: ToolContext, args: BreakdownArgs) -> dict[str, Any]:
    start, end = period_bounds(args.period)
    rows = analytics.breakdown(ctx.db, ctx.filters(start, end, args.project_name), args.dimension, limit=20)
    return {"period": args.period, "dimension": args.dimension, "rows": rows}


def daily_spend(ctx: ToolContext, args: DailySpendArgs) -> dict[str, Any]:
    end = utcnow()
    f = ctx.filters(end - timedelta(days=args.days), end, args.project_name)
    series = analytics.timeseries(ctx.db, f, "day")
    return {
        "days": args.days,
        "series": [
            {k: p[k] for k in ("bucket", "requests", "errors", "cost_usd", "input_tokens", "output_tokens")}
            for p in series
        ],
    }


def error_analysis(ctx: ToolContext, args: ErrorsArgs) -> dict[str, Any]:
    start, end = period_bounds(args.period)
    stmt = (
        select(ApiRequest.provider, ApiRequest.error_type, ApiRequest.http_status, func.count(ApiRequest.id))
        .where(
            ApiRequest.user_id == ctx.user_id,
            ApiRequest.status == "error",
            ApiRequest.created_at >= start,
            ApiRequest.created_at < end,
        )
        .group_by(ApiRequest.provider, ApiRequest.error_type, ApiRequest.http_status)
        .order_by(func.count(ApiRequest.id).desc())
        .limit(20)
    )
    pid = ctx.project_id(args.project_name)
    if pid:
        stmt = stmt.where(ApiRequest.project_id == pid)
    rows = [{"provider": p, "error_type": e, "http_status": s, "count": int(n)} for p, e, s, n in ctx.db.execute(stmt)]
    providers = analytics.breakdown(ctx.db, ctx.filters(start, end, args.project_name), "provider")
    return {
        "period": args.period,
        "error_rate_by_provider": [
            {
                "provider": r["provider"],
                "requests": r["requests"],
                "errors": r["errors"],
                "error_rate": r["error_rate"],
            }
            for r in providers
        ],
        "top_errors": rows,
    }


def optimisation_signals(ctx: ToolContext, args: OptimisationArgs) -> dict[str, Any]:
    start, end = period_bounds(args.period)
    f = ctx.filters(start, end, args.project_name)
    models = analytics.breakdown(ctx.db, f, "model", limit=20)
    catalogue = ctx.db.scalars(
        select(ModelPricing).where((ModelPricing.user_id == ctx.user_id) | (ModelPricing.user_id.is_(None)))
    ).all()
    signals = []
    for m in models:
        n = m["requests"] or 1
        current_price = next(
            (p for p in catalogue if p.provider == m["provider"] and m["model"].startswith(p.model)), None
        )
        cheaper = []
        if current_price is not None:
            for p in catalogue:
                if p.provider == m["provider"] and p.model != current_price.model:
                    blended_now = current_price.input_price_per_mtok + current_price.output_price_per_mtok
                    blended_alt = p.input_price_per_mtok + p.output_price_per_mtok
                    if blended_alt < blended_now:
                        cheaper.append(
                            {
                                "model": p.model,
                                "input_per_mtok": float(p.input_price_per_mtok),
                                "output_per_mtok": float(p.output_price_per_mtok),
                                "price_verified": p.verified,
                            }
                        )
        signals.append(
            {
                "model": f"{m['provider']}/{m['model']}",
                "cost_usd": m["estimated_cost_usd"],
                "cost_share_pct": m["cost_share"],
                "requests": m["requests"],
                "avg_input_tokens": round(m["input_tokens"] / n, 1),
                "avg_output_tokens": round(m["output_tokens"] / n, 1),
                "cost_per_request_usd": round(m["estimated_cost_usd"] / n, 6),
                "error_rate_pct": m["error_rate"],
                "unpriced_requests": m["unpriced_requests"],
                "cheaper_same_provider_models": sorted(cheaper, key=lambda x: x["input_per_mtok"])[:4],
            }
        )
    return {"period": args.period, "models": signals}


@dataclass
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    fn: Callable[[ToolContext, Any], dict[str, Any]]

    def json_schema(self) -> dict[str, Any]:
        schema = self.args.model_json_schema()
        schema.pop("title", None)
        return schema


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "get_spend_summary",
            "Totals for a period: requests, failures, tokens, estimated cost, latency, "
            "plus the same metrics for the immediately preceding period of equal length.",
            SpendSummaryArgs,
            spend_summary,
        ),
        Tool(
            "compare_periods",
            "Compare the last N days with the previous N days, including the models whose "
            "cost changed most. Use for 'why did costs increase' questions.",
            CompareArgs,
            compare_periods,
        ),
        Tool(
            "get_breakdown",
            "Requests, tokens, estimated cost, error rate and latency grouped by provider, model or project.",
            BreakdownArgs,
            breakdown,
        ),
        Tool(
            "get_daily_spend",
            "Daily estimated spend, requests, errors and tokens for the last N days.",
            DailySpendArgs,
            daily_spend,
        ),
        Tool(
            "get_error_analysis",
            "Failure rate per provider and the most common error types.",
            ErrorsArgs,
            error_analysis,
        ),
        Tool(
            "get_optimisation_signals",
            "Per-model cost per request, average token sizes, error rates and "
            "cheaper models from the same provider according to the pricing table.",
            OptimisationArgs,
            optimisation_signals,
        ),
    ]
}


def run_tool(ctx: ToolContext, name: str, raw_args: dict[str, Any]) -> dict[str, Any]:
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"Unknown tool '{name}'"}
    try:
        args = tool.args.model_validate(raw_args or {})
        return tool.fn(ctx, args)
    except ToolError as exc:
        return {"error": str(exc)}
    except ValueError as exc:  # pydantic ValidationError subclasses ValueError
        return {"error": f"Invalid arguments: {str(exc)[:300]}"}


def account_has_data(db: Session, user_id: uuid.UUID) -> bool:
    return db.scalar(select(ApiRequest.id).where(ApiRequest.user_id == user_id).limit(1)) is not None

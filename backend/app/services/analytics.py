"""Analytics queries. Every function is scoped to a single user via ``Filters.user_id``."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.base import utcnow
from app.models import ApiRequest, Project, UsageDaily

RANGES = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}
MAX_CUSTOM_RANGE = timedelta(days=366)


@dataclass
class Filters:
    user_id: uuid.UUID
    start: datetime
    end: datetime
    project_id: uuid.UUID | None = None
    provider: str | None = None
    model: str | None = None

    def shifted_back(self) -> Filters:
        span = self.end - self.start
        return Filters(self.user_id, self.start - span, self.start, self.project_id, self.provider, self.model)


def resolve_range(
    range_key: str | None, start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime, str]:
    """Return (start, end, granularity) for a preset or custom range."""
    now = utcnow()
    if range_key == "custom" or (range_key is None and start and end):
        if not start or not end:
            raise AppError(422, "validation_error", "Custom ranges require both start and end")
        start = start if start.tzinfo else start.replace(tzinfo=UTC)
        end = end if end.tzinfo else end.replace(tzinfo=UTC)
        if end <= start:
            raise AppError(422, "validation_error", "End must be after start")
        if end - start > MAX_CUSTOM_RANGE:
            raise AppError(422, "validation_error", "Custom ranges are limited to 366 days")
    else:
        span = RANGES.get(range_key or "7d")
        if span is None:
            raise AppError(422, "validation_error", f"Unknown range '{range_key}'")
        start, end = now - span, now
    granularity = "hour" if end - start <= timedelta(hours=48) else "day"
    return start, end, granularity


def _where(stmt: Select, f: Filters) -> Select:
    stmt = stmt.where(ApiRequest.user_id == f.user_id, ApiRequest.created_at >= f.start, ApiRequest.created_at < f.end)
    if f.project_id:
        stmt = stmt.where(ApiRequest.project_id == f.project_id)
    if f.provider:
        stmt = stmt.where(ApiRequest.provider == f.provider)
    if f.model:
        stmt = stmt.where(ApiRequest.model == f.model)
    return stmt


_is_error = case((ApiRequest.status == "error", 1), else_=0)
_is_success = case((ApiRequest.status == "success", 1), else_=0)
_is_unpriced = case(((ApiRequest.cost_status == "unknown") & (ApiRequest.total_tokens > 0), 1), else_=0)


def _f(value: Any) -> float:
    return float(value or 0)


def _summary_row(db: Session, f: Filters) -> dict[str, Any]:
    stmt = _where(
        select(
            func.count(ApiRequest.id),
            func.coalesce(func.sum(_is_success), 0),
            func.coalesce(func.sum(_is_error), 0),
            func.coalesce(func.sum(ApiRequest.input_tokens), 0),
            func.coalesce(func.sum(ApiRequest.output_tokens), 0),
            func.coalesce(func.sum(ApiRequest.cost_total_usd), 0),
            func.avg(ApiRequest.latency_ms),
            func.coalesce(func.sum(_is_unpriced), 0),
        ),
        f,
    )
    total, ok, errors, inp, out, cost, latency, unpriced = db.execute(stmt).one()
    return {
        "total_requests": int(total),
        "successful_requests": int(ok),
        "failed_requests": int(errors),
        "error_rate": round(errors / total * 100, 2) if total else 0.0,
        "input_tokens": int(inp),
        "output_tokens": int(out),
        "total_tokens": int(inp) + int(out),
        "estimated_cost_usd": round(_f(cost), 6),
        "avg_latency_ms": round(_f(latency), 1) if latency is not None else None,
        "unpriced_requests": int(unpriced),
    }


def summary(db: Session, f: Filters) -> dict[str, Any]:
    current = _summary_row(db, f)
    previous = _summary_row(db, f.shifted_back())
    return {"current": current, "previous": previous}


def _bucket_iter(start: datetime, end: datetime, granularity: str):
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
    cursor = start.replace(minute=0, second=0, microsecond=0)
    if granularity == "day":
        cursor = cursor.replace(hour=0)
    while cursor < end:
        yield cursor
        cursor += step


def timeseries(db: Session, f: Filters, granularity: str) -> list[dict[str, Any]]:
    bucket = func.date_trunc(granularity, ApiRequest.created_at).label("bucket")
    stmt = _where(
        select(
            bucket,
            func.count(ApiRequest.id),
            func.coalesce(func.sum(_is_error), 0),
            func.coalesce(func.sum(ApiRequest.input_tokens), 0),
            func.coalesce(func.sum(ApiRequest.output_tokens), 0),
            func.coalesce(func.sum(ApiRequest.cost_total_usd), 0),
            func.avg(ApiRequest.latency_ms),
        ),
        f,
    ).group_by(bucket)
    rows = {}
    for b, total, errors, inp, out, cost, latency in db.execute(stmt):
        key = b.astimezone(UTC) if b.tzinfo else b.replace(tzinfo=UTC)
        rows[key] = (total, errors, inp, out, cost, latency)

    series = []
    for ts in _bucket_iter(f.start, f.end, granularity):
        total, errors, inp, out, cost, latency = rows.get(ts, (0, 0, 0, 0, 0, None))
        series.append(
            {
                "bucket": ts.isoformat(),
                "requests": int(total),
                "errors": int(errors),
                "error_rate": round(errors / total * 100, 2) if total else 0.0,
                "input_tokens": int(inp),
                "output_tokens": int(out),
                "cost_usd": round(_f(cost), 6),
                "avg_latency_ms": round(_f(latency), 1) if latency is not None else None,
            }
        )
    return series


def breakdown(db: Session, f: Filters, dimension: str, limit: int = 50) -> list[dict[str, Any]]:
    if dimension == "provider":
        key_cols = [ApiRequest.provider]
    elif dimension == "model":
        key_cols = [ApiRequest.provider, ApiRequest.model]
    elif dimension == "project":
        key_cols = [ApiRequest.project_id, Project.name]
    else:
        raise AppError(422, "validation_error", "dimension must be provider, model or project")

    cost_sum = func.coalesce(func.sum(ApiRequest.cost_total_usd), 0)
    stmt = select(
        *key_cols,
        func.count(ApiRequest.id),
        func.coalesce(func.sum(_is_error), 0),
        func.coalesce(func.sum(ApiRequest.input_tokens), 0),
        func.coalesce(func.sum(ApiRequest.output_tokens), 0),
        cost_sum,
        func.avg(ApiRequest.latency_ms),
        func.coalesce(func.sum(_is_unpriced), 0),
    )
    if dimension == "project":
        stmt = stmt.select_from(ApiRequest).outerjoin(
            Project, (Project.id == ApiRequest.project_id) & (Project.user_id == f.user_id)
        )
    stmt = _where(stmt, f).group_by(*key_cols).order_by(cost_sum.desc(), func.count(ApiRequest.id).desc())
    rows = db.execute(stmt.limit(limit)).all()

    total_requests = sum(r[len(key_cols)] for r in rows) or 0
    total_cost = sum(_f(r[len(key_cols) + 4]) for r in rows) or 0.0
    out = []
    for r in rows:
        keys, (count, errors, inp, outp, cost, latency, unpriced) = r[: len(key_cols)], r[len(key_cols) :]
        item: dict[str, Any] = {
            "requests": int(count),
            "errors": int(errors),
            "error_rate": round(errors / count * 100, 2) if count else 0.0,
            "input_tokens": int(inp),
            "output_tokens": int(outp),
            "total_tokens": int(inp) + int(outp),
            "estimated_cost_usd": round(_f(cost), 6),
            "avg_latency_ms": round(_f(latency), 1) if latency is not None else None,
            "unpriced_requests": int(unpriced),
            "request_share": round(count / total_requests * 100, 2) if total_requests else 0.0,
            "cost_share": round(_f(cost) / total_cost * 100, 2) if total_cost else 0.0,
        }
        if dimension == "provider":
            item["provider"] = keys[0]
        elif dimension == "model":
            item["provider"], item["model"] = keys[0], keys[1] or "(unknown)"
        else:
            item["project_id"] = str(keys[0]) if keys[0] else None
            item["project_name"] = keys[1] or "(no project)"
        out.append(item)
    return out


def spend_summaries(db: Session, user_id: uuid.UUID, project_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Daily (last 30 days) and monthly (last 12 months) estimated spend from the roll-up table."""
    today = utcnow().date()

    def scoped(*cols: Any) -> Select:
        stmt = select(*cols).where(UsageDaily.user_id == user_id)
        return stmt.where(UsageDaily.project_id == project_id) if project_id else stmt

    tokens = func.sum(UsageDaily.input_tokens + UsageDaily.output_tokens)
    day_start = today - timedelta(days=29)
    daily_rows = db.execute(
        scoped(UsageDaily.day, func.sum(UsageDaily.cost_usd), func.sum(UsageDaily.request_count), tokens)
        .where(UsageDaily.day >= day_start)
        .group_by(UsageDaily.day)
    ).all()
    by_day = {d: (c, n, t) for d, c, n, t in daily_rows}
    daily = []
    for i in range(30):
        d = day_start + timedelta(days=i)
        c, n, t = by_day.get(d, (0, 0, 0))
        daily.append({"day": d.isoformat(), "cost_usd": round(_f(c), 6), "requests": int(n), "tokens": int(t)})

    month = func.date_trunc("month", UsageDaily.day).label("month")
    first_month = (today.replace(day=1) - timedelta(days=335)).replace(day=1)
    monthly_rows = db.execute(
        scoped(month, func.sum(UsageDaily.cost_usd), func.sum(UsageDaily.request_count), tokens)
        .where(UsageDaily.day >= first_month)
        .group_by(month)
        .order_by(month)
    ).all()
    monthly = [
        {"month": m.isoformat()[:7], "cost_usd": round(_f(c), 6), "requests": int(n), "tokens": int(t)}
        for m, c, n, t in monthly_rows
    ]
    month_to_date = db.scalar(
        scoped(func.coalesce(func.sum(UsageDaily.cost_usd), 0)).where(UsageDaily.day >= today.replace(day=1))
    )
    return {
        "daily": daily,
        "monthly": monthly,
        "today_usd": daily[-1]["cost_usd"],
        "month_to_date_usd": round(_f(month_to_date), 6),
    }

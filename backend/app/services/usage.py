"""Recording gateway requests and maintaining the daily usage roll-up."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import ApiRequest, UsageDaily
from app.providers.base import Usage
from app.services.pricing import estimate_cost, resolve_pricing


@dataclass
class RequestRecord:
    request_id: str
    user_id: uuid.UUID
    project_id: uuid.UUID | None
    api_key_id: uuid.UUID | None
    provider: str
    model: str
    endpoint: str
    streamed: bool
    http_status: int
    latency_ms: int
    usage: Usage
    error_type: str | None = None
    error_message: str | None = None

    @property
    def success(self) -> bool:
        return self.error_type is None and 200 <= self.http_status < 300


def record_request(db: Session, rec: RequestRecord) -> ApiRequest:
    """Insert the request row and update the roll-up in a single transaction."""
    pricing = resolve_pricing(db, rec.user_id, rec.provider, rec.model) if rec.model else None
    cost = estimate_cost(rec.usage, pricing)
    now = utcnow()
    row = ApiRequest(
        request_id=rec.request_id,
        user_id=rec.user_id,
        project_id=rec.project_id,
        api_key_id=rec.api_key_id,
        provider=rec.provider,
        model=rec.model[:120],
        endpoint=rec.endpoint,
        streamed=rec.streamed,
        status="success" if rec.success else "error",
        http_status=rec.http_status,
        error_type=rec.error_type,
        error_message=(rec.error_message or None) and rec.error_message[:500],
        input_tokens=rec.usage.input_tokens,
        output_tokens=rec.usage.output_tokens,
        total_tokens=rec.usage.total_tokens,
        latency_ms=rec.latency_ms,
        pricing_id=pricing.id if pricing else None,
        pricing_model_key=pricing.model if pricing else None,
        input_price_per_mtok=pricing.input_price_per_mtok if pricing else None,
        output_price_per_mtok=pricing.output_price_per_mtok if pricing else None,
        pricing_verified=bool(pricing and pricing.verified),
        cost_input_usd=cost.input_cost,
        cost_output_usd=cost.output_cost,
        cost_total_usd=cost.total_cost,
        cost_status=cost.status,
        created_at=now,
    )
    db.add(row)

    values = {
        "id": uuid.uuid4(),
        "user_id": rec.user_id,
        "project_id": rec.project_id,
        "project_key": str(rec.project_id) if rec.project_id else "",
        "provider": rec.provider,
        "model": rec.model[:120] or "(unknown)",
        "day": now.date(),
        "request_count": 1,
        "error_count": 0 if rec.success else 1,
        "input_tokens": rec.usage.input_tokens,
        "output_tokens": rec.usage.output_tokens,
        "cost_usd": cost.total_cost or Decimal(0),
        "unpriced_requests": 1 if cost.total_cost is None and rec.usage.total_tokens > 0 else 0,
        "latency_ms_sum": rec.latency_ms,
    }
    stmt = pg_insert(UsageDaily).values(**values)
    t = UsageDaily.__table__.c
    stmt = stmt.on_conflict_do_update(
        constraint="uq_usage_daily_bucket",
        set_={
            "request_count": t.request_count + stmt.excluded.request_count,
            "error_count": t.error_count + stmt.excluded.error_count,
            "input_tokens": t.input_tokens + stmt.excluded.input_tokens,
            "output_tokens": t.output_tokens + stmt.excluded.output_tokens,
            "cost_usd": t.cost_usd + stmt.excluded.cost_usd,
            "unpriced_requests": t.unpriced_requests + stmt.excluded.unpriced_requests,
            "latency_ms_sum": t.latency_ms_sum + stmt.excluded.latency_ms_sum,
        },
    )
    db.execute(stmt)
    db.commit()
    return row

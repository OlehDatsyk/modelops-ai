"""Dashboard analytics computed from the caller's own request records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.projects import get_owned_project
from app.db.session import get_db
from app.models import User
from app.services import analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])

RangeKey = Literal["24h", "7d", "30d", "90d", "custom"]


def _filters(
    user: User,
    db: Session,
    range_key: RangeKey | None,
    start: datetime | None,
    end: datetime | None,
    project_id: uuid.UUID | None,
    provider: str | None,
    model: str | None,
) -> tuple[analytics.Filters, str]:
    if project_id:
        get_owned_project(db, user, project_id)  # 404 for projects the user does not own
    s, e, granularity = analytics.resolve_range(range_key, start, end)
    return analytics.Filters(user.id, s, e, project_id, provider or None, model or None), granularity


@router.get("/overview")
def overview(
    range: RangeKey | None = Query(default="7d"),
    start: datetime | None = None,
    end: datetime | None = None,
    project_id: uuid.UUID | None = None,
    provider: Literal["openai", "anthropic", "gemini"] | None = None,
    model: str | None = Query(default=None, max_length=120),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Summary cards, time series and breakdowns for the selected range in one round trip."""
    f, granularity = _filters(user, db, range, start, end, project_id, provider, model)
    return {
        "range": {"start": f.start.isoformat(), "end": f.end.isoformat(), "granularity": granularity},
        "summary": analytics.summary(db, f),
        "timeseries": analytics.timeseries(db, f, granularity),
        "by_provider": analytics.breakdown(db, f, "provider"),
        "by_model": analytics.breakdown(db, f, "model", limit=15),
        "by_project": analytics.breakdown(db, f, "project", limit=15),
    }


@router.get("/costs")
def costs(
    range: RangeKey | None = Query(default="30d"),
    start: datetime | None = None,
    end: datetime | None = None,
    project_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Spending by provider, model and project plus daily and monthly summaries."""
    f, granularity = _filters(user, db, range, start, end, project_id, None, None)
    summary = analytics.summary(db, f)
    return {
        "range": {"start": f.start.isoformat(), "end": f.end.isoformat(), "granularity": granularity},
        "total_usd": summary["current"]["estimated_cost_usd"],
        "previous_total_usd": summary["previous"]["estimated_cost_usd"],
        "unpriced_requests": summary["current"]["unpriced_requests"],
        "trend": [{"bucket": p["bucket"], "cost_usd": p["cost_usd"]} for p in analytics.timeseries(db, f, granularity)],
        "by_provider": analytics.breakdown(db, f, "provider"),
        "by_model": analytics.breakdown(db, f, "model"),
        "by_project": analytics.breakdown(db, f, "project"),
        "summaries": analytics.spend_summaries(db, user.id, project_id),
    }

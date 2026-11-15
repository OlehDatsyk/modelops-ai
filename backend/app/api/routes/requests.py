"""Request log browsing: search, filter, sort, paginate and inspect."""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import not_found
from app.db.session import get_db
from app.models import ApiRequest, Project, User
from app.schemas.resources import RequestDetail, RequestOut, RequestPage

router = APIRouter(prefix="/requests", tags=["requests"])

SORT_COLUMNS = {
    "created_at": ApiRequest.created_at,
    "latency_ms": ApiRequest.latency_ms,
    "cost": ApiRequest.cost_total_usd,
    "total_tokens": ApiRequest.total_tokens,
    "input_tokens": ApiRequest.input_tokens,
    "output_tokens": ApiRequest.output_tokens,
}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=RequestPage)
def list_requests(
    q: str | None = Query(default=None, max_length=120, description="Search request ID, model or error"),
    provider: Literal["openai", "anthropic", "gemini"] | None = None,
    status: Literal["success", "error"] | None = None,
    project_id: uuid.UUID | None = None,
    model: str | None = Query(default=None, max_length=120),
    start: datetime | None = None,
    end: datetime | None = None,
    sort: Literal["created_at", "latency_ms", "cost", "total_tokens", "input_tokens", "output_tokens"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conditions = [ApiRequest.user_id == user.id]
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        conditions.append(
            or_(
                ApiRequest.request_id.ilike(pattern, escape="\\"),
                ApiRequest.model.ilike(pattern, escape="\\"),
                ApiRequest.error_message.ilike(pattern, escape="\\"),
                ApiRequest.error_type.ilike(pattern, escape="\\"),
            )
        )
    if provider:
        conditions.append(ApiRequest.provider == provider)
    if status:
        conditions.append(ApiRequest.status == status)
    if project_id:
        conditions.append(ApiRequest.project_id == project_id)
    if model:
        conditions.append(ApiRequest.model == model)
    if start:
        conditions.append(ApiRequest.created_at >= start)
    if end:
        conditions.append(ApiRequest.created_at < end)

    total = db.scalar(select(func.count(ApiRequest.id)).where(*conditions)) or 0
    column = SORT_COLUMNS[sort]
    ordering = column.asc().nulls_last() if order == "asc" else column.desc().nulls_last()
    rows = db.execute(
        select(ApiRequest, Project.name)
        .outerjoin(Project, (Project.id == ApiRequest.project_id) & (Project.user_id == user.id))
        .where(*conditions)
        .order_by(ordering, ApiRequest.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [RequestOut.model_validate(r).model_copy(update={"project_name": name}) for r, name in rows]
    return RequestPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/models", response_model=list[str])
def distinct_models(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Models seen in this account's requests (for filter drop-downs)."""
    return list(
        db.scalars(
            select(ApiRequest.model).where(ApiRequest.user_id == user.id, ApiRequest.model != "").distinct().limit(200)
        )
    )


@router.get("/{request_ref}", response_model=RequestDetail)
def get_request(request_ref: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Look up by internal UUID or by the public request ID (``req_...``)."""
    condition = ApiRequest.request_id == request_ref[:64]
    with contextlib.suppress(ValueError):
        condition = or_(condition, ApiRequest.id == uuid.UUID(request_ref))
    row = db.execute(
        select(ApiRequest, Project.name)
        .outerjoin(Project, (Project.id == ApiRequest.project_id) & (Project.user_id == user.id))
        .where(ApiRequest.user_id == user.id, condition)
    ).first()
    if row is None:
        raise not_found("Request")
    return RequestDetail.model_validate(row[0]).model_copy(update={"project_name": row[1]})

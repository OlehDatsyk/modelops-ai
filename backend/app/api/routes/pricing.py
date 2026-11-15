"""Model pricing: shared reference catalogue (read-only) and per-account overrides."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import AppError, not_found
from app.db.session import get_db
from app.models import ModelPricing, User
from app.providers.base import Usage
from app.schemas.resources import CostPreviewOut, PricingIn, PricingOut, PricingUpdate
from app.services.pricing import estimate_cost, resolve_pricing

router = APIRouter(prefix="/pricing", tags=["pricing"])


def _out(row: ModelPricing) -> PricingOut:
    return PricingOut(
        id=row.id,
        provider=row.provider,
        model=row.model,
        input_price_per_mtok=row.input_price_per_mtok,
        output_price_per_mtok=row.output_price_per_mtok,
        currency=row.currency,
        source=row.source,
        verified=row.verified,
        notes=row.notes,
        scope="custom" if row.user_id else "catalog",
        updated_at=row.updated_at,
    )


def _owned(db: Session, user: User, pricing_id: uuid.UUID) -> ModelPricing:
    row = db.scalar(select(ModelPricing).where(ModelPricing.id == pricing_id, ModelPricing.user_id == user.id))
    if row is None:
        raise not_found("Custom pricing entry")
    return row


@router.get("", response_model=list[PricingOut])
def list_pricing(
    provider: Literal["openai", "anthropic", "gemini"] | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(ModelPricing).where(or_(ModelPricing.user_id == user.id, ModelPricing.user_id.is_(None)))
    if provider:
        stmt = stmt.where(ModelPricing.provider == provider)
    rows = db.scalars(stmt.order_by(ModelPricing.provider, ModelPricing.model)).all()
    return [_out(r) for r in rows]


@router.post("", response_model=PricingOut, status_code=201)
def create_pricing(body: PricingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = ModelPricing(
        user_id=user.id,
        provider=body.provider,
        model=body.model.strip(),
        input_price_per_mtok=body.input_price_per_mtok,
        output_price_per_mtok=body.output_price_per_mtok,
        source="manual",
        verified=body.verified,
        notes=body.notes,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "duplicate", "You already have a custom price for this provider and model") from None
    return _out(row)


@router.patch("/{pricing_id}", response_model=PricingOut)
def update_pricing(
    pricing_id: uuid.UUID,
    body: PricingUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _owned(db, user, pricing_id)
    for field in ("input_price_per_mtok", "output_price_per_mtok", "verified", "notes"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    db.commit()
    return _out(row)


@router.delete("/{pricing_id}", status_code=204)
def delete_pricing(pricing_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _owned(db, user, pricing_id)
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.get("/preview", response_model=CostPreviewOut)
def preview_cost(
    provider: Literal["openai", "anthropic", "gemini"],
    model: str = Query(min_length=1, max_length=120),
    input_tokens: int = Query(default=1000, ge=0, le=10**9),
    output_tokens: int = Query(default=1000, ge=0, le=10**9),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Show which pricing entry would apply to a model and the resulting estimate."""
    pricing = resolve_pricing(db, user.id, provider, model)
    cost = estimate_cost(Usage(input_tokens, output_tokens), pricing)
    return CostPreviewOut(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        matched_pricing=_out(pricing) if pricing else None,
        input_cost_usd=cost.input_cost,
        output_cost_usd=cost.output_cost,
        total_cost_usd=cost.total_cost,
        status=cost.status,
    )

"""Model pricing resolution and cost estimation."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import ModelPricing
from app.providers.base import Usage

ONE_MILLION = Decimal(1_000_000)
_COST_QUANTUM = Decimal("0.00000001")

# A pricing entry for "gpt-4o" also applies to a dated/pinned variant like "gpt-4o-2024-08-06",
# but never to a different model family such as "gpt-4o-mini". Only these suffixes are accepted.
_VERSION_SUFFIX = re.compile(
    r"^-(\d{8}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}|\d{3}|latest|preview(-[\w.\-]+)?|exp(-[\w.\-]+)?)$"
)


@dataclass
class CostEstimate:
    pricing: ModelPricing | None
    input_cost: Decimal | None
    output_cost: Decimal | None
    total_cost: Decimal | None

    @property
    def status(self) -> str:
        return "estimated" if self.total_cost is not None else "unknown"


def _matches(entry_model: str, model: str) -> bool:
    if entry_model == model:
        return True
    return model.startswith(entry_model) and bool(_VERSION_SUFFIX.match(model[len(entry_model) :]))


def resolve_pricing(db: Session, user_id: uuid.UUID, provider: str, model: str) -> ModelPricing | None:
    """User overrides win over the shared catalogue; exact matches win over version-suffix matches."""
    model = (model or "").strip().removeprefix("models/")
    if not model:
        return None
    rows = db.scalars(
        select(ModelPricing).where(
            ModelPricing.provider == provider,
            or_(ModelPricing.user_id == user_id, ModelPricing.user_id.is_(None)),
        )
    ).all()
    candidates = [r for r in rows if _matches(r.model, model)]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r.user_id is not None, r.model == model, len(r.model)), reverse=True)
    return candidates[0]


def estimate_cost(usage: Usage, pricing: ModelPricing | None) -> CostEstimate:
    if pricing is None:
        return CostEstimate(None, None, None, None)
    input_cost = (Decimal(usage.input_tokens) * pricing.input_price_per_mtok / ONE_MILLION).quantize(
        _COST_QUANTUM, ROUND_HALF_UP
    )
    output_cost = (Decimal(usage.output_tokens) * pricing.output_price_per_mtok / ONE_MILLION).quantize(
        _COST_QUANTUM, ROUND_HALF_UP
    )
    return CostEstimate(pricing, input_cost, output_cost, input_cost + output_cost)


# --- Reference catalogue ------------------------------------------------------------------
# Standard-tier list prices in USD per 1M tokens, recorded for convenience. They are seeded as
# UNVERIFIED reference values: confirm them on each provider's pricing page (or override them per
# account in the Pricing screen). Long-context, batch, cached-input and regional prices are not modelled.
CATALOG_NOTE = "Reference list price (standard tier). Not verified — confirm on the provider's pricing page."

REFERENCE_PRICES: list[tuple[str, str, str, str]] = [
    # provider, model, input $/1M, output $/1M
    ("openai", "gpt-5", "1.25", "10.00"),
    ("openai", "gpt-5-mini", "0.25", "2.00"),
    ("openai", "gpt-5-nano", "0.05", "0.40"),
    ("openai", "gpt-4.1", "2.00", "8.00"),
    ("openai", "gpt-4.1-mini", "0.40", "1.60"),
    ("openai", "gpt-4.1-nano", "0.10", "0.40"),
    ("openai", "gpt-4o", "2.50", "10.00"),
    ("openai", "gpt-4o-mini", "0.15", "0.60"),
    ("openai", "o3", "2.00", "8.00"),
    ("openai", "o4-mini", "1.10", "4.40"),
    ("openai", "gpt-3.5-turbo", "0.50", "1.50"),
    ("anthropic", "claude-opus-4-5", "5.00", "25.00"),
    ("anthropic", "claude-opus-4-1", "15.00", "75.00"),
    ("anthropic", "claude-opus-4", "15.00", "75.00"),
    ("anthropic", "claude-sonnet-4-5", "3.00", "15.00"),
    ("anthropic", "claude-sonnet-4", "3.00", "15.00"),
    ("anthropic", "claude-3-7-sonnet", "3.00", "15.00"),
    ("anthropic", "claude-haiku-4-5", "1.00", "5.00"),
    ("anthropic", "claude-3-5-haiku", "0.80", "4.00"),
    ("anthropic", "claude-3-haiku", "0.25", "1.25"),
    ("gemini", "gemini-2.5-pro", "1.25", "10.00"),
    ("gemini", "gemini-2.5-flash", "0.30", "2.50"),
    ("gemini", "gemini-2.5-flash-lite", "0.10", "0.40"),
    ("gemini", "gemini-2.0-flash", "0.10", "0.40"),
    ("gemini", "gemini-2.0-flash-lite", "0.075", "0.30"),
]


def seed_reference_pricing(db: Session) -> int:
    """Insert missing catalogue rows. Existing rows are never overwritten. Returns rows inserted."""
    existing = {
        (p, m)
        for p, m in db.execute(select(ModelPricing.provider, ModelPricing.model).where(ModelPricing.user_id.is_(None)))
    }
    inserted = 0
    for provider, model, input_price, output_price in REFERENCE_PRICES:
        if (provider, model) in existing:
            continue
        db.add(
            ModelPricing(
                user_id=None,
                provider=provider,
                model=model,
                input_price_per_mtok=Decimal(input_price),
                output_price_per_mtok=Decimal(output_price),
                source="seed",
                verified=False,
                notes=CATALOG_NOTE,
            )
        )
        inserted += 1
    db.commit()
    return inserted

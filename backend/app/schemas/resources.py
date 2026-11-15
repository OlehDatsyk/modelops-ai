"""Request/response schemas for providers, projects, pricing, budgets, alerts and notifications."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderName = Literal["openai", "anthropic", "gemini"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Providers --------------------------------------------------------------------------
class CredentialUpsert(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)
    validate_now: bool = True

    @field_validator("api_key")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if any(c.isspace() for c in v):
            raise ValueError("API key must not contain whitespace")
        return v


class CredentialOut(ORM):
    id: uuid.UUID
    provider: str
    key_hint: str
    status: str
    status_message: str
    available_models: list[str]
    last_validated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProviderStatusOut(BaseModel):
    provider: str
    display_name: str
    configured: bool
    credential: CredentialOut | None


# --- Projects ---------------------------------------------------------------------------
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    allowed_providers: list[ProviderName] = Field(default_factory=lambda: ["openai", "anthropic", "gemini"])

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v

    @field_validator("allowed_providers")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        return sorted(set(v))


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    allowed_providers: list[ProviderName] | None = None

    @field_validator("allowed_providers")
    @classmethod
    def _dedupe(cls, v: list[str] | None) -> list[str] | None:
        return sorted(set(v)) if v is not None else None


class ApiKeyOut(ORM):
    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="The full key. Shown once; only a hash is stored.")


class ApiKeyCreate(BaseModel):
    name: str = Field(default="Default key", min_length=1, max_length=100)


class ProjectStats(BaseModel):
    requests_30d: int
    errors_30d: int
    tokens_30d: int
    cost_30d_usd: float
    last_request_at: datetime | None


class ProjectOut(ORM):
    id: uuid.UUID
    name: str
    description: str
    allowed_providers: list[str]
    created_at: datetime
    updated_at: datetime
    active_keys: int = 0
    stats: ProjectStats | None = None


# --- Pricing ----------------------------------------------------------------------------
class PricingIn(BaseModel):
    provider: ProviderName
    model: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/\-]*$")
    input_price_per_mtok: Decimal = Field(ge=0, le=100000, max_digits=14, decimal_places=6)
    output_price_per_mtok: Decimal = Field(ge=0, le=100000, max_digits=14, decimal_places=6)
    verified: bool = False
    notes: str = Field(default="", max_length=300)


class PricingUpdate(BaseModel):
    input_price_per_mtok: Decimal | None = Field(default=None, ge=0, le=100000, max_digits=14, decimal_places=6)
    output_price_per_mtok: Decimal | None = Field(default=None, ge=0, le=100000, max_digits=14, decimal_places=6)
    verified: bool | None = None
    notes: str | None = Field(default=None, max_length=300)


class PricingOut(ORM):
    id: uuid.UUID
    provider: str
    model: str
    input_price_per_mtok: Decimal
    output_price_per_mtok: Decimal
    currency: str
    source: str
    verified: bool
    notes: str
    scope: Literal["catalog", "custom"]
    updated_at: datetime


class CostPreviewOut(BaseModel):
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    matched_pricing: PricingOut | None
    input_cost_usd: Decimal | None
    output_cost_usd: Decimal | None
    total_cost_usd: Decimal | None
    status: str


# --- Budgets & alerts -------------------------------------------------------------------
class BudgetIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    project_id: uuid.UUID | None = None
    period: Literal["daily", "monthly"]
    limit_usd: Decimal = Field(gt=0, le=10_000_000, max_digits=14, decimal_places=4)
    warning_thresholds: list[int] = Field(default_factory=lambda: [50, 80, 100])
    enforce_limit: bool = False
    enabled: bool = True

    @field_validator("warning_thresholds")
    @classmethod
    def _thresholds(cls, v: list[int]) -> list[int]:
        if not v or len(v) > 10 or any(t < 1 or t > 500 for t in v):
            raise ValueError("Provide 1-10 thresholds between 1 and 500 (percent)")
        return sorted(set(v))


class BudgetOut(ORM):
    id: uuid.UUID
    name: str
    project_id: uuid.UUID | None
    period: str
    limit_usd: Decimal
    warning_thresholds: list[int]
    enforce_limit: bool
    enabled: bool
    created_at: datetime
    current_spend_usd: Decimal = Decimal(0)
    percent_used: float = 0.0
    period_start: str = ""


class AlertRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    project_id: uuid.UUID | None = None
    metric: Literal["error_rate", "request_volume", "token_usage", "spend"]
    threshold: Decimal = Field(gt=0, le=10**12, max_digits=18, decimal_places=4)
    window_minutes: int = Field(default=60, ge=5, le=10080)
    min_requests: int = Field(default=10, ge=1, le=100000)
    cooldown_minutes: int = Field(default=60, ge=5, le=10080)
    enabled: bool = True


class AlertRuleOut(ORM):
    id: uuid.UUID
    name: str
    project_id: uuid.UUID | None
    metric: str
    threshold: Decimal
    window_minutes: int
    min_requests: int
    cooldown_minutes: int
    enabled: bool
    last_triggered_at: datetime | None
    created_at: datetime


class NotificationOut(ORM):
    id: uuid.UUID
    kind: str
    severity: str
    title: str
    message: str
    data: dict
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int
    total: int


# --- Requests ---------------------------------------------------------------------------
class RequestOut(ORM):
    id: uuid.UUID
    request_id: str
    created_at: datetime
    provider: str
    model: str
    endpoint: str
    project_id: uuid.UUID | None
    project_name: str | None = None
    streamed: bool
    status: str
    http_status: int
    error_type: str | None
    error_message: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    cost_total_usd: Decimal | None
    cost_status: str


class RequestDetail(RequestOut):
    cost_input_usd: Decimal | None
    cost_output_usd: Decimal | None
    pricing_model_key: str | None
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    pricing_verified: bool
    api_key_id: uuid.UUID | None


class RequestPage(BaseModel):
    items: list[RequestOut]
    total: int
    page: int
    page_size: int


# --- Analyst ----------------------------------------------------------------------------
class AnalystAsk(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    conversation_id: uuid.UUID | None = None


class AnalystMessageOut(ORM):
    id: uuid.UUID
    role: str
    content: str
    tool_results: list
    created_at: datetime


class ConversationOut(ORM):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[AnalystMessageOut]


class AnalystStatus(BaseModel):
    configured: bool
    provider: str | None
    model: str | None

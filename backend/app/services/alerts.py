"""Budgets, alert-rule evaluation and in-app notifications."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import AlertRule, ApiRequest, Budget, Notification, UsageDaily

logger = logging.getLogger("modelops.alerts")


def period_start(period: str, now: datetime | None = None) -> date:
    today = (now or utcnow()).date()
    return today.replace(day=1) if period == "monthly" else today


def budget_spend(db: Session, budget: Budget, now: datetime | None = None) -> Decimal:
    start = period_start(budget.period, now)
    stmt = select(func.coalesce(func.sum(UsageDaily.cost_usd), 0)).where(
        UsageDaily.user_id == budget.user_id, UsageDaily.day >= start
    )
    if budget.project_id:
        stmt = stmt.where(UsageDaily.project_id == budget.project_id)
    return Decimal(db.scalar(stmt) or 0)


def blocking_budget(db: Session, user_id: uuid.UUID, project_id: uuid.UUID | None) -> Budget | None:
    """Return an enforced budget whose limit has been reached for this request's scope, if any."""
    budgets = db.scalars(
        select(Budget).where(
            Budget.user_id == user_id,
            Budget.enabled.is_(True),
            Budget.enforce_limit.is_(True),
            or_(Budget.project_id.is_(None), Budget.project_id == project_id),
        )
    ).all()
    for budget in budgets:
        if budget_spend(db, budget) >= budget.limit_usd:
            return budget
    return None


def create_notification(
    db: Session,
    user_id: uuid.UUID,
    *,
    kind: str,
    severity: str,
    title: str,
    message: str,
    data: dict | None = None,
    dedupe_key: str | None = None,
) -> Notification | None:
    """Create a notification; returns None if one with the same dedupe key already exists."""
    if dedupe_key and db.scalar(
        select(Notification.id).where(Notification.user_id == user_id, Notification.dedupe_key == dedupe_key)
    ):
        return None
    note = Notification(
        user_id=user_id,
        kind=kind,
        severity=severity,
        title=title[:200],
        message=message[:1000],
        data=data or {},
        dedupe_key=dedupe_key,
    )
    db.add(note)
    try:
        db.commit()
    except IntegrityError:  # concurrent duplicate — the unique constraint is the source of truth
        db.rollback()
        return None
    return note


def evaluate_budgets(db: Session, user_id: uuid.UUID, project_id: uuid.UUID | None) -> int:
    created = 0
    budgets = db.scalars(
        select(Budget).where(
            Budget.user_id == user_id,
            Budget.enabled.is_(True),
            or_(Budget.project_id.is_(None), Budget.project_id == project_id),
        )
    ).all()
    for budget in budgets:
        spend = budget_spend(db, budget)
        if budget.limit_usd <= 0:
            continue
        pct = spend / budget.limit_usd * 100
        crossed = sorted(t for t in budget.warning_thresholds if pct >= Decimal(str(t)))
        if not crossed:
            continue
        threshold = crossed[-1]
        start = period_start(budget.period)
        severity = "critical" if threshold >= 100 else "warning"
        note = create_notification(
            db,
            user_id,
            kind="budget",
            severity=severity,
            title=f"Budget '{budget.name}' reached {threshold}%",
            message=(
                f"Estimated {budget.period} spend is ${spend:.4f} of the ${budget.limit_usd:.2f} limit "
                f"({pct:.1f}%). Period started {start.isoformat()} (UTC)."
                + (" Gateway requests in this scope are now blocked." if budget.enforce_limit and pct >= 100 else "")
            ),
            data={"budget_id": str(budget.id), "spend_usd": str(spend), "threshold": threshold},
            dedupe_key=f"budget:{budget.id}:{start.isoformat()}:{threshold}",
        )
        created += 1 if note else 0
    return created


def rule_value(db: Session, rule: AlertRule, now: datetime) -> tuple[Decimal | None, int]:
    """Current metric value for a rule over its window. Returns (value, request_count)."""
    since = now - timedelta(minutes=rule.window_minutes)
    stmt = select(
        func.count(ApiRequest.id),
        func.coalesce(func.sum(case((ApiRequest.status == "error", 1), else_=0)), 0),
        func.coalesce(func.sum(ApiRequest.total_tokens), 0),
        func.coalesce(func.sum(ApiRequest.cost_total_usd), 0),
    ).where(ApiRequest.user_id == rule.user_id, ApiRequest.created_at >= since)
    if rule.project_id:
        stmt = stmt.where(ApiRequest.project_id == rule.project_id)
    total, errors, tokens, spend = db.execute(stmt).one()
    if rule.metric == "error_rate":
        if total < max(rule.min_requests, 1):
            return None, total
        return Decimal(errors) / Decimal(total) * 100, total
    if rule.metric == "request_volume":
        return Decimal(total), total
    if rule.metric == "token_usage":
        return Decimal(tokens), total
    if rule.metric == "spend":
        return Decimal(spend), total
    return None, total


_METRIC_LABEL = {
    "error_rate": ("Error rate", "%"),
    "request_volume": ("Request volume", " requests"),
    "token_usage": ("Token usage", " tokens"),
    "spend": ("Estimated spend", " USD"),
}


def evaluate_rules(db: Session, user_id: uuid.UUID, project_id: uuid.UUID | None) -> int:
    now = utcnow()
    created = 0
    rules = db.scalars(
        select(AlertRule).where(
            AlertRule.user_id == user_id,
            AlertRule.enabled.is_(True),
            or_(AlertRule.project_id.is_(None), AlertRule.project_id == project_id),
        )
    ).all()
    for rule in rules:
        if rule.last_triggered_at and now - rule.last_triggered_at < timedelta(minutes=rule.cooldown_minutes):
            continue
        value, total = rule_value(db, rule, now)
        if value is None or value < rule.threshold:
            continue
        label, unit = _METRIC_LABEL.get(rule.metric, (rule.metric, ""))
        rule.last_triggered_at = now
        db.commit()
        note = create_notification(
            db,
            user_id,
            kind="alert",
            severity="critical" if rule.metric == "error_rate" else "warning",
            title=f"Alert '{rule.name}' triggered",
            message=(
                f"{label} over the last {rule.window_minutes} min is {value:.2f}{unit} "
                f"(threshold {rule.threshold:.2f}{unit}, {total} requests)."
            ),
            data={"rule_id": str(rule.id), "value": str(value), "metric": rule.metric},
            dedupe_key=f"rule:{rule.id}:{now.isoformat(timespec='minutes')}",
        )
        created += 1 if note else 0
    return created


def evaluate_after_request(user_id: uuid.UUID, project_id: uuid.UUID | None) -> None:
    """Background task run after each gateway request. Failures are logged, never raised."""
    from app.db.session import get_sessionmaker

    session = get_sessionmaker()()
    try:
        evaluate_budgets(session, user_id, project_id)
        evaluate_rules(session, user_id, project_id)
    except Exception:
        session.rollback()
        logger.exception("Alert evaluation failed")
    finally:
        session.close()

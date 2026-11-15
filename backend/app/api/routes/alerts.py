"""Budgets, alert rules and the in-app notification centre."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.projects import get_owned_project
from app.core.errors import AppError, not_found
from app.db.base import utcnow
from app.db.session import get_db
from app.models import AlertRule, Budget, Notification, User
from app.schemas.resources import (
    AlertRuleIn,
    AlertRuleOut,
    BudgetIn,
    BudgetOut,
    NotificationList,
    NotificationOut,
)
from app.services.alerts import budget_spend, evaluate_budgets, period_start

router = APIRouter(tags=["alerts"])

MAX_ITEMS = 50


def _budget_out(db: Session, budget: Budget) -> BudgetOut:
    spend = budget_spend(db, budget)
    pct = float(spend / budget.limit_usd * 100) if budget.limit_usd else 0.0
    return BudgetOut.model_validate(budget).model_copy(
        update={
            "current_spend_usd": spend,
            "percent_used": round(pct, 2),
            "period_start": period_start(budget.period).isoformat(),
        }
    )


def _owned(db: Session, model, user: User, item_id: uuid.UUID):
    item = db.scalar(select(model).where(model.id == item_id, model.user_id == user.id))
    if item is None:
        raise not_found(model.__name__)
    return item


# --- Budgets ---------------------------------------------------------------------------
@router.get("/budgets", response_model=list[BudgetOut])
def list_budgets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    budgets = db.scalars(select(Budget).where(Budget.user_id == user.id).order_by(Budget.created_at)).all()
    return [_budget_out(db, b) for b in budgets]


@router.post("/budgets", response_model=BudgetOut, status_code=201)
def create_budget(body: BudgetIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.project_id:
        get_owned_project(db, user, body.project_id)
    if db.scalar(select(func.count(Budget.id)).where(Budget.user_id == user.id)) >= MAX_ITEMS:
        raise AppError(400, "limit_reached", f"At most {MAX_ITEMS} budgets per account")
    budget = Budget(user_id=user.id, **body.model_dump())
    db.add(budget)
    db.commit()
    evaluate_budgets(db, user.id, budget.project_id)
    return _budget_out(db, budget)


@router.put("/budgets/{budget_id}", response_model=BudgetOut)
def update_budget(
    budget_id: uuid.UUID,
    body: BudgetIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    budget = _owned(db, Budget, user, budget_id)
    if body.project_id:
        get_owned_project(db, user, body.project_id)
    for key, value in body.model_dump().items():
        setattr(budget, key, value)
    db.commit()
    evaluate_budgets(db, user.id, budget.project_id)
    return _budget_out(db, budget)


@router.delete("/budgets/{budget_id}", status_code=204)
def delete_budget(budget_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_owned(db, Budget, user, budget_id))
    db.commit()
    return Response(status_code=204)


# --- Alert rules ------------------------------------------------------------------------
@router.get("/alert-rules", response_model=list[AlertRuleOut])
def list_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(AlertRule).where(AlertRule.user_id == user.id).order_by(AlertRule.created_at)).all()


@router.post("/alert-rules", response_model=AlertRuleOut, status_code=201)
def create_rule(body: AlertRuleIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.project_id:
        get_owned_project(db, user, body.project_id)
    if db.scalar(select(func.count(AlertRule.id)).where(AlertRule.user_id == user.id)) >= MAX_ITEMS:
        raise AppError(400, "limit_reached", f"At most {MAX_ITEMS} alert rules per account")
    rule = AlertRule(user_id=user.id, **body.model_dump())
    db.add(rule)
    db.commit()
    return rule


@router.put("/alert-rules/{rule_id}", response_model=AlertRuleOut)
def update_rule(
    rule_id: uuid.UUID,
    body: AlertRuleIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rule = _owned(db, AlertRule, user, rule_id)
    if body.project_id:
        get_owned_project(db, user, body.project_id)
    for key, value in body.model_dump().items():
        setattr(rule, key, value)
    db.commit()
    return rule


@router.delete("/alert-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_owned(db, AlertRule, user, rule_id))
    db.commit()
    return Response(status_code=204)


# --- Notifications ----------------------------------------------------------------------
@router.get("/notifications", response_model=NotificationList)
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        base = base.where(Notification.read_at.is_(None))
    items = db.scalars(base.order_by(Notification.created_at.desc()).offset(offset).limit(limit)).all()
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    unread = (
        db.scalar(
            select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
        or 0
    )
    return NotificationList(items=[NotificationOut.model_validate(n) for n in items], unread=unread, total=total)


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    note = _owned(db, Notification, user, notification_id)
    note.read_at = note.read_at or utcnow()
    db.commit()
    return note


@router.post("/notifications/read-all", status_code=204)
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()
    return Response(status_code=204)


@router.delete("/notifications/{notification_id}", status_code=204)
def delete_notification(
    notification_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    db.delete(_owned(db, Notification, user, notification_id))
    db.commit()
    return Response(status_code=204)

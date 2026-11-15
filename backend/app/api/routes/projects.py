"""Monitoring projects and their gateway API keys."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import AppError, not_found
from app.core.security import generate_project_key, project_key_display_prefix, sha256_hex
from app.db.base import utcnow
from app.db.session import get_db
from app.models import ApiRequest, Project, ProjectApiKey, User
from app.schemas.resources import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    ProjectCreate,
    ProjectOut,
    ProjectStats,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])

MAX_ACTIVE_KEYS = 20


def get_owned_project(db: Session, user: User, project_id: uuid.UUID) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
    if project is None:
        raise not_found("Project")
    return project


def _stats(db: Session, user: User, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, ProjectStats]:
    if not project_ids:
        return {}
    since = utcnow() - timedelta(days=30)
    rows = db.execute(
        select(
            ApiRequest.project_id,
            func.count(ApiRequest.id),
            func.coalesce(func.sum(case((ApiRequest.status == "error", 1), else_=0)), 0),
            func.coalesce(func.sum(ApiRequest.total_tokens), 0),
            func.coalesce(func.sum(ApiRequest.cost_total_usd), 0),
            func.max(ApiRequest.created_at),
        )
        .where(
            ApiRequest.user_id == user.id,
            ApiRequest.project_id.in_(project_ids),
            ApiRequest.created_at >= since,
        )
        .group_by(ApiRequest.project_id)
    ).all()
    stats = {
        pid: ProjectStats(
            requests_30d=int(n),
            errors_30d=int(e),
            tokens_30d=int(t),
            cost_30d_usd=float(c),
            last_request_at=last,
        )
        for pid, n, e, t, c, last in rows
    }
    empty = ProjectStats(requests_30d=0, errors_30d=0, tokens_30d=0, cost_30d_usd=0.0, last_request_at=None)
    return {pid: stats.get(pid, empty) for pid in project_ids}


def _active_key_counts(db: Session, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not project_ids:
        return {}
    rows = db.execute(
        select(ProjectApiKey.project_id, func.count(ProjectApiKey.id))
        .where(ProjectApiKey.project_id.in_(project_ids), ProjectApiKey.revoked_at.is_(None))
        .group_by(ProjectApiKey.project_id)
    ).all()
    return {pid: int(n) for pid, n in rows}


def _out(project: Project, keys: int, stats: ProjectStats | None) -> ProjectOut:
    return ProjectOut.model_validate(project).model_copy(update={"active_keys": keys, "stats": stats})


@router.get("", response_model=list[ProjectOut])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).where(Project.user_id == user.id).order_by(Project.created_at)).all()
    ids = [p.id for p in projects]
    stats, keys = _stats(db, user, ids), _active_key_counts(db, ids)
    return [_out(p, keys.get(p.id, 0), stats.get(p.id)) for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.scalar(select(func.count(Project.id)).where(Project.user_id == user.id)) >= 100:
        raise AppError(400, "limit_reached", "Project limit reached (100)")
    project = Project(
        user_id=user.id,
        name=body.name,
        description=body.description,
        allowed_providers=body.allowed_providers,
    )
    db.add(project)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "name_taken", "A project with this name already exists") from None
    return _out(project, 0, None)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_owned_project(db, user, project_id)
    return _out(
        project,
        _active_key_counts(db, [project.id]).get(project.id, 0),
        _stats(db, user, [project.id])[project.id],
    )


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_owned_project(db, user, project_id)
    if body.name is not None:
        project.name = body.name.strip()
    if body.description is not None:
        project.description = body.description
    if body.allowed_providers is not None:
        project.allowed_providers = body.allowed_providers
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "name_taken", "A project with this name already exists") from None
    return get_project(project_id, user, db)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Deletes the project and its keys. Historical request records are kept (project set to null)."""
    project = get_owned_project(db, user, project_id)
    db.delete(project)
    db.commit()
    return Response(status_code=204)


@router.get("/{project_id}/keys", response_model=list[ApiKeyOut])
def list_keys(project_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_owned_project(db, user, project_id)
    return db.scalars(
        select(ProjectApiKey)
        .where(ProjectApiKey.project_id == project_id, ProjectApiKey.user_id == user.id)
        .order_by(ProjectApiKey.created_at.desc())
    ).all()


@router.post("/{project_id}/keys", response_model=ApiKeyCreated, status_code=201)
def create_key(
    project_id: uuid.UUID,
    body: ApiKeyCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_project(db, user, project_id)
    active = db.scalar(
        select(func.count(ProjectApiKey.id)).where(
            ProjectApiKey.project_id == project_id, ProjectApiKey.revoked_at.is_(None)
        )
    )
    if active >= MAX_ACTIVE_KEYS:
        raise AppError(400, "limit_reached", f"A project can have at most {MAX_ACTIVE_KEYS} active keys")
    raw = generate_project_key()
    key = ProjectApiKey(
        project_id=project_id,
        user_id=user.id,
        name=body.name.strip(),
        prefix=project_key_display_prefix(raw),
        key_hash=sha256_hex(raw),
    )
    db.add(key)
    db.commit()
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), key=raw)


@router.post("/{project_id}/keys/{key_id}/revoke", response_model=ApiKeyOut)
def revoke_key(
    project_id: uuid.UUID,
    key_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_project(db, user, project_id)
    key = db.scalar(
        select(ProjectApiKey).where(
            ProjectApiKey.id == key_id,
            ProjectApiKey.project_id == project_id,
            ProjectApiKey.user_id == user.id,
        )
    )
    if key is None:
        raise not_found("API key")
    key.revoked_at = key.revoked_at or utcnow()
    db.commit()
    return key

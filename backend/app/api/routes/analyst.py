"""AI Analyst conversations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import not_found
from app.db.base import utcnow
from app.db.session import get_db
from app.models import AnalystConversation, AnalystMessage, User
from app.schemas.resources import (
    AnalystAsk,
    AnalystMessageOut,
    AnalystStatus,
    ConversationDetail,
    ConversationOut,
)
from app.services import analyst
from app.services.analyst_tools import ToolContext, account_has_data

router = APIRouter(prefix="/analyst", tags=["analyst"])

NO_DATA_ANSWER = (
    "There is no request data in this account yet, so there is nothing to analyse. "
    "Create a project, add a provider key and send a request through the gateway — "
    "once requests are recorded I can explain costs, failures, token usage and trends."
)


def _owned(db: Session, user: User, conversation_id: uuid.UUID) -> AnalystConversation:
    conv = db.scalar(
        select(AnalystConversation).where(
            AnalystConversation.id == conversation_id, AnalystConversation.user_id == user.id
        )
    )
    if conv is None:
        raise not_found("Conversation")
    return conv


@router.get("/status", response_model=AnalystStatus)
def status(_: User = Depends(get_current_user)):
    s = get_settings()
    return AnalystStatus(
        configured=s.analyst_configured,
        provider=s.ai_analyst_provider or None if s.analyst_configured else None,
        model=s.ai_analyst_model or None if s.analyst_configured else None,
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(AnalystConversation)
        .where(AnalystConversation.user_id == user.id)
        .order_by(AnalystConversation.updated_at.desc())
        .limit(100)
    ).all()


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _owned(db, user, conversation_id)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    db.delete(_owned(db, user, conversation_id))
    db.commit()
    return Response(status_code=204)


@router.post("/ask")
async def ask(body: AnalystAsk, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit.enforce(f"analyst:{user.id}", 10)

    def prepare() -> tuple[AnalystConversation, list[dict[str, str]], bool]:
        if body.conversation_id:
            conv = _owned(db, user, body.conversation_id)
        else:
            conv = AnalystConversation(user_id=user.id, title=body.question.strip()[:80])
            db.add(conv)
            db.commit()
        history = [
            {"role": m.role, "content": m.content}
            for m in db.scalars(
                select(AnalystMessage)
                .where(AnalystMessage.conversation_id == conv.id)
                .order_by(AnalystMessage.created_at.desc())
                .limit(10)
            ).all()[::-1]
        ]
        return conv, history, account_has_data(db, user.id)

    conv, history, has_data = await run_in_threadpool(prepare)
    if has_data:
        result = await analyst.ask(ToolContext(db, user.id), history, body.question.strip())
        answer, evidence = result.answer, result.tool_results
    else:
        answer, evidence = NO_DATA_ANSWER, []

    def save() -> tuple[AnalystMessage, AnalystMessage]:
        now = utcnow()
        q = AnalystMessage(conversation_id=conv.id, role="user", content=body.question.strip(), created_at=now)
        a = AnalystMessage(conversation_id=conv.id, role="assistant", content=answer, tool_results=evidence)
        conv.updated_at = utcnow()
        db.add_all([q, a])
        db.commit()
        return q, a

    q, a = await run_in_threadpool(save)
    return {
        "conversation": ConversationOut.model_validate(conv),
        "question": AnalystMessageOut.model_validate(q),
        "answer": AnalystMessageOut.model_validate(a),
    }

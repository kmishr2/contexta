import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.analytics.execute import execute_metric
from app.analytics.intent import interpret
from app.api.connections import metadata_session, owner
from app.api.onboarding import current_catalog, fail, latest_snapshot, lock_connection
from app.catalog.models import Chat, MetricRevision, QueryRun
from app.core.settings import Settings
from app.onboarding.metrics import Definition
from app.sources.postgres.discovery import SourcePolicyError

router = APIRouter()


class ChatMessage(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.post('/connections/{connection_id}/chats', status_code=201)
def create_chat(connection_id: uuid.UUID, session: Annotated[Session, Depends(metadata_session)]):
    lock_connection(session, connection_id)
    chat = Chat(connection_id=connection_id)
    session.add(chat)
    session.commit()
    return {'id': chat.id, 'connection_id': chat.connection_id}


@router.post('/chats/{chat_id}/messages')
def message(chat_id: uuid.UUID, body: ChatMessage, settings: Annotated[Settings, Depends(owner)], session: Annotated[Session, Depends(metadata_session)]):
    existing = session.get(Chat, chat_id)
    if existing is None:
        fail('chat_not_found', 'Chat not found', 404)
    record = lock_connection(session, existing.connection_id)
    chat = session.scalar(select(Chat).where(Chat.id == chat_id).with_for_update().execution_options(populate_existing=True))
    if chat is None:
        fail('chat_not_found', 'Chat not found', 404)
    result = interpret(body.message, chat.last_intent, chat.pending_metric)
    if result['kind'] == 'unsupported':
        return {'type': 'unsupported', 'message': result['message']}
    metric_id = result.get('metric_id') if result['kind'] == 'clarify' else result['intent'].metric_id
    if metric_id:
        metric = session.scalar(select(MetricRevision).where(MetricRevision.connection_id == record.id, MetricRevision.metric_id == metric_id, MetricRevision.state == 'ready'))
        if metric is None:
            chat.pending_metric = None
            session.commit()
            return {'type': 'unsupported', 'message': 'That metric is not available for this connection.'}
        current_catalog(session, metric)
    if result['kind'] == 'clarify':
        chat.pending_metric = metric_id
        session.commit()
        return {'type': 'clarification', 'message': result['message']}
    intent = result['intent']
    try:
        execution = execute_metric(record, settings, Definition.model_validate(metric.definition), intent)
    except (SQLAlchemyError, SourcePolicyError):
        fail('source_unavailable', 'The source query could not be completed', 503)
    snapshot = latest_snapshot(session, record.id)
    effective = intent.model_dump(mode='json')
    run = QueryRun(chat_id=chat.id, metric_revision_id=metric.id, snapshot_id=snapshot.id, intent=effective, outcome=execution['data_status'])
    chat.last_intent = effective
    chat.pending_metric = None
    session.add(run)
    session.commit()
    return {'type': 'answer', 'metric': {'id': metric.metric_id, 'revision': metric.revision, 'definition': metric.definition},
            'date_scope': {'start': effective['start'], 'end_exclusive': effective['end']},
            'columns': ['value'], 'rows': [[execution['value']]], 'row_count': 1, 'truncated': False,
            'data_status': execution['data_status'], 'sql': execution['sql'], 'query_run_id': run.id,
            'message': 'The requested date window uses an exclusive end date.'}

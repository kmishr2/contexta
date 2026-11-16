import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.connections import get_record, metadata_session, owner
from app.catalog.models import ConnectionRecord, MetricRevision, SchemaSnapshot
from app.core.settings import Settings
from app.onboarding.metrics import Definition, ReferenceCheck, run_check, validate_definition
from app.onboarding.drift import source_changed
from app.onboarding.suggestions import suggest_sources
from app.sources.postgres.discovery import SourcePolicyError

router = APIRouter()


def fail(code, message, status=409):
    raise HTTPException(status, detail={'code': code, 'message': message})


def lock_connection(session, connection_id):
    record = session.scalar(select(ConnectionRecord).where(ConnectionRecord.id == connection_id).with_for_update())
    if record is None:
        fail('connection_not_found', 'Connection not found', 404)
    return record


def latest_snapshot(session, connection_id):
    snapshot = session.scalar(select(SchemaSnapshot).where(SchemaSnapshot.connection_id == connection_id).order_by(SchemaSnapshot.captured_at.desc(), SchemaSnapshot.id.desc()).limit(1))
    if snapshot is None:
        fail('catalog_not_found', 'Discover the connection first', 404)
    return snapshot


def revision_for(session, connection_id, metric_id, revision):
    metric = session.scalar(select(MetricRevision).where(MetricRevision.connection_id == connection_id, MetricRevision.metric_id == metric_id, MetricRevision.revision == revision))
    if metric is None:
        fail('revision_not_found', 'Metric revision not found', 404)
    return metric


def current_catalog(session, metric):
    latest = latest_snapshot(session, metric.connection_id)
    reviewed = session.get(SchemaSnapshot, metric.snapshot_id)
    if source_changed(metric.definition, reviewed.catalog, latest.catalog):
        fail('stale_definition', 'Catalog changed; save and verify a new draft')
    return latest


class Message(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ExpectedRevision(BaseModel):
    revision: int = Field(ge=1)


class Verification(ReferenceCheck):
    revision: int = Field(ge=1)


@router.post('/connections/{connection_id}/onboarding/messages')
def suggest(connection_id: uuid.UUID, body: Message, session: Annotated[Session, Depends(metadata_session)]):
    get_record(session, connection_id)
    snapshot = latest_snapshot(session, connection_id)
    matches = suggest_sources(body.message, snapshot.catalog)
    return {'suggestions': matches, 'question': 'Which source represents the metric, and which date and amount columns should it use?', 'note': 'Suggestions are unapproved; confirm all business rules before publication.'}


@router.put('/connections/{connection_id}/metrics/{metric_id}/draft', status_code=201)
def save(connection_id: uuid.UUID, metric_id: str, body: Definition, session: Annotated[Session, Depends(metadata_session)]):
    if not metric_id or len(metric_id) > 80 or not all(c.isascii() and (c.isalnum() or c in '_-') for c in metric_id):
        fail('invalid_metric_id', 'Use letters, digits, underscores, or hyphens for the metric ID', 422)
    lock_connection(session, connection_id)
    snapshot = latest_snapshot(session, connection_id)
    try:
        validate_definition(body, snapshot.catalog)
    except ValueError as exc:
        fail('invalid_definition', str(exc), 422)
    last = session.scalar(select(MetricRevision.revision).where(MetricRevision.connection_id == connection_id, MetricRevision.metric_id == metric_id).order_by(MetricRevision.revision.desc()).limit(1)) or 0
    metric = MetricRevision(connection_id=connection_id, metric_id=metric_id, revision=last + 1, snapshot_id=snapshot.id, definition=body.model_dump(), state='draft')
    session.add(metric)
    session.commit()
    return {'metric_id': metric_id, 'revision': metric.revision, 'state': metric.state, 'definition': metric.definition}


@router.post('/connections/{connection_id}/metrics/{metric_id}/verify')
def verify(connection_id: uuid.UUID, metric_id: str, body: Verification, settings: Annotated[Settings, Depends(owner)], session: Annotated[Session, Depends(metadata_session)]):
    record = lock_connection(session, connection_id)
    metric = revision_for(session, connection_id, metric_id, body.revision)
    if metric.state not in ('draft', 'in_review'):
        fail('invalid_state', 'Only drafts can be verified')
    current_catalog(session, metric)
    try:
        result = run_check(record, settings, Definition.model_validate(metric.definition), body)
    except (SQLAlchemyError, SourcePolicyError):
        fail('source_unavailable', 'Source query failed', 503)
    metric.check_result = result
    metric.state = 'in_review'
    session.commit()
    return {'revision': metric.revision, 'state': metric.state, 'check': result}


@router.post('/connections/{connection_id}/metrics/{metric_id}/publish')
def publish(connection_id: uuid.UUID, metric_id: str, body: ExpectedRevision, session: Annotated[Session, Depends(metadata_session)]):
    lock_connection(session, connection_id)
    metric = revision_for(session, connection_id, metric_id, body.revision)
    latest = session.scalar(select(MetricRevision.revision).where(MetricRevision.connection_id == connection_id, MetricRevision.metric_id == metric_id).order_by(MetricRevision.revision.desc()).limit(1))
    if latest != body.revision or metric.state != 'in_review' or not metric.check_result or not metric.check_result['passed']:
        fail('not_publishable', 'The latest revision must pass its reference check')
    current_catalog(session, metric)
    for prior in session.scalars(select(MetricRevision).where(MetricRevision.connection_id == connection_id, MetricRevision.metric_id == metric_id, MetricRevision.state == 'ready')):
        prior.state = 'superseded'
    metric.state = 'ready'
    session.commit()
    return {'metric_id': metric_id, 'revision': metric.revision, 'state': metric.state, 'definition': metric.definition}


@router.get('/connections/{connection_id}/metrics')
def list_revisions(connection_id: uuid.UUID, session: Annotated[Session, Depends(metadata_session)]):
    get_record(session, connection_id)
    snapshot = latest_snapshot(session, connection_id)
    rows = session.execute(
        select(MetricRevision, SchemaSnapshot.catalog)
        .join(SchemaSnapshot, MetricRevision.snapshot_id == SchemaSnapshot.id)
        .where(MetricRevision.connection_id == connection_id)
        .order_by(MetricRevision.metric_id, MetricRevision.revision.desc())
        .limit(501)
    ).all()
    return {'revisions': [
        {'metric_id': metric.metric_id, 'revision': metric.revision,
         'name': metric.definition.get('name', metric.metric_id),
         'state': 'stale' if metric.state in ('draft', 'in_review', 'ready') and source_changed(metric.definition, reviewed_catalog, snapshot.catalog) else metric.state}
        for metric, reviewed_catalog in rows[:500]], 'truncated': len(rows) > 500}


@router.get('/connections/{connection_id}/metrics/{metric_id}/revisions/{revision}')
def review(connection_id: uuid.UUID, metric_id: str, revision: int, session: Annotated[Session, Depends(metadata_session)]):
    get_record(session, connection_id)
    metric = revision_for(session, connection_id, metric_id, revision)
    latest = latest_snapshot(session, connection_id)
    reviewed = session.get(SchemaSnapshot, metric.snapshot_id)
    return {'metric_id': metric_id, 'revision': metric.revision, 'state': 'stale' if metric.state in ('draft', 'in_review', 'ready') and source_changed(metric.definition, reviewed.catalog, latest.catalog) else metric.state, 'definition': metric.definition, 'check': metric.check_result}

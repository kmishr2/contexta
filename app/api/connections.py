import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.catalog.models import ConnectionRecord, MetricRevision, SchemaSnapshot
from app.onboarding.drift import source_changed
from app.core.settings import Settings
from app.core.auth import Actor, actor, require_connection, require_owner as owner
from app.sources.postgres.discovery import ScopeAccessError, SourcePolicyError, inspect_source

router = APIRouter()


class ConnectionInput(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    host: str = Field(min_length=1, max_length=253, pattern=r"^[a-zA-Z0-9.:-]+$")
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    credential_ref: str = Field(pattern=r"^CONTEXA_SOURCE_[A-Z0-9_]+$", max_length=128)
    schemas: list[str] = Field(min_length=1, max_length=20)
    # No profiling or external sharing is enabled in Phase 2.
    @field_validator("schemas")
    @classmethod
    def validate_schemas(cls, value):
        if len(set(value)) != len(value) or any(not s or len(s.encode()) > 63 or '\x00' in s or s.startswith('pg_') or s == 'information_schema' for s in value):
            raise ValueError("Schemas must be distinct, valid, non-system names")
        return sorted(value)


def metadata_session(request: Request, principal: Annotated[Actor, Depends(actor)]):
    settings = request.app.state.settings
    if settings.metadata_url is None or not settings.metadata_url.get_secret_value().startswith("postgresql+psycopg://"):
        raise HTTPException(503, detail={"code": "metadata_unavailable", "message": "Metadata store is unavailable"})
    engine = create_engine(settings.metadata_url.get_secret_value(), poolclass=NullPool, hide_parameters=True, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def get_record(session: Session, connection_id: uuid.UUID):
    record = session.get(ConnectionRecord, connection_id)
    if record is None:
        raise HTTPException(404, detail={"code": "connection_not_found", "message": "Connection not found"})
    return record


def safe_source(record, settings, discover):
    try:
        return inspect_source(record, settings, discover=discover)
    except (SourcePolicyError, SQLAlchemyError):
        raise HTTPException(503, detail={"code": "source_unavailable", "message": "Source access or scope verification failed"}) from None


@router.get("/connections")
def list_connections(session: Annotated[Session, Depends(metadata_session)], principal: Annotated[Actor, Depends(actor)]):
    query = select(ConnectionRecord).order_by(ConnectionRecord.label, ConnectionRecord.id)
    if principal.role != 'owner':
        query = query.where(ConnectionRecord.id.in_(principal.connections))
    records = session.scalars(query).all()
    return [{"id": r.id, "label": r.label, **({"schemas": r.schemas} if principal.role == 'owner' else {})} for r in records]


@router.get('/me')
def current_identity(principal: Annotated[Actor, Depends(actor)]):
    return {'id': principal.id, 'role': principal.role}


@router.post("/connections", status_code=201)
def register(body: ConnectionInput, settings: Annotated[Settings, Depends(owner)], session: Annotated[Session, Depends(metadata_session)]):
    if f"{body.host}:{body.port}" not in settings.allowed_destinations:
        raise HTTPException(403, detail={"code": "destination_denied", "message": "Destination is not approved"})
    record = ConnectionRecord(**body.model_dump(), sharing_policy={"profiling": False, "provider_sharing": False})
    session.add(record)
    session.commit()
    return {"id": record.id, "label": record.label, "schemas": record.schemas}


@router.post("/connections/{connection_id}/verify")
def verify(connection_id: uuid.UUID, settings: Annotated[Settings, Depends(owner)], session: Annotated[Session, Depends(metadata_session)]):
    return safe_source(get_record(session, connection_id), settings, False)


@router.post("/connections/{connection_id}/discover")
def discover(connection_id: uuid.UUID, settings: Annotated[Settings, Depends(owner)], session: Annotated[Session, Depends(metadata_session)]):
    record = session.scalar(select(ConnectionRecord).where(ConnectionRecord.id == connection_id).with_for_update())
    if record is None:
        raise HTTPException(404, detail={"code": "connection_not_found", "message": "Connection not found"})
    try:
        catalog, fingerprint = inspect_source(record, settings, discover=True)
    except ScopeAccessError as exc:
        # Schema access is known to be lost. Invalidate definitions in that
        # schema and views, whose dependency graph is not yet available.
        active = session.execute(select(MetricRevision, SchemaSnapshot.catalog)
            .join(SchemaSnapshot, MetricRevision.snapshot_id == SchemaSnapshot.id)
            .where(MetricRevision.connection_id == connection_id,
                   MetricRevision.state.in_(['draft', 'in_review', 'ready']))).all()
        for metric, reviewed in active:
            obj = next((o for o in reviewed.get('objects', []) if o['schema'] == metric.definition.get('schema_name') and o['name'] == metric.definition.get('relation')), None)
            if metric.definition.get('schema_name') == exc.schema or obj is None or obj.get('kind') == 'view':
                metric.state = 'stale'
        session.commit()
        raise HTTPException(503, detail={'code': 'source_unavailable', 'message': 'Source access or scope verification failed'}) from None
    except (SourcePolicyError, SQLAlchemyError):
        raise HTTPException(503, detail={'code': 'source_unavailable', 'message': 'Source access or scope verification failed'}) from None
    previous = session.scalar(select(SchemaSnapshot).where(SchemaSnapshot.connection_id == connection_id).order_by(SchemaSnapshot.captured_at.desc(), SchemaSnapshot.id.desc()).limit(1))
    # Serialize with drafting and publication via the connection row lock.
    # Staleness is persistent: restoring a schema later does not restore approval.
    active = session.execute(select(MetricRevision, SchemaSnapshot.catalog)
        .join(SchemaSnapshot, MetricRevision.snapshot_id == SchemaSnapshot.id)
        .where(MetricRevision.connection_id == connection_id,
               MetricRevision.state.in_(['draft', 'in_review', 'ready']))).all()
    for metric, reviewed_catalog in active:
        if source_changed(metric.definition, reviewed_catalog, catalog):
            metric.state = 'stale'
    snapshot = SchemaSnapshot(connection_id=connection_id, fingerprint=fingerprint, catalog=catalog)
    session.add(snapshot)
    session.commit()
    return {"snapshot_id": snapshot.id, "fingerprint": fingerprint, "changed": previous is not None and previous.fingerprint != fingerprint, "catalog": catalog}


@router.get("/connections/{connection_id}/catalog")
def catalog(connection_id: uuid.UUID, session: Annotated[Session, Depends(metadata_session)], settings: Annotated[Settings, Depends(owner)]):
    get_record(session, connection_id)
    snapshot = session.scalar(select(SchemaSnapshot).where(SchemaSnapshot.connection_id == connection_id).order_by(SchemaSnapshot.captured_at.desc(), SchemaSnapshot.id.desc()).limit(1))
    if snapshot is None:
        raise HTTPException(404, detail={"code": "catalog_not_found", "message": "Connection has not been discovered"})
    return {"snapshot_id": snapshot.id, "fingerprint": snapshot.fingerprint, "catalog": snapshot.catalog}


@router.get('/connections/{connection_id}/published-metrics')
def published_metrics(connection_id: uuid.UUID, session: Annotated[Session, Depends(metadata_session)], principal: Annotated[Actor, Depends(actor)]):
    require_connection(principal, connection_id)
    get_record(session, connection_id)
    snapshot = session.scalar(select(SchemaSnapshot).where(SchemaSnapshot.connection_id == connection_id).order_by(SchemaSnapshot.captured_at.desc(), SchemaSnapshot.id.desc()).limit(1))
    if snapshot is None:
        return []
    rows = session.execute(select(MetricRevision, SchemaSnapshot.catalog).join(SchemaSnapshot, MetricRevision.snapshot_id == SchemaSnapshot.id).where(MetricRevision.connection_id == connection_id, MetricRevision.state == 'ready')).all()
    return [{'id': metric.metric_id, 'revision': metric.revision, 'name': metric.definition['name'],
             'dimensions': [d for d in metric.definition.get('dimensions', []) if (metric.dimension_checks or {}).get(d, {}).get('passed')]}
            for metric, reviewed in rows if not source_changed(metric.definition, reviewed, snapshot.catalog)]

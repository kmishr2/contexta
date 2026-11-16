import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ConnectionRecord(Base):
    __tablename__ = "connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    host: Mapped[str] = mapped_column(String(253), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    database: Mapped[str] = mapped_column(String(128), nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    credential_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    schemas: Mapped[list] = mapped_column(JSONB, nullable=False)
    sharing_policy: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SchemaSnapshot(Base):
    __tablename__ = "schema_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    catalog: Mapped[dict] = mapped_column(JSONB, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False)


class MetricRevision(Base):
    __tablename__ = "metric_revisions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_id: Mapped[str] = mapped_column(String(80), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schema_snapshots.id"), nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    check_result: Mapped[dict | None] = mapped_column(JSONB)
    dimension_checks: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False)
    __table_args__ = (UniqueConstraint("connection_id", "metric_id", "revision"),)


class Chat(Base):
    __tablename__ = 'chats'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('connections.id', ondelete='CASCADE'), nullable=False, index=True)
    last_intent: Mapped[dict | None] = mapped_column(JSONB)
    pending_metric: Mapped[str | None] = mapped_column(String(80))
    pending_plan: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False)


class QueryRun(Base):
    __tablename__ = 'query_runs'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('chats.id', ondelete='CASCADE'), nullable=False, index=True)
    metric_revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('metric_revisions.id'), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('schema_snapshots.id'), nullable=False)
    intent: Mapped[dict] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False)

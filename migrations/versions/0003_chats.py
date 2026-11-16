"""Add connection-scoped chats and query run provenance."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('chats',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('last_intent', postgresql.JSONB), sa.Column('pending_metric', sa.String(80)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False))
    op.create_index('ix_chats_connection_id', 'chats', ['connection_id'])
    op.create_table('query_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('chat_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('chats.id', ondelete='CASCADE'), nullable=False),
        sa.Column('metric_revision_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('metric_revisions.id'), nullable=False),
        sa.Column('snapshot_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('schema_snapshots.id'), nullable=False),
        sa.Column('intent', postgresql.JSONB, nullable=False),
        sa.Column('outcome', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False))
    op.create_index('ix_query_runs_chat_id', 'query_runs', ['chat_id'])


def downgrade():
    op.drop_index('ix_query_runs_chat_id', table_name='query_runs')
    op.drop_table('query_runs')
    op.drop_index('ix_chats_connection_id', table_name='chats')
    op.drop_table('chats')

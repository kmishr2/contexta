"""Store bounded owner onboarding conversations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('onboarding_conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('snapshot_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('schema_snapshots.id'), nullable=False),
        sa.Column('turns', postgresql.JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False))
    op.create_index('ix_onboarding_conversations_connection_id', 'onboarding_conversations', ['connection_id'])


def downgrade():
    op.drop_index('ix_onboarding_conversations_connection_id', table_name='onboarding_conversations')
    op.drop_table('onboarding_conversations')

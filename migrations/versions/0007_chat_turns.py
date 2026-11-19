"""Store bounded analyst chat exchanges."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('chat_turns',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('chat_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('chats.id', ondelete='CASCADE'), nullable=False),
        sa.Column('message', sa.String(2000), nullable=False),
        sa.Column('response', postgresql.JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False))
    op.create_index('ix_chat_turns_chat_id', 'chat_turns', ['chat_id'])


def downgrade():
    op.drop_index('ix_chat_turns_chat_id', table_name='chat_turns')
    op.drop_table('chat_turns')

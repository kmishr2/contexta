"""Bind chats to the local identity that created them."""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chats', sa.Column('actor_id', sa.String(80), nullable=False, server_default='development-owner'))
    op.alter_column('chats', 'actor_id', server_default=None)
    op.add_column('onboarding_conversations', sa.Column('actor_id', sa.String(80), nullable=False, server_default='development-owner'))
    op.alter_column('onboarding_conversations', 'actor_id', server_default=None)


def downgrade():
    op.drop_column('onboarding_conversations', 'actor_id')
    op.drop_column('chats', 'actor_id')

"""Keep bounded clarification context in analyst chats."""
from alembic import op
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chats', Column('pending_clarification', JSONB, nullable=True))


def downgrade():
    op.drop_column('chats', 'pending_clarification')

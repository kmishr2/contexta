"""Add reviewable AI query proposals to chats."""
from alembic import op
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chats', Column('pending_plan', JSONB, nullable=True))


def downgrade():
    op.drop_column('chats', 'pending_plan')

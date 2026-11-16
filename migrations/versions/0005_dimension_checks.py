"""Track independently verified breakdowns on each metric revision."""
from alembic import op
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('metric_revisions', Column('dimension_checks', JSONB, nullable=True))


def downgrade():
    op.drop_column('metric_revisions', 'dimension_checks')

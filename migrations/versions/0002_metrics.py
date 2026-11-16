"""Add versioned metric drafts and checks."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("metric_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_id", sa.String(80), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schema_snapshots.id"), nullable=False),
        sa.Column("definition", postgresql.JSONB, nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("check_result", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
        sa.UniqueConstraint("connection_id", "metric_id", "revision"))
    op.create_index("ix_metric_revisions_connection_id", "metric_revisions", ["connection_id"])


def downgrade():
    op.drop_index("ix_metric_revisions_connection_id", table_name="metric_revisions")
    op.drop_table("metric_revisions")

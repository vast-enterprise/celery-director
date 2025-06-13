"""add data field into Task object

Revision ID: e5cddff3c1bf
Revises: 5472063899f8
Create Date: 2025-02-10 15:15:48.377981

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e5cddff3c1bf"
down_revision = "5472063899f8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("celery_tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("data", sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table("celery_tasks", schema=None) as batch_op:
        batch_op.drop_column("data")

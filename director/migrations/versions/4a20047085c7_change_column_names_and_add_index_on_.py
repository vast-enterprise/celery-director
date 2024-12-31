"""change column names and add index on task_id

Revision ID: 4a20047085c7
Revises: cdb99748a7ab
Create Date: 2024-12-31 12:20:19.285033

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4a20047085c7'
down_revision = 'cdb99748a7ab'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('workflows', schema=None) as batch_op:
        batch_op.add_column(sa.Column('task_name', sa.String(length=255), nullable=False))
        batch_op.add_column(sa.Column('model_version', sa.String(length=255), nullable=False))
        batch_op.create_index(batch_op.f('ix_workflows_tripo_task_id'), ['tripo_task_id'], unique=False)
        batch_op.drop_column('name')
        batch_op.drop_column('project')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('workflows', schema=None) as batch_op:
        batch_op.add_column(sa.Column('project', sa.VARCHAR(length=255), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('name', sa.VARCHAR(length=255), autoincrement=False, nullable=False))
        batch_op.drop_index(batch_op.f('ix_workflows_tripo_task_id'))
        batch_op.drop_column('model_version')
        batch_op.drop_column('task_name')

    # ### end Alembic commands ###

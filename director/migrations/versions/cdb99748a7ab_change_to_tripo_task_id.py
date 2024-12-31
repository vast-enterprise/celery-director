"""change to tripo task_id

Revision ID: cdb99748a7ab
Revises: 95dd92b30ffe
Create Date: 2024-12-30 16:28:06.754511

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cdb99748a7ab'
down_revision = '95dd92b30ffe'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('workflows', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tripo_task_id', sa.String(length=255), nullable=False))
        batch_op.drop_column('task_id')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('workflows', schema=None) as batch_op:
        batch_op.add_column(sa.Column('task_id', sa.VARCHAR(length=255), autoincrement=False, nullable=False))
        batch_op.drop_column('tripo_task_id')

    # ### end Alembic commands ###

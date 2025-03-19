"""Initial migration

Revision ID: 5472063899f8
Revises: 
Create Date: 2025-01-09 10:59:12.051206

"""
import director
import sqlalchemy_utils

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '5472063899f8'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('celery_users',
    sa.Column('username', sa.String(length=255), nullable=False),
    sa.Column('password', sa.String(length=255), nullable=False),
    sa.Column('id', sqlalchemy_utils.types.uuid.UUIDType(binary=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_celery_users')),
    sa.UniqueConstraint('username', name=op.f('uq_celery_users_username'))
    )
    with op.batch_alter_table('celery_users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_celery_users_created_at'), ['created_at'], unique=False)

    op.create_table('celery_workflows',
    sa.Column('tripo_task_id', sa.String(length=255), nullable=False),
    sa.Column('task_name', sa.String(length=255), nullable=False),
    sa.Column('model_version', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('pending', 'progress', 'success', 'error', 'canceled', name='statustype'), nullable=False),
    sa.Column('payload', director.models.utils.JSONBType(), nullable=True),
    sa.Column('periodic', sa.Boolean(), nullable=True),
    sa.Column('comment', sa.String(length=255), nullable=True),
    sa.Column('id', sqlalchemy_utils.types.uuid.UUIDType(binary=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_celery_workflows'))
    )
    with op.batch_alter_table('celery_workflows', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_celery_workflows_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_celery_workflows_tripo_task_id'), ['tripo_task_id'], unique=False)

    op.create_table('celery_tasks',
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('pending', 'progress', 'success', 'error', 'canceled', name='statustype'), nullable=False),
    sa.Column('previous', director.models.utils.JSONBType(), nullable=True),
    sa.Column('result', sa.PickleType(), nullable=True),
    sa.Column('is_hook', sa.Boolean(), nullable=True),
    sa.Column('workflow_id', sqlalchemy_utils.types.uuid.UUIDType(binary=False), nullable=False),
    sa.Column('id', sqlalchemy_utils.types.uuid.UUIDType(binary=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['workflow_id'], ['celery_workflows.id'], name=op.f('fk_celery_tasks_workflow_id_celery_workflows'), ondelete='cascade'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_celery_tasks'))
    )
    with op.batch_alter_table('celery_tasks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_celery_tasks_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_celery_tasks_workflow_id'), ['workflow_id'], unique=False)


def downgrade():
    with op.batch_alter_table('celery_tasks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_celery_tasks_workflow_id'))
        batch_op.drop_index(batch_op.f('ix_celery_tasks_created_at'))

    op.drop_table('celery_tasks')
    with op.batch_alter_table('celery_workflows', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_celery_workflows_tripo_task_id'))
        batch_op.drop_index(batch_op.f('ix_celery_workflows_created_at'))

    op.drop_table('celery_workflows')
    with op.batch_alter_table('celery_users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_celery_users_created_at'))

    op.drop_table('celery_users')

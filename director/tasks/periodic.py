import logging

from sqlalchemy.orm import load_only

from director.builder import WorkflowBuilder
from director.extensions import cel, db
from director.models.workflows import Workflow

logger = logging.getLogger()


@cel.task()
def execute(workflow, payload):
    # periodic task 会在 celery beat 执行, 需要单独开启这个 worker
    model_version, task_name = workflow.split(":")
    c_obj = Workflow(tripo_task_id="na", model_version=model_version, task_name=task_name, payload=payload, periodic=True)
    c_obj.save()

    # Build the workflow and execute it
    workflow = WorkflowBuilder(c_obj.id)
    workflow.run()

    c_obj_dict = c_obj.to_dict()

    # Force commit before ending the function to ensure the ongoing transaction
    # does not end up in a "idle in transaction" state on PostgreSQL
    c_obj.commit()

    return c_obj_dict


@cel.task()
def cleanup(retentions):
    count = 0
    # cleanup 会在 celery beat 执行, 需要单独开启这个 worker
    for workflow_name, retention in retentions.items():
        model_version, task_name = workflow_name.split(":")
        logger.info(f"Cleaning {workflow_name} (retention of {retention})")

        bind = db.session.get_bind()
        if bind.engine.name == "sqlite":
            # SQLite does not use ON DELETE CASCADE by default
            db.session.execute("PRAGMA foreign_keys=ON")

        workflows = (
            db.session.query(Workflow)
            .options(load_only(Workflow.id))
            .filter_by(model_version=model_version, task_name=task_name)
            .order_by(Workflow.created_at.desc())
            .offset(retention)
            .all()
        )

        ids = [workflow.id for workflow in workflows]
        if not ids:
            logger.info(f"No need to clean {workflow_name}")
            continue

        Workflow.query.filter(Workflow.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        count += len(ids)
        logger.info(f"Deleted workflows: {len(ids)}")
    return count

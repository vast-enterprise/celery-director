from celery import chain
from celery.utils import uuid
from celery.utils.log import get_task_logger

from director.extensions import cel
from director.models import StatusType
from director.models.tasks import Task


logger = get_task_logger(__name__)


@cel.task(name="celery.ping")
def ping():
    # type: () -> str
    """Simple task that just returns 'pong'."""
    return "pong"


@cel.task()
def mark_as_canceled_pending_tasks(workflow_id):
    logger.info(f"Mark as cancelled pending tasks of the workflow {workflow_id}")
    tasks = Task.query.filter_by(workflow_id=workflow_id, status=StatusType.pending)
    for task in tasks:
        task.status = StatusType.canceled
        task.save()


@cel.task()
def failure_hooks_launcher(workflow_id, queue, tasks_names, payload):
    canvas = []

    for task_name in tasks_names:
        task_id = uuid()

        # We create the Celery task specifying its UID
        signature = cel.tasks.get(task_name).subtask(
            kwargs={"workflow_id": workflow_id, "payload": payload},
            task_id=task_id,
        )

        # Director task has the same UID
        task = Task(
            id=task_id,
            key=task_name,
            workflow_id=workflow_id,
            status=StatusType.pending,
            is_hook=True,
        )
        task.save()

        canvas.append(signature)

    canvas = chain(*canvas, task_id=uuid())

    result = canvas.apply_async()

    try:
        result.get()
    except Exception:
        pass

    task_id = uuid()
    signature_mark_as_canceled = cel.tasks.get(
        "director.tasks.workflows.mark_as_canceled_pending_tasks"
    ).subtask(
        args=(workflow_id,),
        task_id=task_id,
    )
    signature_mark_as_canceled.apply_async()

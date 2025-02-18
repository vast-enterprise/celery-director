import time, os, sys
from pathlib import Path

from celery import chain
from celery.utils import uuid
from celery.utils.log import get_task_logger

from director import extensions
from director.extensions import cel
from director.extensions import kafka_client
from director.models import StatusType
from director.models.workflows import Workflow
from director.models.tasks import Task
from workers.worker_utils.status_code import StatusCode


config_path = Path(os.getenv("DIRECTOR_CONFIG")).resolve()
sys.path.append(f"{config_path.parent.resolve()}/")
import config

workflow_path = Path(os.getenv("DIRECTOR_HOME")).resolve()
sys.path.append(f"{workflow_path.resolve()}/")
from tripo_workflows.celery_task_utils import increase_counter


logger = get_task_logger(__name__)


@cel.task(name="celery.ping")
def ping():
    # type: () -> str
    """Simple task that just returns 'pong'."""
    return "pong"

@cel.task(bind=True)
def start(self, workflow_id, *args, **kwargs):
    logger.info(f"Opening the workflow {workflow_id}")
    workflow = Workflow.query.filter_by(id=workflow_id).first()
    workflow.status = StatusType.progress
    workflow.save()

    # 发 workflow 启动信息到 openapi
    data = workflow.payload["data"]
    task_id = data["task_id"]
    module_name = workflow.task_name
    callback_data = {
                        "task_id": task_id,
                        "task_status": StatusCode.RUNNING.value,
                        "task_name": module_name,
                        "result": {}
                    }
    callback_data["error_code"] = 0
    callback_data["error_msg"] = config.ERR_CODE2MSG[
        callback_data["error_code"]
    ]

    callback_data["start_time"] = time.time()
    callback_data["end_time"] = -1
    # TODO 从环境变量读取
    target_topic = config.TASK_TOPIC
    kafka_client.produce_message(target_topic, callback_data, task_id)
    return {"prev_task_finish_time": time.time()}


@cel.task(bind=True)
def end(self, workflow_id, *args, **kwargs):
    # Waiting for the workflow status to be marked in error if a task failed
    # TODO 0.5 是不是太长
    time.sleep(0.5)

    logger.info(f"Closing the workflow {workflow_id}")
    workflow = Workflow.query.filter_by(id=workflow_id).first()

    if workflow.status != StatusType.error:
        workflow.status = StatusType.success
        workflow.save()

    end_time = workflow.created_at.timestamp()
    # 方法参考 https://github.com/celery/celery/issues/479
    running_time = time.time() - end_time
    increase_counter(extensions.redis_client.get_client(), running_time, workflow.payload["data"])


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

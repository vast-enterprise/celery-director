import json
from celery import Task as _Task
from celery.signals import task_prerun, task_postrun
from celery.utils.log import get_task_logger

from director.extensions import cel, db
from director.models import StatusType
from director.models.tasks import Task


logger = get_task_logger(__name__)


@task_prerun.connect
def director_prerun(task_id, task, *args, **kwargs):
    if task.name.startswith("director.tasks"):
        return

    with cel.app.app_context():
        task = Task.query.filter_by(id=task_id).first()
        task.status = StatusType.progress
        task.save()


@task_postrun.connect
def close_session(*args, **kwargs):
    # Flask SQLAlchemy will automatically create new sessions for you from
    # a scoped session factory, given that we are maintaining the same app
    # context, this ensures tasks have a fresh session (e.g. session errors
    # won't propagate across tasks)
    db.session.remove()


class BaseTask(_Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        task = Task.query.filter_by(id=task_id).first()
        task.status = StatusType.error
        task.result = {"exception": str(exc), "traceback": einfo.traceback}
        task.workflow.status = StatusType.error
        task.save()

        logger.info(f"Task {task_id} is now in error")
        super(BaseTask, self).on_failure(exc, task_id, args, kwargs, einfo)

    def on_success(self, retval, task_id, args, kwargs):
        task = Task.query.filter_by(id=task_id).first()
        task.status = StatusType.success
        task.result = retval
        
        # TODO 有一些任务需要往数据库存东西
        # 可以放在 data 里面
        if self.name == "translate":
            data = retval["translated_data"]["data"]
            is_eng_negative_pmt = retval["translated_data"]["is_eng_negative_pmt"]
            translate_data = {
                "original_prompt": data["original_prompt"],
                "obj_prompt": data["obj_prompt"],
                "original_negative_prompt": data["original_negative_prompt"] if is_eng_negative_pmt else None,
                "negative_prompt": data["negative_prompt"] if is_eng_negative_pmt else None
            }
            task.data = json.dumps(translate_data)
        task.save()

        logger.info(f"Task {task_id} is now in success")
        super(BaseTask, self).on_success(retval, task_id, args, kwargs)

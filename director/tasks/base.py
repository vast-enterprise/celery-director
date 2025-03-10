from celery import Task as _Task
from celery.utils.log import get_task_logger
from celery.signals import after_task_publish, task_prerun, task_postrun

from director.extensions import db_engine
from director.models import StatusType
from director.models.tasks import Task


logger = get_task_logger(__name__)

class BaseTask(_Task):

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        if self.name.startswith("director.tasks"):
            return

        db_session = db_engine.get_db_session()
        with db_session() as session:
            task = session.query(Task).filter_by(id=task_id).first()
            task.status = StatusType.error
            task.result = {"exception": str(exc), "traceback": einfo.traceback}
            task.workflow.status = StatusType.error
            task.save(session)
            session.commit()

        logger.info(f"Task {task_id} is now in error")
        super(BaseTask, self).on_failure(exc, task_id, args, kwargs, einfo)

    def on_success(self, retval, task_id, args, kwargs):
        if self.name.startswith("director.tasks"):
            return

        db_session = db_engine.get_db_session()
        with db_session() as session:
            task = session.query(Task).filter_by(id=task_id).first()
            task.status = StatusType.success
            task.result = retval
            task.save(session)
            session.commit()

        logger.info(f"Task {task_id} is now in success")
        super(BaseTask, self).on_success(retval, task_id, args, kwargs)

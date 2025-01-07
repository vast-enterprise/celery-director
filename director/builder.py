from celery import chain, group
from celery.utils import uuid

from director.exceptions import WorkflowSyntaxError
from director.extensions import cel, cel_workflows
from director.models import StatusType
from director.models.tasks import Task
from director.models.workflows import Workflow
from director.tasks.workflows import start, end, failure_hooks_launcher


class WorkflowBuilder(object):
    def __init__(self, workflow_id):
        self.workflow_id = workflow_id
        self._workflow = None

        self.queue = cel_workflows.get_queue(str(self.workflow))
        self.custom_queues = {}

        self.tasks = cel_workflows.get_tasks(str(self.workflow))
        self.canvas = []

        self.failure_hook = cel_workflows.get_failure_hook_task(str(self.workflow))
        self.failure_hook_canvas = []

        self.success_hook = cel_workflows.get_success_hook_task(str(self.workflow))
        self.success_hook_canvas = []

        # Pointer to the previous task(s)
        self.previous = []

    @property
    def workflow(self):
        if not self._workflow:
            self._workflow = Workflow.query.filter_by(id=self.workflow_id).first()
        return self._workflow

    def new_task(self, task_name, previous, is_hook):
        task_id = uuid()

        queue = self.custom_queues.get(task_name, self.queue)

        # We create the Celery task specifying its UID
        signature = cel.tasks.get(task_name).subtask(
            kwargs={"workflow_id": self.workflow_id, "payload": self.workflow.payload},
            queue=queue,
            task_id=task_id,
        )

        previous_ids = []
        if isinstance(previous, (chain, group)):
            for previous_task in previous.tasks:
                previous_ids.append(previous_task.id)
        elif previous is not None:
            previous_ids = [previous.id]

        # Director task has the same UID
        task = Task(
            id=task_id,
            key=task_name,
            workflow_id=self.workflow.id,
            previous=previous_ids,
            status=StatusType.pending,
            is_hook=is_hook,
        )
        task.save()

        return signature

    def parse_queues(self):
        if isinstance(self.queue, dict):
            self.custom_queues = self.queue.get("customs", {})
            self.queue = self.queue.get("default", "celery")
        if not (isinstance(self.queue, str) and isinstance(self.custom_queues, dict)):
            raise WorkflowSyntaxError()

    def parse_wf(self, tasks, payload, is_hook=False):
        return self.parse_dag(tasks, None, None, payload, is_hook)

    def parse_dag(self, tasks, payload=None, is_hook=False, src_parents=None, is_group=False):
        canvas_tasks = []
        parents = src_parents
        for task in tasks:
            if is_group:
                parents = src_parents
            if isinstance(task, dict):
                if "GROUP" in task:
                    if not isinstance(task["GROUP"], list):
                        raise WorkflowSyntaxError()
                    parents = self.parse_dag(task["GROUP"], payload,
                                        is_hook, parents,
                                        is_group=True)
                else:
                    # add task
                    ((task_name, condition),) = task.items()
                    if payload is None or payload.get(condition, True):
                        parents = self.new_task(task_name, parents, is_hook)
            elif isinstance(task, list):
                parents = self.parse_dag(task, payload, is_hook, parents, is_group=False)
            elif isinstance(task, str):
                # add task
                parents = self.new_task(task, parents, is_hook)
            else:
                raise WorkflowSyntaxError()
            canvas_tasks.append(parents)
        if is_group:
            return group(*canvas_tasks, task_id=uuid())
        return chain(*canvas_tasks, task_id=uuid())

    def build(self, payload):
        self.parse_queues()
        self.canvas = self.parse_wf(self.tasks, payload)
        self.canvas.insert(0, start.si(self.workflow.id).set(queue=self.queue))
        self.canvas.append(end.si(self.workflow.id).set(queue=self.queue))

    def build_hooks(self):
        initial_previous = self.previous

        if self.failure_hook and not self.failure_hook_canvas:
            self.previous = None
            self.failure_hook_canvas = [
                failure_hooks_launcher.si(
                    self.workflow.id,
                    self.queue,
                    [self.failure_hook],
                    self.workflow.payload,
                ).set(queue=self.queue),
            ]

        if self.success_hook and not self.success_hook_canvas:
            self.previous = None
            self.success_hook_canvas = [self.parse_wf([self.success_hook], {}, True)[0]]

        self.previous = initial_previous

    def run(self, payload={}):
        if not self.canvas:
            self.build(conditions)
        self.build_hooks()

        priority = 1
        if payload is not None and "priority" in payload:
            priority = 10 - payload["priority"]
        try:
            return self.canvas.apply_async(
                priority=priority,
                link=self.success_hook_canvas,
                link_error=self.failure_hook_canvas,
            )

        except Exception as e:
            self.workflow.status = StatusType.error
            self.workflow.save()
            raise e

    def cancel(self):
        status_to_cancel = set([StatusType.pending, StatusType.progress])
        for task in self.workflow.tasks:
            if task.status in status_to_cancel:
                cel.control.revoke(task.id, terminate=True)
                task.status = StatusType.canceled
                task.save()
        self.workflow.status = StatusType.canceled
        self.workflow.save()

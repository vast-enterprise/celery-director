from celery import chain, group
from celery.utils import uuid

from director.exceptions import WorkflowSyntaxError
from director.extensions import cel, cel_workflows
from director.models import StatusType
from director.models.tasks import Task
from director.models.workflows import Workflow
from director.tasks.workflows import start, end, failure_hooks_launcher


class CanvasPhase:
    def __init__(self, phase, previous) -> None:
        self.phase = phase
        self.previous = previous

class WorkflowBuilder(object):
    def __init__(self, workflow_id):
        self.workflow_id = workflow_id
        self._workflow = None

        self.root_type = cel_workflows.get_type(str(self.workflow))
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

    def new_task(self, task_name, previous, is_hook, original_task_name=None):
        task_id = uuid()

        queue = self.custom_queues.get(task_name, self.queue)

        if original_task_name:
            # We create the Celery task specifying its UID
            signature = cel.tasks.get(task_name).subtask(
                kwargs={"workflow_id": self.workflow_id, "payload": self.workflow.payload, "original_task_name": original_task_name},
                queue=queue,
                task_id=task_id,
            )
        else:
            # We create the Celery task specifying its UID
            signature = cel.tasks.get(task_name).subtask(
                kwargs={"workflow_id": self.workflow_id, "payload": self.workflow.payload},
                queue=queue,
                task_id=task_id,
            )

        if type(previous) != list:
            previous = [previous]

        # Director task has the same UID
        task = Task(
            id=task_id,
            key=task_name,
            workflow_id=self.workflow.id,
            previous=previous,
            status=StatusType.pending,
            is_hook=is_hook,
        )
        task.save()

        return signature

    def parse_queues(self):
        if type(self.queue) is dict:
            self.custom_queues = self.queue.get("customs", {})
            self.queue = self.queue.get("default", "celery")
        if type(self.queue) is not str or type(self.custom_queues) is not dict:
            raise WorkflowSyntaxError()
    
    def parse_wf(self, tasks, conditions, is_hook=False):
            full_canvas = self.parse_recursive(tasks, None, None, conditions, is_hook)
            return full_canvas

    def parse_recursive(self, tasks, parent_type, parent, conditions, is_hook):
        previous = parent.phase.id if parent!=None else []
        canvas_phase = []
        for task in tasks:  
            if type(task) is str:
                if len(canvas_phase) > 0 and parent_type!="group":
                    previous = canvas_phase[-1].previous

                # 在这根据 conditions 判断一下任务是否是被跳过的
                # 如果不执行把任务换成 skipped_task 以免破坏 pipeline 结构
                if task in conditions and not conditions[task]:
                    # TODO 可能有更好办法？
                    signature = self.new_task("skipped_task", previous, is_hook, task)
                else:
                    signature = self.new_task(task, previous, is_hook)
                canvas_phase.append(CanvasPhase(signature, signature.id))
            elif type(task) is dict:
                task_name = list(task)[0]
                task_type = task[task_name]["type"]
                if "type" not in task[task_name] \
                    and (task[task_name]["type"] != "group" \
                        or task[task_name]["type"] != "chain"):
                    raise WorkflowSyntaxError()
                
                current = None
                if len(canvas_phase) > 0 and parent_type!="group":
                    current = canvas_phase[-1]
                else:
                    current = parent
                canvas_phase.append(self.parse_recursive(task[task_name]["tasks"], task_type, current, conditions, is_hook))   
            else:
                raise WorkflowSyntaxError()
                        
        if parent_type == "chain":
            chain_previous = canvas_phase[-1].phase.id
            return CanvasPhase(chain([ca.phase for ca in canvas_phase]), chain_previous)
        elif parent_type == "group":
            group_previous = [ca.previous for ca in canvas_phase]
            return CanvasPhase(group([ca.phase for ca in canvas_phase]), group_previous)
        else:
            return canvas_phase

    def build(self, conditions):
        self.parse_queues()
        self.canvas_phase = self.parse_wf(self.tasks, conditions)
        self.canvas_phase.insert(0, CanvasPhase(
            start.si(self.workflow.id).set(queue=self.queue),
        []))
        self.canvas_phase.append(CanvasPhase(
            end.si(self.workflow.id).set(queue=self.queue),
        []))

        if self.root_type == "group":
            self.canvas = group([ca.phase for ca in self.canvas_phase], task_id=uuid())
        else:
            self.canvas = chain([ca.phase for ca in self.canvas_phase], task_id=uuid())

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
            self.success_hook_canvas = [self.parse_wf([self.success_hook], {}, True)[0].phase]

        self.previous = initial_previous

    def run(self, priority = 1, conditions = {}):
        if not self.canvas:
            self.build(conditions)
        self.build_hooks()

        try:
            # TODO send task
            return self.canvas.apply_async(
                priority=priority,
                # 成功的 hook 会在运行 workflow 的同一个 worker 执行
                link=self.success_hook_canvas,
                # 失败的 hook 会在 celery beat 执行
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

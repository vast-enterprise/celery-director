import sys, os
from pathlib import Path
from celery import chain, group
from celery.utils import uuid

from director.exceptions import WorkflowSyntaxError
from director.extensions import cel, cel_workflows
from director.models import StatusType
from director.models.tasks import Task
from director.models.workflows import Workflow
from director.tasks.workflows import failure_hooks_launcher

workflow_path = Path(os.getenv("DIRECTOR_HOME")).resolve()
sys.path.append(f"{workflow_path.resolve()}/")
from tripo_workflows.tasks.start_end_tasks import start, end


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


    def get_task_type(self, task):
        if type(task) is list:
            return "chain"
        if type(task) is dict:
            (task_name, _), = task.items() 
            if task_name == "GROUP":
                return "group"
        return "common"


    def new_task(self, task_name, previous, is_hook, priority, assigned_queue, periodic):
        task_id = uuid()
        if periodic:
            # periodic 任务统一放到单独的 worker 执行
            signature = cel.tasks.get(task_name).subtask(
                task_id=task_id,
                queue=cel.app.config["NON_SUBMODULE_TASKS_QUEUE_NAME"]
            )
            task = Task(
                id=task_id,
                key=task_name,
                workflow_id=self.workflow.id,
                status=StatusType.pending,
            )
            task.save()
            return signature

        # We create the Celery task specifying its UID
        signature = cel.tasks.get(task_name).subtask(
            kwargs={"workflow_id": str(self.workflow_id),
                    "payload": self.workflow.payload},
            queue=assigned_queue,
            task_id=task_id,
        )
        signature.set(priority=priority)
        
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


    def parse_wf(self, tasks, queues, conditions, priority, periodic, is_hook=False):
        full_canvas = self.parse_recursive(tasks, None, None, queues, conditions, priority, is_hook, periodic)
        return full_canvas


    def parse_recursive(self, tasks, parent_type, parent, queues, conditions, priority, is_hook, periodic):
        previous = []
        if parent != None:
            if isinstance(parent.phase, group): 
                previous = [task.id for task in parent.phase.tasks]
            else:
                previous = parent.phase.id 
        canvas_phase = []

        for task in tasks:
            task_type = self.get_task_type(task)
            # 如果是普通任务
            if task_type == "common":
                if len(canvas_phase) > 0 and parent_type != "group":
                    previous = canvas_phase[-1].previous

                task_name, is_skipped = task, False
                # 如果是有条件的
                if type(task) is dict:
                    (task_name, condition_key), = task.items()
                    is_skipped = condition_key in conditions and not conditions[condition_key]
                if not is_skipped:
                    # 如果 queues 非空则用 payload 中的 queues
                    assigned_queue = None
                    if not periodic:
                        try:
                            assigned_queue = queues[task_name]
                        except Exception as e:
                            raise WorkflowSyntaxError("Every task should have an assigned queue")
                    signature = self.new_task(task_name, previous, is_hook, priority, assigned_queue, periodic)
                    canvas_phase.append(CanvasPhase(signature, signature.id))
            # 如果是 GROUP 任务
            else:
                group_task = task[list(task)[0]] if task_type == "group" else task
                current = None
                if len(canvas_phase) > 0 and parent_type != "group":
                    current = canvas_phase[-1]
                else:
                    current = parent
                group_canvas_phase = self.parse_recursive(group_task, task_type, current, queues, conditions, priority, is_hook)
                if group_canvas_phase:
                    canvas_phase.append(group_canvas_phase)

        if len(canvas_phase) == 0:
            return None

        if parent_type == "chain":
            chain_previous = canvas_phase[-1].phase.id
            if isinstance(canvas_phase[-1].phase, group): 
                chain_previous = [task.id for task in canvas_phase[-1].phase.tasks]
            return CanvasPhase(chain([ca.phase for ca in canvas_phase]), chain_previous)
        elif parent_type == "group":
            def flatten(lst):
                for item in lst:
                    if isinstance(item, list):
                        yield from flatten(item)
                    else:
                        yield item
            group_previous = [ca.previous for ca in canvas_phase]
            # group_previous 有可能是 [task1, [task2, task3]] 这种嵌套情况
            flatten_previous = list(flatten(group_previous))
            return CanvasPhase(group([ca.phase for ca in canvas_phase]), flatten_previous)
        else:
            return canvas_phase


    def build(self, queues, conditions, priority, periodic):
        # 不在 workflows.yml 里面定义 queue 名称
        # 所有 queue 名称都由 queues 传入
        self.parse_queues()
        self.canvas_phase = self.parse_wf(self.tasks, queues, conditions, priority, periodic)
        if not periodic:
            # 不是 periodic 任务会把 start 和 end 任务放在 NON_SUBMODULE_TASKS_QUEUE_NAME 里面
            # 因为现在 periodic 任务都是单任务不需要 pipeline, 但是如果之后变成了多任务的 pipeline 
            # 这里需要进行修改
            task_assigned_queue = cel.app.config["NON_SUBMODULE_TASKS_QUEUE_NAME"]
            self.canvas_phase.insert(0, CanvasPhase(
                start.si(self.workflow.id).set(queue=task_assigned_queue).set(priority=priority),
            []))
            self.canvas_phase.append(CanvasPhase(
                end.si(self.workflow.id).set(queue=task_assigned_queue).set(priority=priority),
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


    def run(self, queues, priority, conditions, periodic=False):
        if not self.canvas:
            # 为每个 task 单独设置 priority
            self.build(queues, conditions, priority, periodic)

        # 不在 workflows.yml 里面设置任何 hook
        self.build_hooks()

        try:
            return self.canvas.apply_async(
                # 成功的 hook 会在运行 workflow 的同一个 worker 执行
                link=self.success_hook_canvas,
                # 失败的 hook 会在 celery beat 执行
                link_error=self.failure_hook_canvas,
                expire=3600 # TODO: 应该放在设置里
            )

        except Exception as e:
            self.workflow.status = StatusType.error
            self.workflow.save()
            raise e


    def cancel(self):
        status_to_cancel = set([StatusType.pending, StatusType.progress])
        for task in self.workflow.tasks:
            if task.status in status_to_cancel:
                cel.control.revoke(str(task.id), terminate=True)
                task.status = StatusType.canceled
                task.save()
        self.workflow.status = StatusType.canceled
        self.workflow.save()

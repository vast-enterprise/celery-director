from director import task
from celery.signals import task_postrun
from celery.signals import task_failure
from director.builder import WorkflowBuilder
from director.models.workflows import Workflow

@task(name="photo_frame", time_limit=180)
def photo_frame(*args, **kwargs):
    return "photo_frame"

@task(name="caption", time_limit=180)
def caption(*args, **kwargs):
    return "caption"

@task(name="image2model", time_limit=180)
def image2model(*args, **kwargs):
    return "image2model"

@task(name="image2image", time_limit=180)
def image2image(*args, **kwargs):
    return "image2image"

@task(name="postprocess_stylize", time_limit=180)
def postprocess_stylize(*args, **kwargs):
    return "postprocess_stylize"

@task(name="texture", time_limit=180)
def texture(*args, **kwargs):
    return "texture"

@task(name="pbr", time_limit=180)
def pbr(*args, **kwargs):
    return "pbr"

@task(name="diffuse2normal", time_limit=180)
def diffuse2normal(*args, **kwargs):
    return "diffuse2normal"

@task(name="project2model", time_limit=180)
def project2model(*args, **kwargs):
    return "project2model"

@task(name="render", time_limit=180)
def render(*args, **kwargs):
    return "render"

@task(name="empty_task")
def empty_task(*args, **kwargs):
    return "empty_task"

@task(name="skipped_task")
def skipped_task(*args, **kwargs):
    return f"skipped task: {kwargs['original_task_name']}"

@task(name="success_task")
def success_task(*args, **kwargs):
    print("I'm executed because the workflow succeeded")
    return "success_task"

@task(name="fail_task")
def fail_task(*args, **kwargs):
    print("I'm executed because the workflow failed")
    return "fail_task"

# yaml 中的 hooks 在 nested group 中如果有 error 无法触发 fail_task
# 用手动捕捉 error 的方式 cancel 剩余 task
@task_failure.connect()
def handle_task_failure(sender=None, task_id=None, exception=None, **kwargs):
    print(f"Task {task_id} failed with exception: {exception}.")
    workflow_id = kwargs["kwargs"]["workflow_id"]
    obj = Workflow.query.filter_by(id=workflow_id).first()
    if not obj:
        print(f"Workflow {workflow_id} does not exist")

    workflow = WorkflowBuilder(obj.id)
    workflow.cancel()
    print(f"Workflow {workflow_id} canceled")


@task_postrun.connect
def task_postrun_handler(sender=None, **kwargs):
    # canvas 有一个开始任务和结束任务
    print(f"Task {sender.name} has finished.")
    if sender.name != "director.tasks.workflows.start" and sender.name != "director.tasks.workflows.end":
        task_name = kwargs["args"][0]
        workflow_id = kwargs["kwargs"]["workflow_id"]
        task_id = kwargs["kwargs"]["payload"]["task_id"]
        state = kwargs["state"]
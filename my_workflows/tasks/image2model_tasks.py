from director import task
from celery.signals import task_failure
from director.builder import WorkflowBuilder
from director.models.workflows import Workflow

@task(name="photo_frame")
def photo_frame(*args, **kwargs):
    return "photo_frame"

@task(name="caption")
def caption(*args, **kwargs):
    return "caption"

@task(name="image2model")
def image2model(*args, **kwargs):
    return "image2model"

@task(name="image2image")
def image2image(*args, **kwargs):
    return "image2image"

@task(name="postprocess_stylize")
def postprocess_stylize(*args, **kwargs):
    return "postprocess_stylize"

@task(name="texture")
def texture(*args, **kwargs):
    return "texture"

@task(name="pbr")
def pbr(*args, **kwargs):
    return "pbr"

@task(name="diffuse2normal")
def diffuse2normal(*args, **kwargs):
    return "diffuse2normal"

@task(name="project2model")
def project2model(*args, **kwargs):
    return "project2model"

@task(name="render")
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
    print(f"Task {task_id} failed with exception: {exception}。 Sender: {sender.name}, workflow_id: {kwargs['kwargs']['workflow_id']}")
    workflow_id = kwargs["kwargs"]["workflow_id"]
    obj = Workflow.query.filter_by(id=workflow_id).first()
    if not obj:
        print(f"Workflow {workflow_id} does not exist")

    workflow = WorkflowBuilder(obj.id)
    workflow.cancel()
    print(f"Workflow {workflow_id} canceled")
import click
import json
from json.decoder import JSONDecodeError
from terminaltables import AsciiTable
import uuid

from flask_json_schema import JsonValidationError

from director.builder import WorkflowBuilder
from director.context import pass_ctx
from director.exceptions import WorkflowNotFound
from director.extensions import cel_workflows
from director.models.workflows import Workflow
from director.utils import validate, format_schema_errors, build_celery_schedule

from director.exceptions import PayloadSyntaxError

def tasks_to_ascii(tasks, hooks):
    tasks_str = ""
    # Wrap the tasks list
    for task in tasks:
        if type(task) == dict:
            group_name = list(task.keys())[0]
            tasks_str += f"Group {group_name}:\n"
            for task_name in task[group_name].get("tasks", []):
                tasks_str += f" └ {task_name}\n"
        else:
            tasks_str += f"{task}\n"

    if "failure" in hooks:
        tasks_str += f"Failure hook: {hooks['failure']}\n"
    if "success" in hooks:
        tasks_str += f"Success hook: {hooks['success']}\n"

    # Just remove the last newline
    if tasks_str:
        tasks_str = tasks_str[:-1]

    return tasks_str


@click.group()
def workflow():
    """Manage the workflows"""


@workflow.command(name="list")
@pass_ctx
def list_workflow(ctx):
    """List the workflows"""
    workflows = {
        k: v
        for k, v in sorted(cel_workflows.workflows.items(), key=lambda item: item[0])
    }

    data = [[f"Workflows ({len(workflows)})", "Periodic", "Tasks"]]

    # Add a row for each workflow
    for name, conf in workflows.items():
        periodic = "--"
        if conf.get("periodic"):
            periodic, _ = build_celery_schedule(name, conf["periodic"])
        tasks_str = tasks_to_ascii(
            conf["tasks"], conf["hooks"] if "hooks" in conf else {}
        )
        data.append([name, periodic, tasks_str])

    table = AsciiTable(data)
    table.inner_row_border = True
    table.justify_columns[1] = "center"
    click.echo(table.table)


@workflow.command(name="show")
@click.argument("name")
@pass_ctx
def show_workflow(ctx, name):
    """Display details of a workflow"""
    try:
        _workflow = cel_workflows.get_by_name(name)
    except WorkflowNotFound as e:
        click.echo(f"Error: {e}")
        raise click.Abort()

    tasks_str = tasks_to_ascii(
        _workflow["tasks"], _workflow["hooks"] if "hooks" in _workflow else {}
    )
    periodic = "--"
    if _workflow.get("periodic"):
        periodic, _ = build_celery_schedule(name, _workflow["periodic"])
    payload = _workflow.get("periodic", {}).get("payload", {})

    # Construct the table
    table = AsciiTable(
        [
            ["Name", name],
            ["Tasks", tasks_str],
            ["Periodic", periodic],
            ["Default Payload", payload],
        ]
    )
    table.inner_heading_row_border = False
    table.inner_row_border = True
    click.echo(table.table)


@workflow.command(name="run")
@click.argument("fullname")
@click.argument("payload", required=False, default="{}")
@click.option("--comment", help="A comment for the workflow instance.")
@pass_ctx
def run_workflow(ctx, fullname, payload, comment):
    """Execute a workflow"""
    try:
        # fullname 是 workflow 的名字
        # 目前采用用版本号:任务名称, 中间有一个冒号 :
        # 例如 v2.0-20240919:image2model
        wf = cel_workflows.get_by_name(fullname)
        payload = json.loads(payload)

        if "schema" in wf:
            try:
                validate(payload, wf["schema"])
            except JsonValidationError as e:
                result = format_schema_errors(e)

                click.echo(f"Error: {result['error']}")
                for err in result["errors"]:
                    click.echo(f"- {err}")
                raise click.Abort()

    except WorkflowNotFound as e:
        click.echo(f"Error: {e}")
        raise click.Abort()
    except (JSONDecodeError) as e:
        click.echo(f"Error in the payload : {e}")
        raise click.Abort()

    # 在 payload 里面必须要有 task_id 和 priority
    if "task_id" not in payload["data"]:
        raise PayloadSyntaxError("task_id is not found in payload")
    if "priority" not in payload["data"]:
        raise PayloadSyntaxError("priority is not found in payload")
    if "conditions" not in payload:
        raise PayloadSyntaxError("conditions(dict) is not found in payload")
    if "queues" not in payload:
        raise PayloadSyntaxError("queues(dict) is not found in payload")

    task_id = payload["data"]["task_id"]

    # Create the workflow object
    # 把 v2.0-20240919:image2model 拆开
    model_version, task_name = fullname.split(":")
    obj = Workflow(tripo_task_id=task_id, model_version=model_version, task_name=task_name, payload=payload, comment=comment)
    obj.save()

    # Build the canvas and execute it
    # 用 obj.id 主要是怕未来如果有任务重试，用 task_id 做主键会有重复
    # TODO 在网页端增加利用 task_id 搜索
    _workflow = WorkflowBuilder(obj.id)

    # conditions 是一个字典, 里面决定某些子任务是否执行
    # 如果是空字典  则所有子任务都执行
    conditions = payload["conditions"]
    queues = payload["queues"]
    priority = payload["data"]["priority"]
    _workflow.run(queues, priority, conditions)

    click.echo(f"Workflow {obj.id} for task {task_id} launched")


@workflow.command(name="cancel")
@click.argument("id")
@pass_ctx
def cancel_workflow(ctx, id):
    """Cancel a workflow"""
    try:
        uuid.UUID(id)
    except ValueError:
        click.echo(f"Invalid UUID")
        raise click.Abort()
    obj = Workflow.query.filter_by(id=id).first()
    if not obj:
        click.echo(f"Workflow {id} does not exist")
        raise click.Abort()

    workflow = WorkflowBuilder(obj.id)
    workflow.cancel()

    click.echo(f"Workflow {id} canceled")


@workflow.command(name="relaunch")
@click.argument("id")
@pass_ctx
def relaunch_workflow(ctx, id):
    """Relaunch a workflow"""
    try:
        uuid.UUID(id)
    except ValueError:
        click.echo(f"Invalid UUID")
        raise click.Abort()
    obj = Workflow.query.filter_by(id=id).first()
    if not obj:
        click.echo(f"Workflow {id} does not exist")
        raise click.Abort()

    # Create the workflow in DB
    obj = Workflow(tripo_task_id=obj.tripo_task_id, project=obj.model_version, name=obj.task_name, payload=obj.payload)
    obj.save()

    # Build the workflow and execute it
    workflow = WorkflowBuilder(obj.id)
    conditions = obj.payload["conditions"]
    workflow.run(conditions)

    click.echo(f"Workflow {obj.id} relaunched")
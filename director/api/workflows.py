from distutils.util import strtobool

from flask import abort, jsonify, request
from flask import current_app as app

from director.api import api_bp, validate
from director.auth import auth
from director.builder import WorkflowBuilder
from director.exceptions import WorkflowNotFound
from director.extensions import cel_workflows, schema, db_engine
from director.models.workflows import Workflow


def _get_workflow(workflow_id):
    db_session = db_engine.get_db_session()
    with db_session() as session:
        workflow = session.query(Workflow).filter_by(id=workflow_id).first()
    if not workflow:
        abort(404, f"Workflow {workflow_id} not found")
    return workflow


def _execute_workflow(model_version, task_name, payload={}, comment=None):
    fullname = f"{model_version}:{task_name}"

    # Check if the workflow exists
    try:
        wf = cel_workflows.get_by_name(fullname)
        if "schema" in wf:
            validate(payload, wf["schema"])
    except WorkflowNotFound:
        abort(404, f"Workflow {fullname} not found")

    task_id = payload["data"]["task_id"]
    mapped_priority = payload["mapped_priority"]
    # Create the workflow in DB
    db_session = db_engine.get_db_session()
    with db_session() as session:
        obj = Workflow(id=task_id, tripo_task_id=task_id, model_version=model_version, task_name=task_name, payload=payload, comment=comment)
        obj.save(session)
        session.commit()
        obj_dict = obj.to_dict()

    # Build the workflow and execute it
    workflow = WorkflowBuilder(obj.id)
    conditions = payload["conditions"]
    queues = payload["queues"]
    workflow.run(queues, mapped_priority, conditions)
    app.logger.info(f"Workflow sent : {workflow.canvas}")

    return obj_dict, workflow


def _cancel_workflow(obj):
    db_session = db_engine.get_db_session()
    with db_session() as session:
        workflow = WorkflowBuilder(obj.id)
        workflow.cancel(session)
        session.commit()
    app.logger.info(f"Workflow {obj.id} canceled")
    return obj.to_dict(), workflow


@api_bp.route("/workflows", methods=["POST"])
@auth.login_required
@schema.validate(
    {
        "required": ["project", "name", "payload"],
        "additionalProperties": False,
        "properties": {
            "project": {"type": "string"},
            "name": {"type": "string"},
            "payload": {"type": "object"},
            "comment": {"type": "string"},
        },
    }
)
def create_workflow():
    project, name, payload, comment = (
        request.get_json()["project"],
        request.get_json()["name"],
        request.get_json()["payload"],
        request.get_json().get("comment"),
    )
    if "task_id" not in payload["data"]:
        return jsonify("no task_id in payload"), 400
    if "priority" not in payload["data"]:
        return jsonify("no priority in payload"), 400

    data, _ = _execute_workflow(project, name, payload, comment)
    return jsonify(data), 201


@api_bp.route("/workflows/<workflow_id>/relaunch", methods=["POST"])
@auth.login_required
def relaunch_workflow(workflow_id):
    obj = _get_workflow(workflow_id)
    if hasattr(obj, "comment"):
        comment = obj.comment
    data, _ = _execute_workflow(obj.model_version, obj.task_name, obj.payload, comment)
    return jsonify(data), 201


@api_bp.route("/workflows/<workflow_id>/cancel", methods=["POST"])
@auth.login_required
def cancel_workflow(workflow_id):
    obj = _get_workflow(workflow_id)
    data, _ = _cancel_workflow(obj)
    return jsonify(data), 201


@api_bp.route("/workflows")
@auth.login_required
def list_workflows():
    page = request.args.get("page", type=int, default=1)
    # Convert with_payload arg to boolean, if we encounter an error,
    # ignore and set with_payload to its default value (True)
    # We don't do request.args.get with type=bool because it doesn't seem to work as expected because
    # this most likely casts the string as bool which is not the proper string to bool conversion we need
    try:
        with_payload = strtobool(
            request.args.get("with_payload", type=str, default="True")
        )
    except ValueError:
        with_payload = True
    per_page = request.args.get(
        "per_page", type=int, default=app.config["WORKFLOWS_PER_PAGE"]
    )
    workflows = Workflow.query.order_by(Workflow.created_at.desc()).paginate(
        page=page, per_page=per_page
    )
    return jsonify([w.to_dict(with_payload=with_payload) for w in workflows.items])


@api_bp.route("/workflows/<workflow_id>")
@auth.login_required
def get_workflow(workflow_id):
    workflow = _get_workflow(workflow_id)
    tasks = [t.to_dict() for t in workflow.tasks]

    resp = workflow.to_dict()
    resp.update({"tasks": tasks})
    return jsonify(resp)


@api_bp.route("/definitions")
@auth.login_required
def list_definitions():
    workflow_definitions = []
    for fullname, definition in sorted(cel_workflows.workflows.items()):
        project, name = fullname.split(":", 1)
        workflow_definitions.append(
            {"fullname": fullname, "project": project, "name": name, **definition}
        )
    return jsonify(workflow_definitions)

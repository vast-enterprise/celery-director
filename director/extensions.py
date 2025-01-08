import imp
import json
from pathlib import Path
from json.decoder import JSONDecodeError

import yaml
import redis
import sentry_sdk
from celery import Celery
from flask_sqlalchemy import SQLAlchemy
from flask_json_schema import JsonSchema, JsonValidationError
from flask_migrate import Migrate
from pluginbase import PluginBase
from sqlalchemy.schema import MetaData
from sentry_sdk.integrations import celery as sentry_celery
from sentry_sdk.utils import capture_internal_exceptions
from celery.exceptions import SoftTimeLimitExceeded

from director.exceptions import SchemaNotFound, SchemaNotValid, WorkflowNotFound



def _expand_task_structure(task_structure, group_counter=0, chain_counter=0, group_prefix='GROUP', chain_prefix='CHAIN'):
    if isinstance(task_structure, list):
        expanded_tasks = []
        for task_in_list in task_structure:
            # dict 说明是普通任务或 GROUP
            if isinstance(task_in_list, dict):
                for key, value in task_in_list.items():
                    # 如果是 GROUP 任务, 递归
                    if key == group_prefix:
                        group_name = f"{group_prefix}_{group_counter}"
                        group_counter += 1
                        expanded_group = {
                            group_name: {
                                'type': 'group',
                                'tasks': _expand_task_structure(value, group_counter, chain_counter)
                            }
                        }
                        expanded_tasks.append(expanded_group)
                    else: # 如果是普通任务直接添加, 例如 {"task_1": "condition_task_1"}
                        # 转化为 tuple 方便条件判断 ("task_1", "condition_task_1")
                        (task_name, condtion_name), = task_in_list.items()
                        expanded_tasks.append((task_name, condtion_name))
            # 如果是 list 说明这是一个 chain, 对列表中每个任务递归
            elif isinstance(task_in_list, list):
                chain_name = f"{chain_prefix}_{chain_counter}"
                chain_counter += 1
                expanded_chain = {
                            chain_name: {
                                'type': 'chain',
                                'tasks': _expand_task_structure(task_in_list, group_counter, chain_counter)
                            }
                        }
                expanded_tasks.append(expanded_chain)
            # 如果是其他类型, 只能是字符串, 直接添加, 例如 "render"
            else:
                expanded_tasks.append(task_in_list)
        return expanded_tasks
    return task_structure


def expand_yaml_task_structure(yaml_data):
    expand_yaml = {}
    for task_name, tasks in yaml_data.items():
        # 例如 v2.0-20240919:image_to_model, 下一层即是 tasks
        if isinstance(tasks, dict) and "tasks" in tasks:
            tasks["tasks"] = _expand_task_structure(tasks["tasks"])
            tasks["type"] = "chain"
            expand_yaml[task_name] = tasks
        # 例如 periodic, 下一层是 task 的 list
        else:
            for task in tasks:
                for key, val in task.items():
                    val["tasks"] = _expand_task_structure(val["tasks"])
                    val["type"] = "chain"
                    expand_yaml[f"{task_name}:{key}"] = val
    return expand_yaml


class CeleryWorkflow:
    def __init__(self):
        self.app = None
        self.workflows = None

    def init_app(self, app):
        self.app = app
        self.path = Path(self.app.config["DIRECTOR_HOME"]).resolve() / "workflows.yml"
        with open(self.path) as f:
            self.workflows = expand_yaml_task_structure(yaml.load(f, Loader=yaml.SafeLoader))
        self.import_user_tasks()
        self.read_schemas()

    def get_by_name(self, name):
        workflow = self.workflows.get(name)
        if not workflow:
            raise WorkflowNotFound(f"Workflow {name} not found")
        return workflow

    def get_tasks(self, name):
        return self.get_by_name(name)["tasks"]

    def get_type(self, name):
        try:
            return self.get_by_name(name)["type"]
        except KeyError:
            return "chain"

    def get_hook_task(self, name, hook_name):
        if (
            "hooks" in self.get_by_name(name)
            and hook_name in self.get_by_name(name)["hooks"]
        ):
            return self.get_by_name(name)["hooks"][hook_name]
        return None

    def get_failure_hook_task(self, name):
        return self.get_hook_task(name, "failure")

    def get_success_hook_task(self, name):
        return self.get_hook_task(name, "success")

    def get_queue(self, name):
        try:
            return self.get_by_name(name)["queue"]
        except KeyError:
            return "celery"

    def import_user_tasks(self):
        self.plugin_base = PluginBase(package="director.foobar")

        folder = Path(self.app.config["DIRECTOR_HOME"]).resolve()
        self.plugin_source = self.plugin_base.make_plugin_source(
            searchpath=[str(folder)]
        )

        tasks = Path(folder / "tasks").glob("**/*.py")
        with self.plugin_source:
            for task in tasks:
                if task.stem == "__init__":
                    continue

                name = str(task.relative_to(folder))[:-3].replace("/", ".")
                __import__(
                    self.plugin_source.base.package + "." + name,
                    globals(),
                    {},
                    ["__name__"],
                )

    def read_schemas(self):
        folder = Path(self.app.config["DIRECTOR_HOME"]).resolve()

        for name, conf in self.workflows.items():
            if "schema" in conf:
                path = Path(folder / "schemas" / f"{conf['schema']}.json")

                try:
                    schema = json.loads(open(path).read())
                except FileNotFoundError:
                    raise SchemaNotFound(
                        f"Schema '{conf['schema']}' not found ({path})"
                    )
                except JSONDecodeError as e:
                    raise SchemaNotValid(f"Schema '{conf['schema']}' not valid ({e})")

                self.workflows[name]["schema"] = schema


# Celery Extension
class FlaskCelery(Celery):
    def __init__(self, *args, **kwargs):
        kwargs["include"] = ["director.tasks"]
        super(FlaskCelery, self).__init__(*args, **kwargs)

        if "app" in kwargs:
            self.init_app(kwargs["app"])

    def init_app(self, app):
        self.app = app
        self.conf.update(app.config.get("CELERY_CONF", {}))


# Sentry Extension
class DirectorSentry:
    def __init__(self):
        self.app = None

    def init_app(self, app):
        self.app = app

        if self.app.config["SENTRY_DSN"]:
            sentry_celery._make_event_processor = self.custom_event_processor
            sentry_sdk.init(
                dsn=self.app.config["SENTRY_DSN"],
                integrations=[sentry_celery.CeleryIntegration()],
            )

    def enrich_tags(self, tags, workflow_id, task):
        from director.models.workflows import Workflow

        with self.app.app_context():
            workflow_obj = Workflow.query.filter_by(id=workflow_id).first()
            workflow = {
                "id": str(workflow_obj.id),
                "project": workflow_obj.project,
                "name": str(workflow_obj),
            }

        tags.update(
            {
                "celery_task_name": task.name,
                "director_workflow_id": workflow.get("id"),
                "director_workflow_project": workflow.get("project"),
                "director_workflow_name": workflow.get("name"),
            }
        )
        return tags

    def enrich_extra(self, extra, args, kwargs):
        extra.update({"workflow-payload": kwargs["payload"], "task-args": args})
        return extra

    def custom_event_processor(self, task, uuid, args, kwargs, request=None):
        """
        This function is the same as the original, except that we
        add custom tags and extras about the workflow object.

        Published under a BSD-2 license and available at:
        https://github.com/getsentry/sentry-python/blob/0.16.3/sentry_sdk/integrations/celery.py#L176
        """

        def event_processor(event, hint):
            with capture_internal_exceptions():
                tags = event.setdefault("tags", {})
                tags["celery_task_id"] = uuid
                extra = event.setdefault("extra", {})
                extra["celery-job"] = {
                    "task_name": task.name,
                    "args": args,
                    "kwargs": kwargs,
                }

                # Director custom fields (references are used by Sentry,
                # no need to retrieve the new values)
                self.enrich_tags(tags, kwargs["workflow_id"], task)
                self.enrich_extra(extra, args, kwargs)

            if "exc_info" in hint:
                with capture_internal_exceptions():
                    if issubclass(hint["exc_info"][0], SoftTimeLimitExceeded):
                        event["fingerprint"] = [
                            "celery",
                            "SoftTimeLimitExceeded",
                            getattr(task, "name", task),
                        ]

            return event

        return event_processor


# List of extensions
db = SQLAlchemy(
    metadata=MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
)
migrate = Migrate()
schema = JsonSchema()
cel = FlaskCelery("director")
cel_workflows = CeleryWorkflow()
sentry = DirectorSentry()

redis_client = redis.from_url("redis://127.0.0.1:6379", db="2", decode_responses=True)
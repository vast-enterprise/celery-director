import imp
import sys
import yaml
import hashlib
import importlib
import sentry_sdk
from pathlib import Path
import os, uuid, requests, json
from json.decoder import JSONDecodeError
from celery import Celery
from celery import current_app
from billiard.process import current_process
from celery.exceptions import SoftTimeLimitExceeded
from flask_migrate import Migrate
from flask_json_schema import JsonSchema
from flask_sqlalchemy import SQLAlchemy as _BaseSQLAlchemy
from sqlalchemy.schema import MetaData
import confluent_kafka
from confluent_kafka import KafkaException
from sentry_sdk.utils import capture_internal_exceptions
from sentry_sdk.integrations import celery as sentry_celery

import redis
from redis.retry import Retry as RetrySync
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError, TimeoutError, BusyLoadingError

from director.exceptions import SchemaNotFound, SchemaNotValid, WorkflowNotFound
config_path = Path(os.getenv("DIRECTOR_CONFIG")).resolve()
sys.path.append(f"{config_path.parent.resolve()}/")
import config
from workers.worker_loader import SubmoduleWorkerLoader


def validate_tasks(task_definition, tasks_config):
    if isinstance(task_definition, dict) and "tasks" not in task_definition:
        raise WorkflowNotFound("no tasks definitions in workflow yaml")

    if not isinstance(task_definition, list):
        task_definition = task_definition["tasks"]

    for task in task_definition:
        if isinstance(task, str):
            # 无条件的任务
            if task not in tasks_config:
                pass
                # 检查 task_name 被取消
                # raise WorkflowSyntaxError(f"task '{task}' is not found in {config.TASKS_CONFIG_PATH}")
        elif isinstance(task, list):
            validate_tasks(task, tasks_config)
        else: # dict
            (task_name, value), = task.items() 
            if task_name == "GROUP":
                validate_tasks(value, tasks_config)
            else: # 有条件的任务
                if task_name not in tasks_config:
                    pass
                    # raise WorkflowSyntaxError(f"task '{task_name}' is not found in {config.TASKS_CONFIG_PATH}")


def format_yaml(yaml_data):
    tasks_config = config.TASKS_CONFIG
    formatted_yaml = {}
    for task_name, val in yaml_data.items():
        # 如果是 periodic 下层是任务 list
        if isinstance(val, list):
            for task in val:
                (sub_task_name, tasks), = task.items() 
                validate_tasks(tasks, tasks_config)
                formatted_yaml[f"{task_name}:{sub_task_name}"] = tasks
        else:
            validate_tasks(val, tasks_config)
            formatted_yaml[task_name] = val
    return formatted_yaml


class CeleryWorkflow:
    def __init__(self):
        self.app = None
        self.workflows = None

    def init_app(self, app):
        self.app = app
        self.path = Path(self.app.config["DIRECTOR_HOME"]).resolve() / "workflows.yml"
        with open(self.path) as f:
            original_yaml = yaml.load(f, Loader=yaml.SafeLoader)
            self.workflows = format_yaml(original_yaml)
        self.import_user_tasks()
        self.read_schemas()

    def get_by_name(self, name):
        workflow = self.workflows.get(name)
        if not workflow:
            raise WorkflowNotFound(f"Workflow {name} not found")
        return workflow

    def get_tasks(self, name):
        return self.get_by_name(name)["tasks"]

    def get_first_task(self, task):
        if isinstance(task, str):
            return task
        elif isinstance(task, list):
            return self.get_first_task(task[0])
        else:
            (task_name, val), = task.items()
            if task_name == "GROUP":
                return self.get_first_task(val[0])
            else:
                return task_name

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
        folder = Path(self.app.config["DIRECTOR_HOME"]).resolve()
        tasks = Path(folder / "tasks").glob("**/*.py")
        for task in tasks:
            if task.stem == "__init__":
                continue
            module_name = f"tasks.{task.stem}"
            module_path = str(task)
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

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


class SQLAlchemy(_BaseSQLAlchemy):
    def apply_pool_defaults(self, app, options):
        options = super().apply_pool_defaults(app, options)
        options["pool_pre_ping"] = True
        return options


# Redis Extension
class RedisClient:
    def __init__(self):
        self.conn = None

    def init_redis(self):
        retry_sync = RetrySync(ExponentialBackoff(), retries=5)
        self.conn = redis.from_url(os.getenv('REDIS_URL'),
                                    password=os.getenv("REDIS_PASSWD"),
                                    retry=retry_sync,
                                    retry_on_error=[ConnectionError, BusyLoadingError, TimeoutError],
                                    db=os.getenv('WORKER_REDIS_DB'),
                                    decode_responses=True
                                )

    def ping(self):
        return self.conn.ping()

    def close_conn(self):
        self.conn.close()

    def get_client(self):
        return self.conn


# Kafka Extension
class KafkaClient:
    def __init__(self):
        self.producer_dict = {}

    @property
    def producer(self):
        p = current_process()
        return self.producer_dict[p.pid]

    def init_kafka(self, kafka_configs):
        p = current_process()
        if p.pid not in self.producer_dict:
            try:
                self.producer_dict[p.pid] = confluent_kafka.Producer(kafka_configs)
                # 在初始化时去拿 partition 数量
                # TODO 如果从数据库读取 topic, 是否在这时拿 partitions
                metadata = self.producer.list_topics(timeout=10)
                self.num_partitions = len(metadata.topics[os.getenv("KAFKA_TOPIC")].partitions)
            except Exception:
                self.num_partitions = 6

    def get_hash_partition(self, task_id):
        hash_object = hashlib.sha256(task_id.encode())
        hash_digest = int(hash_object.hexdigest(), 16)
        return hash_digest % self.num_partitions

    def _decompose_msg(self, msg):
        return {
            "topic": msg.topic(),
            "timestamp": msg.timestamp(),
            "partition": msg.partition(),
            "offset": msg.offset(),
        }

    def _produce_with_callback(self, topic, value, key, partition=None, callback=None):
        def ack(err, msg):
            # if err is not None:
            #     print('Message delivery failed: {}'.format(err))
            # else:
            #     print(f"ack 消息:{value}")
            #     print('Message delivered to {} [{}]'.format(msg.topic(), msg.partition()))
            if callback:
                callback(err, msg)
        try:
            if partition:
                self.producer.produce(topic=topic, value=value, key=key, on_delivery=ack, partition=partition)
            else:
                self.producer.produce(topic=topic, value=value, key=key, on_delivery=ack)
            self.producer.flush()
        except KafkaException as e:
            raise KafkaException(f"Error while producing message: {str(e)}")

    def produce_message(self, message_dict, task_id, topic=None, partition=None):
        message_dict["msg_key"] = str(uuid.uuid4())
        message = json.dumps(message_dict)
        try:
            # 如果指定了 topic 或 partition, 则用指定和默认的
            if topic or partition:
                if not topic:
                    topic = os.getenv("KAFKA_TOPIC")
                if not partition:
                    task_partition = self.get_hash_partition(task_id)
                self._produce_with_callback(topic, message, task_id, partition=task_partition)
            # 如果 topic 和 partition 都没指定, 则用数据库存的
            else:
                try:
                    kafka_dict = current_app.conf.worker_module_kafka
                except Exception:
                    # 以防在 conf 里面 拿不到 kafka_dict
                    p = current_process()
                    if p._parent_pid:
                        kafka_dict = json.loads(os.getenv(f"{p._parent_pid}_kafka_dict"))
                    else:
                        kafka_dict = json.loads(os.getenv(f"{p.pid}_kafka_dict"))
                # 遍历在数据库中的所有 topic
                for topic_in_db, partitions_in_db in kafka_dict.items():
                    # 如果 partitions 是空列表, 则用 task_id 做哈希值找 partition
                    if not partitions_in_db:
                        task_partition = self.get_hash_partition(task_id)
                        self._produce_with_callback(topic_in_db, message, task_id, partition=task_partition)
                    else:
                        # 向每个 partition 都发一份
                        for p in partitions_in_db:
                            self._produce_with_callback(topic_in_db, message, task_id, partition=p)
        except Exception as e:
            print(e)
            return None

    def close(self):
        self.producer.flush()


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
cel = FlaskCelery("director", broker_connection_retry_on_startup=True, loader=SubmoduleWorkerLoader)
cel_workflows = CeleryWorkflow()
sentry = DirectorSentry()

http_session = requests.Session()
redis_client = RedisClient()
print("初始化redis开始")
redis_client.init_redis()
print("初始化redis结束")
kafka_client = KafkaClient()
print("初始化kafka开始")
kafka_client.init_kafka({
        'bootstrap.servers': os.getenv("KAFKA_HOST"),
        'sasl.username':     os.getenv("KAFKA_USERNAME"),
        'sasl.password':     os.getenv("KAFKA_PASSWORD"),
        'acks':              'all',
        'enable.idempotence': True,
        "retries": 3,
        'security.protocol': config.SECURITY_PROTOCOL,
        'sasl.mechanisms':   config.SASL_MECHANISM,
})
print("初始化kafka结束")
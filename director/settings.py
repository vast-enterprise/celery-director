import os, sys
from pathlib import Path
from environs import Env

config_path = Path(os.getenv("DIRECTOR_CONFIG")).resolve()
sys.path.append(f"{config_path.parent.resolve()}/")
import config


HIDDEN_CONFIG = [
    "DIRECTOR_ENABLE_HISTORY_MODE",
    "DIRECTOR_REFRESH_INTERVAL",
    "DIRECTOR_API_URL",
    "DIRECTOR_FLOWER_URL",
    "DIRECTOR_DATABASE_URI",
    "DIRECTOR_DATABASE_POOL_RECYCLE",
    "DIRECTOR_BROKER_URI",
    "DIRECTOR_RESULT_BACKEND_URI",
    "DIRECTOR_SENTRY_DSN",
]


class Config(object):
    def __init__(self, home_path=None, config_path=None):
        if not home_path or not Path(home_path).resolve().exists():
            raise ValueError("environment variable DIRECTOR_HOME is not set correctly")

        env = Env()

        env_path = Path(home_path) / ".env"
        self.DIRECTOR_HOME = str(home_path)

        if config_path:
            if not Path(config_path).resolve().exists():
                raise ValueError(
                    "environment variable DIRECTOR_CONFIG is not set correctly"
                )
            env_path = config_path
            env.read_env(env_path)

        self.ENABLE_HISTORY_MODE = env.bool("DIRECTOR_ENABLE_HISTORY_MODE", False)
        self.ENABLE_CDN = env.bool("DIRECTOR_ENABLE_CDN", True)
        self.STATIC_FOLDER = env.str(
            "DIRECTOR_STATIC_FOLDER", str(Path(self.DIRECTOR_HOME).resolve() / "static")
        )
        self.API_URL = env.str("DIRECTOR_API_URL", "http://127.0.0.1:8000/api")
        self.FLOWER_URL = env.str("DIRECTOR_FLOWER_URL", "http://127.0.0.1:5555")
        self.WORKFLOWS_PER_PAGE = env.int("DIRECTOR_WORKFLOWS_PER_PAGE", 1000)
        self.REFRESH_INTERVAL = env.int("DIRECTOR_REFRESH_INTERVAL", 30000)
        self.REPO_LINK = env.str(
            "DIRECTOR_REPO_LINK", "https://github.com/ovh/celery-director"
        )
        self.DOCUMENTATION_LINK = env.str(
            "DIRECTOR_DOCUMENTATION_LINK", "https://ovh.github.io/celery-director"
        )

        # Authentication
        self.AUTH_ENABLED = env.bool("DIRECTOR_AUTH_ENABLED", False)

        # SQLAlchemy configuration
        self.SQLALCHEMY_TRACK_MODIFICATIONS = False
        self.SQLALCHEMY_DATABASE_URI = env.str("DIRECTOR_DATABASE_URI", "")
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_size": 10,
            "pool_recycle": env.int("DIRECTOR_DATABASE_POOL_RECYCLE", -1),
            "pool_pre_ping": True,
        }
        self.SQLALCHEMY_ENGINE_OPTIONS = SQLALCHEMY_ENGINE_OPTIONS

        # Celery configuration
        self.CELERY_CONF = {
            "task_always_eager": False,
            "broker_url": env.str("DIRECTOR_BROKER_URI", "redis://localhost:6379/0"),
            "result_backend": env.str(
                "DIRECTOR_RESULT_BACKEND_URI", "redis://localhost:6379/1"
            ),
            "broker_transport_options": {
                "master_name": "director",
                # 不能加 sep 因为在 flower 里面是 sep 是写死了的
                # "sep": ":",
                # https://docs.celeryq.dev/projects/kombu/en/v5.2.3/reference/kombu.transport.redis.html#kombu.transport.redis.Transport.Channel.queue_order_strategy
                "queue_order_strategy": "priority",
                "priority_steps": config.PRIORITY_LIST,
            },
            "worker_hijack_root_logger": False,
            "worker_redirect_stdouts": False,
            "enable_utc": True,
            "timezone": "Asia/Shanghai",
            "task_acks_late": True,
            "reject_on_worker_lost": True,
        }

        # Sentry configuration
        self.SENTRY_DSN = env.str("DIRECTOR_SENTRY_DSN", "")

        # Default retention value (number of workflows to keep in the database)
        self.DEFAULT_RETENTION_OFFSET = env.int("DIRECTOR_DEFAULT_RETENTION_OFFSET", -1)

        # Enable Vue debug loading vue.js instead of vue.min.js
        self.VUE_DEBUG = env.bool("DIRECTOR_VUE_DEBUG", False)

        self.NON_SUBMODULE_TASKS_QUEUE_NAME = config.NON_SUBMODULE_TASKS_QUEUE_NAME


class UserConfig(dict):
    """Handle the user configuration"""

    def init(self):
        envs = {
            k.split("DIRECTOR_")[1]: v
            for k, v in os.environ.items()
            if k.startswith("DIRECTOR_") and k not in HIDDEN_CONFIG
        }
        super().__init__(**envs)

    def __getattr__(self, attr):
        try:
            return self[attr]
        except KeyError as e:
            raise AttributeError(f"Config '{e.args[0]}' not defined")

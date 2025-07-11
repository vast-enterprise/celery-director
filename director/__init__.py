import os, sys
import pkgutil
import importlib
from pathlib import Path
from functools import partial
from billiard.process import current_process

config_path = Path(os.getenv("DIRECTOR_CONFIG")).resolve()
sys.path.append(f"{config_path.parent.resolve()}/")
import config

if (
    os.getenv("IS_WORKER")
    and os.getenv("IS_WORKER").lower() == "true"
    and os.getenv(f"{current_process().pid}") in config.TASKS_CONFIG
):
    os.environ["FORKED_BY_MULTIPROCESSING"] = "1"
    if os.name != "nt":
        from billiard import context

        context._force_start_method("spawn")

from celery.schedules import crontab
from flask import Flask, Blueprint, jsonify, request, render_template
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from director.api import api_bp
from director.extensions import (
    FlaskCelery,
    cel,
    cel_workflows,
    db,
    schema,
    sentry,
    migrate,
)
from director.settings import Config, UserConfig
from director.tasks.base import BaseTask
from director.utils import build_celery_schedule
from director.views import view_bp


with open(Path(__file__).parent.resolve() / "VERSION", encoding="utf-8") as version:
    __version__ = version.readline().rstrip()


# Proxify the task method
task = partial(cel.task, base=BaseTask)


# Provide the user config
_config = UserConfig()


# Custom Flask class
class DirectorFlask(Flask):
    static_folder = "static"
    jinja_options = Flask.jinja_options.copy()
    jinja_options.update(
        dict(
            variable_start_string="%%",
            variable_end_string="%%",
        )
    )


# Create the application using a factory
def create_app(
    home_path=os.getenv("DIRECTOR_HOME"),
    config_path=os.getenv("DIRECTOR_CONFIG"),
    celery_app: FlaskCelery = None,
):
    app = DirectorFlask(__name__)
    CORS(app)
    c = Config(home_path, config_path)
    app.config.from_object(c)

    # Init User's config
    _config.init()

    # Init Blueprints
    app.register_blueprint(api_bp)
    app.register_blueprint(view_bp)
    # Init the blueprint for the User's static assets
    app.register_blueprint(
        Blueprint(
            "user",
            __name__,
            static_url_path="/static/user",
            static_folder=str(Path(app.config["STATIC_FOLDER"])),
        )
    )

    # Error handler
    app.register_error_handler(HTTPException, lambda e: http_exception_handler(e))

    # Init extensions
    db.init_app(app)
    db.app = app

    migrate.init_app(
        app=app,
        db=db,
        directory=str(Path(__file__).resolve().parent / "migrations"),
    )
    schema.init_app(app)
    new_cel = cel
    if celery_app is not None:
        new_cel = celery_app
    new_cel.init_app(app)
    cel_workflows.init_app(app)
    sentry.init_app(app)

    # Dict passed to the cleanup function
    retentions = {}

    # Register the periodic tasks for Celery Beat
    for workflow, conf in cel_workflows.workflows.items():
        retention = conf.get("retention", {}).get(
            "offset", app.config["DEFAULT_RETENTION_OFFSET"]
        )

        # A dict is built for the periodic cleaning if the retention is valid
        if retention >= 0:
            retentions[workflow] = retention

        if "periodic" in conf:
            periodic_conf = conf.get("periodic")
            periodic_payload = periodic_conf.get("payload", {})
            schedule_str, schedule_value = build_celery_schedule(
                workflow, periodic_conf
            )
            new_cel.conf.beat_schedule.update(
                {
                    f"periodic-{workflow}-{schedule_str}": {
                        "task": "director.tasks.periodic.execute",
                        "schedule": schedule_value,
                        "args": (
                            workflow,
                            periodic_payload,
                        ),
                        # beat 会把 periodic 的任务推送到下边拿到 queue 里, 5 秒过期
                        "options": {
                            "queue": app.config["NON_SUBMODULE_TASKS_QUEUE_NAME"],
                            "expires": 5,
                        },
                    }
                }
            )

    if len(retentions):
        new_cel.conf.beat_schedule.update(
            {
                "periodic-cleanup": {
                    "task": "director.tasks.periodic.cleanup",
                    # 可以修改 retension 任务的执行频率, 现在是每天凌晨 0 点执行
                    "schedule": crontab(minute=0, hour=0),
                    "args": (retentions,),
                }
            }
        )

    @app.teardown_request
    def session_clear(exception=None):
        db.session.remove()

    return app


def http_exception_handler(error):
    if request.path.startswith("/api"):
        return jsonify(error=str(error.description)), error.code

    return render_template("error.html", error=error), error.code


# Import director's submodules
def import_submodules(package, modules_to_import):
    """
    Import all submodules of a module, recursively, including subpackages.
    """
    if isinstance(package, str):
        package = importlib.import_module(package)
    results = {}

    for loader, full_name, is_pkg in pkgutil.walk_packages(
        package.__path__, package.__name__ + "."
    ):
        name = full_name.split(".")[-1]
        if not name.startswith("_") and not name.startswith("tests"):

            if any(x in package.__name__ for x in modules_to_import) or any(
                x in name for x in modules_to_import
            ):
                results[full_name] = importlib.import_module(full_name)
                if is_pkg:
                    results.update(import_submodules(full_name, modules_to_import))
    return results


import_submodules(__name__, ("api", "models", "tasks", "views"))

import os
import click

from urllib.parse import urlparse

from director.context import pass_ctx


@click.group()
def celery():
    """Celery commands"""


@celery.command(name="beat", context_settings=dict(ignore_unknown_options=True))
@click.option("--dev", "dev_mode", default=False, is_flag=True, type=bool)
@click.argument("beat_args", nargs=-1, type=click.UNPROCESSED)
def beat(dev_mode, beat_args):
    """Start the beat instance"""
    args = [
        "celery",
        "-A",
        "director._auto:cel",
        "beat",
    ]
    if dev_mode:
        args += [
            "--loglevel",
            "INFO",
        ]
    args += list(beat_args)
    os.execvp(args[0], args)


@celery.command("worker", context_settings=dict(ignore_unknown_options=True))
@click.option("--dev", "dev_mode", default=False, is_flag=True, type=bool)
@click.option("--platform", "platform", default="3090", type=str)
@click.argument("worker_args", nargs=-1, type=click.UNPROCESSED)
def worker(dev_mode, platform, worker_args):
    """Start a Celery worker instance"""
    args = [
        "celery",
        "-A",
        "director._auto:cel",
        "worker",
    ]
    if dev_mode:
        args += [
            "--loglevel",
            "INFO",
        ]
    # TODO 传递相应参数
    from director._auto import cel
    cel.conf.worker_platform = platform

    args += list(worker_args)
    os.execvp(args[0], args)


@celery.command(name="flower", context_settings=dict(ignore_unknown_options=True))
@click.argument("flower_args", nargs=-1, type=click.UNPROCESSED)
@pass_ctx
def flower(ctx, flower_args):
    """Start the flower instance"""
    broker = ctx.app.config["CELERY_CONF"]["broker_url"]
    args = ["celery", "-b", broker, "flower"]
    args += list(flower_args)
    os.execvp(args[0], args)

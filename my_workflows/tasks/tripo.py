from director import task
import config

def create_task_function(task_name, time_limit):
    @task(name=task_name, time_limit=time_limit)
    def task_function(*args, **kwargs):
        return task_name
    return task_function

for _task_name in config.tasks.keys():
    _time_limit = config.tasks[_task_name].get("time_limit", 30)
    globals()[_task_name + "_celery_task"] = create_task_function(_task_name, _time_limit)

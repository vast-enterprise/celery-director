from director import task



@task(name="clean_expired_tasks", time_limit=180)
def clean_expired_tasks(*args, **kwargs):
    return "clean_expired_tasks"

@task(name="upload_queue_info", time_limit=180)
def upload_queue_info(*args, **kwargs):
    return "upload_queue_info"
from director import task
from director.extensions import redis_client



@task(name="translate", time_limit=180)
def translate(*args, **kwargs):
    redis_client.set('foo2', 'bar2')
    return "translate"

@task(name="text2image_pose", time_limit=180)
def text2image_pose(*args, **kwargs):
    return "text2image_pose"

@task(name="text2image", time_limit=180)
def text2image(*args, **kwargs):
    return "text2image"

@task(name="image2image", time_limit=180)
def image2image(*args, **kwargs):
    return "image2image"

@task(name="caption", time_limit=180)
def caption(*args, **kwargs):
    return "caption"

@task(name="image2model", time_limit=180)
def image2model(*args, **kwargs):
    return "image2model"

@task(name="postprocess_stylize", time_limit=180)
def postprocess_stylize(*args, **kwargs):
    return "postprocess_stylize"

@task(name="texture", time_limit=180)
def texture(*args, **kwargs):
    return "texture"

@task(name="pbr", time_limit=180)
def pbr(*args, **kwargs):
    return "pbr"

@task(name="diffuse2normal", time_limit=180)
def diffuse2normal(*args, **kwargs):
    return "diffuse2normal"

@task(name="project2model", time_limit=180)
def project2model(*args, **kwargs):
    return "project2model"

@task(name="render", time_limit=180)
def render(*args, **kwargs):
    return "render"
# initialize a working context

from director import create_app

app = create_app()
# 更新上下文为数据库
ctx = app.app_context()
ctx.push()

from director.extensions import cel
# 确保 Celery 知道应用上下文
cel.conf.update(app.config)

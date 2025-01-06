FROM python:3.11-alpine
RUN apk add --no-cache shadow
WORKDIR /app

COPY director/ ./director/
COPY my_workflows/ ./my_workflows/
COPY requirements.txt ./requirements.txt

RUN pip install -r requirements.txt

# 跟上边 workflow 的文件夹名称一致
ENV DIRECTOR_HOME=/app/my_workflows

ARG UID=10001
RUN useradd --system \
    --uid "${UID}" \
    --create-home \
    --home-dir /var/app \
    --shell /sbin/nologin \
    --comment "Algo Server Runner" \
    appuser

USER appuser
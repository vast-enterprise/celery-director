FROM ccr-23gxup9u-vpc.cnc.bj.baidubce.com/common/python:3.11.9-bullseye
WORKDIR /app
COPY . /app/
COPY requirements.txt /app
RUN pip install -r requirements.txt

ARG UID=10001
RUN useradd --system \
    --uid "${UID}" \
    --create-home \
    --home-dir /var/app \
    --shell /sbin/nologin \
    --comment "Training Server Runner" \
    appuser

USER appuser
ENTRYPOINT [ "python3", "main.py" ]
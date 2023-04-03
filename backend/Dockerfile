FROM python:3.11
WORKDIR /app/

ENV PYTHONUNBUFFERED=yes

RUN apt-get update -y
RUN apt-get install cmake -y

COPY ./requirements.txt /app/

RUN pip install -r requirements.txt

COPY ./log_conf.json /app/
COPY ./mypy.ini /app/

COPY ./src/ /app/src/

RUN mypy src --config-file /app/mypy.ini

WORKDIR /app/src/
CMD uvicorn main:app --host 0.0.0.0 --port 80 --use-colors --log-config /app/log_conf.json

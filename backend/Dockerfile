FROM python:3.11-slim

WORKDIR /app

# tzdata: SQLite CURRENT_TIMESTAMP 用 UTC，容器内统一时区为 Asia/Shanghai
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && ln -sf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# 应用代码 + GPU 服务器端 worker 脚本（远程引擎自动部署用）
COPY app ./app
COPY inference-worker ./inference-worker

RUN mkdir -p /app/data
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

#!/usr/bin/env bash
# 一键把 TimesFM 推理 worker 部署到 GPU 服务器（默认 192.168.0.109）
# 用法: ./scripts/deploy_worker.sh [host] [port]
set -e

HOST="${1:-192.168.0.109}"
PORT="${2:-22}"
REMOTE_DIR="${TIMESFM_REMOTE_DIR:-/data/work/timesfm-3/stock_worker}"
REMOTE_PY="${TIMESFM_REMOTE_PYTHON:-/data/work/timesfm-3/.venv/bin/python}"

echo "==> 部署 worker 到 ${HOST}:${PORT}:${REMOTE_DIR}"
ssh -p "$PORT" root@"$HOST" "mkdir -p ${REMOTE_DIR}"
scp -P "$PORT" backend/inference-worker/infer_service.py "root@${HOST}:${REMOTE_DIR}/"

echo "==> 冒烟测试（加载模型约 20s，单次预测 <1s）"
ssh -p "$PORT" root@"$HOST" "cd ${REMOTE_DIR} && echo '{\"id\":1,\"context\":[1,2,3,4,5,6,7,8,9,10],\"horizon\":3,\"past_only\":null,\"return_quantiles\":false,\"make_positive\":true}' | ${REMOTE_PY} -u infer_service.py"

echo "==> 完成。后端 INFERENCE_MODE=auto|remote 时将自动连接该 worker。"

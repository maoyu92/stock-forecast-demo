#!/bin/bash
# A股 TimesFM 预测 Demo 启动脚本
cd "$(dirname "$0")"

# 使用独立 venv（PyTorch 2.11 + CUDA 12.8，支持 RTX 5070 Ti）
source "$(dirname "$0")/venv/bin/activate"

echo "🚀 启动 A股 TimesFM 预测 Demo..."
echo "📍 访问地址: http://localhost:8501"
echo ""

streamlit run app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false

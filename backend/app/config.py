"""应用配置 —— 全部通过环境变量覆盖，Docker 友好"""
import os
from pathlib import Path

# 项目根目录（backend/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# SQLite 数据库文件
DATABASE_PATH = os.environ.get("DATABASE_PATH", str(PROJECT_ROOT / "data" / "stock_forecast.db"))

# 推理模式: auto | remote | local | mock
#   auto   = 优先远程 GPU(SSH)，不可用则本地 timesfm，最后 mock
#   remote = 强制远程（不可用时报错）
#   local  = 强制本地（未安装 timesfm 时报错）
#   mock   = 模拟预测（演示/无 GPU 环境）
INFERENCE_MODE = os.environ.get("INFERENCE_MODE", "auto")

# 远程 GPU 服务器（局域网 TimesFM 推理机）
TIMESFM_SSH_HOST = os.environ.get("TIMESFM_SSH_HOST", "192.168.0.109")
TIMESFM_SSH_PORT = int(os.environ.get("TIMESFM_SSH_PORT", "22"))
TIMESFM_SSH_USER = os.environ.get("TIMESFM_SSH_USER", "root")
TIMESFM_SSH_KEY_PATH = os.environ.get("TIMESFM_SSH_KEY_PATH", "")
TIMESFM_SSH_PASSWORD = os.environ.get("TIMESFM_SSH_PASSWORD", "")  # 备用：密码认证
# 服务器上 worker 所在目录与 Python 解释器
TIMESFM_REMOTE_DIR = os.environ.get("TIMESFM_REMOTE_DIR", "/data/work/timesfm-3/stock_worker")
TIMESFM_REMOTE_PYTHON = os.environ.get("TIMESFM_REMOTE_PYTHON", "/data/work/timesfm-3/.venv/bin/python")

# TimesFM 模型 ID（本地模式使用）
TIMESFM_MODEL_ID = os.environ.get("TIMESFM_MODEL_ID", "google/timesfm-3.0-pytorch")

# 数据缓存 TTL（秒）
STOCK_LIST_CACHE_TTL = int(os.environ.get("STOCK_LIST_CACHE_TTL", "21600"))  # 6h
KLINE_CACHE_TTL = int(os.environ.get("KLINE_CACHE_TTL", "600"))              # 10min
SCREEN_SNAPSHOT_TTL = int(os.environ.get("SCREEN_SNAPSHOT_TTL", "300"))      # 选股全市场快照 5min

# 本地历史K线仓库（通达信式"先下载数据、再本地选股"）
SYNC_WORKERS = int(os.environ.get("SYNC_WORKERS", "4"))          # baostock 多进程并发数
HIST_SYNC_MIN_BARS = int(os.environ.get("HIST_SYNC_MIN_BARS", "60"))  # 少于该行数的股票不入库（次新股）
# 可选：通达信本地 vipdoc 目录（如 C:\new_tdx\vipdoc）。设置后同步时优先读取其 .day 文件（不复权）
TDX_VIPDOC_PATH = os.environ.get("TDX_VIPDOC_PATH", "")

# 预测参数边界
HORIZON_OPTIONS = [1, 3, 7, 14, 30]
CONTEXT_OPTIONS = [60, 120, 180, 250, 365, 512]
MAX_CONTEXT = 15360  # TimesFM 3.0 全局上限

# 置信带分位（TimesFM 输出 9 分位 0.1~0.9）
QUANTILE_LOW_IDX = 1   # 0.2
QUANTILE_HIGH_IDX = 7  # 0.8

PERIODS = {
    "daily": {"label": "日线", "freq": "d", "calendar_days": 1},
    "weekly": {"label": "周线", "freq": "w", "calendar_days": 7},
    "monthly": {"label": "月线", "freq": "m", "calendar_days": 30},
}

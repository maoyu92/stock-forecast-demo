"""项目配置"""
from dataclasses import dataclass, field
from typing import List

# 预测步长选项
HORIZON_OPTIONS = [7, 16, 32, 64]

# 上下文长度选项
CONTEXT_OPTIONS = [30, 60, 90, 180, 365, 512, 1024]

# 数据频率选项
FREQUENCY_MAP = {
    "日线": "daily",
    "周线": "weekly",
    "月线": "monthly",
    "1分钟": "1",
    "5分钟": "5",
    "15分钟": "15",
    "30分钟": "30",
    "60分钟": "60",
}

# akshare 频率映射
AKSHARE_FREQ_MAP = {
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
    "1": "1",
    "5": "5",
    "15": "15",
    "30": "30",
    "60": "60",
}

# TimesFM 模型配置
@dataclass
class ModelConfig:
    model_id: str = "google/timesfm-2.5-200m-pytorch"
    max_context: int = 2048
    max_horizon: int = 64
    backend: str = "gpu"

# 默认预测配置
@dataclass
class ForecastConfig:
    horizon: int = 7
    context_len: int = 90
    frequency: str = "daily"
    stock_code: str = "000001"
    stock_name: str = "平安银行"

# 数据库路径
DB_PATH = "data/forecast_history.db"

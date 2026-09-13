"""Pydantic 请求模型"""
from typing import Any, Optional

from pydantic import BaseModel, Field


class FactorSpec(BaseModel):
    code: str
    name: Optional[str] = None


class PredictRequest(BaseModel):
    code: str = Field(..., description="目标证券代码，如 sh.601601")
    name: Optional[str] = None
    period: str = Field("daily", description="daily / weekly / monthly")
    horizon: int = Field(7, ge=1, le=512)
    context_len: int = Field(180, ge=30, le=15360)
    factors: list[FactorSpec] = Field(default_factory=list, description="多因子列表（可空=单变量）")
    save: bool = True


class FactorGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    target_code: str
    target_name: Optional[str] = None
    factors: list[FactorSpec] = Field(default_factory=list)


class ScreenRunRequest(BaseModel):
    strategy_id: str = Field(..., description="选股策略 id，见 GET /api/screener/strategies")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数（缺省用各策略默认值）")
    save: bool = Field(True, description="是否保存本次选股结果")


class ScreenMultiRunRequest(BaseModel):
    strategy_ids: list[str] = Field(..., min_length=1, description="参与组合的公式策略 id 列表")
    combine: str = Field("or", description="组合方式：or=并集(任一命中) / and=交集(全部命中)")
    exclude_ids: list[str] = Field(default_factory=list, description="排除策略 id：命中的股票从结果剔除")
    params: dict[str, Any] = Field(default_factory=dict,
                                   description="公共参数覆盖（within_n/board/exclude_st/min_amount），"
                                               "各策略专属参数用默认值")
    save: bool = Field(True, description="是否保存本次选股结果")


class PortfolioBacktestRequest(BaseModel):
    months: float = Field(12, ge=1, le=24)
    group_ids: list[str] = Field(default_factory=list, description="留空=全部启用组")
    mode: str = Field("both", description="individual / combined / both")
    initial_cash: float = Field(1_000_000, gt=0)
    max_positions: int = Field(8, ge=1, le=50)
    max_exposure: float = Field(0.95, ge=0.1, le=1)
    fee_rate: float = Field(0.0003, ge=0, le=0.01)
    stamp_tax_rate: float = Field(0.0005, ge=0, le=0.01)
    slippage: float = Field(0.001, ge=0, le=0.05)
    market_timing_enabled: bool = True
    market_breadth_threshold: float = Field(0.45, ge=0, le=1)
    board: str = Field("全部", description="全部 / 主板 / 创业板 / 科创板")
    exclude_st: bool = True
    limit: Optional[int] = Field(None, ge=1, le=5300)
    save: bool = True

"""策略组元数据与注册表"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class StrategyGroupDef:
    id: str
    name: str
    description: str
    entry_ids: list[str]
    entry_combine: str = "or"
    risk_ids: list[str] = field(default_factory=list)
    exit_kind: str = "trend"
    # 仓位/风控
    max_positions: int = 2
    max_weight: float = 0.15
    risk_per_trade: float = 0.006
    hard_stop_pct: float = 0.08
    stop_atr_mult: float = 3.0
    trail_drawdown_pct: float = 0.12
    max_holding_days: int = 30
    time_exit_min_return_pct: float = 0.0
    min_amount: float = 1.0  # 亿元
    requires_forecast: bool = False
    enabled: bool = True

    def schema(self) -> dict:
        return asdict(self)


_REGISTRY: dict[str, StrategyGroupDef] = {}


def register(group: StrategyGroupDef) -> None:
    if group.id in _REGISTRY:
        raise ValueError(f"策略组 id 重复: {group.id}")
    _REGISTRY[group.id] = group


def list_groups() -> list[dict]:
    return [g.schema() for g in _REGISTRY.values()]


def get_group(group_id: str) -> StrategyGroupDef:
    if group_id not in _REGISTRY:
        raise ValueError(f"未知策略组: {group_id}")
    return _REGISTRY[group_id]

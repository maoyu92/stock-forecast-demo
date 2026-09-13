"""选股策略注册表 —— 每个选股方法注册为一个 StrategyDef

新增选股方法：新建模块，定义 StrategyDef 并调用 register()，
再在包 __init__.py 中 import 该模块即可，前端参数表单按 schema 动态渲染。
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional


@dataclass
class ParamDef:
    """策略参数定义（前端据此渲染表单）"""
    key: str
    label: str
    type: str = "number"            # number | bool | select
    default: Any = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    unit: str = ""
    description: str = ""
    options: Optional[list[dict]] = None   # select 类型的可选项 [{"value","label"}]

    def schema(self) -> dict:
        return asdict(self)


@dataclass
class StrategyDef:
    id: str
    name: str
    description: str
    source: str                     # 方法出处说明
    params: list[ParamDef] = field(default_factory=list)
    # 编排函数：接收 (params, ctx) 返回结果列表，由各策略模块实现
    run: Optional[Callable[[dict, dict], list[dict]]] = None
    # ---- 公式型策略（kind="formula"）----
    kind: str = "snapshot"          # snapshot=实时快照两段式 / formula=通达信公式引擎
    category: str = ""              # 策略分类（前端分组显示）
    formula: str = ""               # 通达信公式源码（kind=formula 时必填）
    detail_tpl: str = ""            # 命中详情模板，如 "MA5={M5:.2f}"
    strength: str = ""              # 强度公式（可选，用于结果排序打分）

    def schema(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "kind": self.kind,
            "category": self.category,
            "formula": self.formula,
            "params": [p.schema() for p in self.params],
        }


_registry: dict[str, StrategyDef] = {}


def register(strategy: StrategyDef) -> None:
    if strategy.id in _registry:
        raise ValueError(f"策略 id 重复: {strategy.id}")
    _registry[strategy.id] = strategy


def get_strategy(strategy_id: str) -> StrategyDef:
    if strategy_id not in _registry:
        raise ValueError(f"未知的选股策略: {strategy_id}")
    return _registry[strategy_id]


def list_strategies() -> list[dict]:
    return [s.schema() for s in _registry.values()]


def get_param(params: dict, pdef: ParamDef) -> Any:
    """取参数值：用户传入优先，缺省回落到定义默认值并做范围裁剪"""
    if pdef.type == "select":
        v = params.get(pdef.key, pdef.default)
        opts = {o["value"] for o in (pdef.options or [])}
        return v if v in opts else pdef.default
    v = params.get(pdef.key, pdef.default)
    if pdef.type == "bool":
        return bool(v) if v is not None else bool(pdef.default)
    try:
        v = float(v) if v is not None else float(pdef.default)
    except (TypeError, ValueError):
        v = float(pdef.default)
    if pdef.minimum is not None:
        v = max(pdef.minimum, v)
    if pdef.maximum is not None:
        v = min(pdef.maximum, v)
    return v

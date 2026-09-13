"""策略组注册入口"""
from __future__ import annotations

from .base import StrategyGroupDef, get_group, list_groups, register
from . import indicators
from . import definitions  # noqa: F401  # 触发注册


__all__ = [
    "StrategyGroupDef", "get_group", "list_groups", "register", "indicators",
]

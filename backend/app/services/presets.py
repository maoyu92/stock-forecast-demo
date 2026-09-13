"""内置多因子预设（覆盖 4 只测试股票）+ 可选 ETF 因子池"""
from typing import Optional

# 预设因子：目标股票 + 相关个股（全历史可用）+ 沪深300 指数
BUILTIN_PRESETS: list[dict] = [
    {
        "name": "中国太保",
        "target": {"code": "sh.601601", "name": "中国太保"},
        "factors": [
            {"code": "sh.601318", "name": "中国平安"},
            {"code": "sh.601336", "name": "新华保险"},
            {"code": "sh.000300", "name": "沪深300指数"},
        ],
        "note": "保险同业联动 + 大盘基准",
    },
    {
        "name": "长江电力",
        "target": {"code": "sh.600900", "name": "长江电力"},
        "factors": [
            {"code": "sh.600886", "name": "国投电力"},
            {"code": "sh.600025", "name": "华能水电"},
            {"code": "sh.000300", "name": "沪深300指数"},
        ],
        "note": "水电同业联动 + 大盘基准",
    },
    {
        "name": "工商银行",
        "target": {"code": "sh.601398", "name": "工商银行"},
        "factors": [
            {"code": "sh.601939", "name": "建设银行"},
            {"code": "sh.601288", "name": "农业银行"},
            {"code": "sh.000300", "name": "沪深300指数"},
        ],
        "note": "国有大行联动 + 大盘基准",
    },
    {
        "name": "伊利股份",
        "target": {"code": "sh.600887", "name": "伊利股份"},
        "factors": [
            {"code": "sh.600597", "name": "光明乳业"},
            {"code": "sz.000876", "name": "新希望"},
            {"code": "sh.000300", "name": "沪深300指数"},
        ],
        "note": "乳业/食品同业联动 + 大盘基准",
    },
]

# 常用 ETF（baostock 2026 起有数据，历史不足时自动用新浪补全）
ETF_QUICK_PICKS: list[dict] = [
    {"code": "sh.510300", "name": "沪深300ETF"},
    {"code": "sh.512800", "name": "银行ETF"},
    {"code": "sh.515170", "name": "食品饮料ETF"},
    {"code": "sz.159611", "name": "电力ETF"},
    {"code": "sh.512000", "name": "券商ETF"},
    {"code": "sh.512690", "name": "酒ETF"},
]


def find_preset(name: str) -> Optional[dict]:
    for p in BUILTIN_PRESETS:
        if p["name"] == name:
            return p
    return None


def find_preset_by_code(code: str) -> Optional[dict]:
    for p in BUILTIN_PRESETS:
        if p["target"]["code"] == code:
            return p
    return None

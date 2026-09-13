"""板块行业服务：行业分类 + 指数成分股缓存 → 自动关联板块龙头因子

数据来源（baostock）：
- query_stock_industry()  证监会行业分类（约 5500 行）
- query_hs300_stocks()    沪深300 成分
- query_sz50_stocks()     上证50 成分（大盘龙头优先级更高）
内存缓存 + SQLite 持久化（baostock 不可用时用旧数据兜底）。
"""
import logging
import threading
import time
from typing import Optional

from .. import db
from . import datasource
from .presets import find_preset_by_code

log = logging.getLogger("industry")

_TTL = 24 * 3600
_lock = threading.Lock()

# 内存缓存
_industry: Optional[dict[str, str]] = None        # code -> 行业名（如 J68保险业）
_hs300: list[tuple[str, str]] = []                # [(code, name)] 按成分顺序
_sz50: list[tuple[str, str]] = []
_loaded_at: float = 0.0


def _fetch_all() -> None:
    import baostock as bs
    global _industry, _hs300, _sz50, _loaded_at
    with datasource._bs_lock:
        for attempt in (1, 2):
            try:
                datasource._bs_ensure_login()

                ind: dict[str, str] = {}
                rs = bs.query_stock_industry()
                while (rs.error_code == "0") and rs.next():
                    _, code, _, industry, _ = rs.get_row_data()
                    ind[code] = industry
                if not ind:
                    raise RuntimeError("行业分类为空")

                def members(q):
                    rs = q()
                    out = []
                    while (rs.error_code == "0") and rs.next():
                        _, code, name = rs.get_row_data()
                        out.append((code, name))
                    return out

                hs300 = members(bs.query_hs300_stocks)
                sz50 = members(bs.query_sz50_stocks)
                if not hs300:
                    raise RuntimeError("沪深300成分查询失败")

                _industry, _hs300, _sz50 = ind, hs300, sz50
                _loaded_at = time.time()
                _persist(ind, hs300, sz50)
                return
            except Exception:
                datasource._bs_reset()
                if attempt == 2:
                    raise


def _persist(ind: dict[str, str], hs300: list, sz50: list) -> None:
    try:
        conn = db.get_conn()
        conn.execute("DROP TABLE IF EXISTS stock_industry")
        conn.execute("CREATE TABLE stock_industry (code TEXT PRIMARY KEY, industry TEXT)")
        conn.executemany("INSERT OR REPLACE INTO stock_industry VALUES (?,?)", ind.items())
        conn.execute("DROP TABLE IF EXISTS index_members")
        conn.execute("CREATE TABLE index_members (list_name TEXT, code TEXT, name TEXT)")
        conn.executemany("INSERT INTO index_members VALUES ('hs300',?,?)", hs300)
        conn.executemany("INSERT INTO index_members VALUES ('sz50',?,?)", sz50)
        conn.commit()
    except Exception as e:
        log.warning("行业数据写库失败: %s", e)


def _load_from_db() -> None:
    global _industry, _hs300, _sz50, _loaded_at
    try:
        conn = db.get_conn()
        ind = {r["code"]: r["industry"] for r in
               conn.execute("SELECT code, industry FROM stock_industry")}
        hs300 = [(r["code"], r["name"]) for r in conn.execute(
            "SELECT code, name FROM index_members WHERE list_name='hs300'")]
        sz50 = [(r["code"], r["name"]) for r in conn.execute(
            "SELECT code, name FROM index_members WHERE list_name='sz50'")]
        if ind and hs300:
            _industry, _hs300, _sz50 = ind, hs300, sz50
            _loaded_at = time.time()
    except Exception as e:
        log.warning("行业数据读库失败: %s", e)


def _ensure_loaded() -> None:
    global _loaded_at
    with _lock:
        if _industry is not None and time.time() - _loaded_at < _TTL:
            return
        try:
            _fetch_all()
        except Exception as e:
            log.warning("行业数据刷新失败: %s", e)
            if _industry is None:
                _load_from_db()


def industry_of(code: str) -> Optional[str]:
    _ensure_loaded()
    return (_industry or {}).get(code)


# 展示用：去掉 "J68"/"C15" 这类前缀
def _pretty(industry: Optional[str]) -> Optional[str]:
    if not industry:
        return None
    body = industry[3:] if len(industry) > 3 and industry[1].isdigit() else industry
    return body or industry


def auto_factors(code: str) -> dict:
    """选股后自动关联多因子：内置预设 / 同板块龙头 + 沪深300 / 仅沪深300"""
    # 1) 内置预设（4 只测试股票走人工校准的因子组合）
    preset = find_preset_by_code(code)
    industry = _pretty(industry_of(code))
    if preset:
        return {
            "industry": industry,
            "factors": preset["factors"],
            "source": "builtin",
            "note": f"内置预设因子：{preset['note']}",
        }

    # 2) 自动关联：同板块龙头（上证50 优先，其次沪深300 成分）+ 沪深300 指数
    _ensure_loaded()
    industry_raw = (_industry or {}).get(code)
    if not industry_raw:
        return {
            "industry": None,
            "factors": [{"code": "sh.000300", "name": "沪深300指数"}],
            "source": "index_only",
            "note": "未识别到板块（ETF/指数等），仅关联沪深300指数",
        }

    def is_leader(c: str) -> bool:
        return c != code and (_industry or {}).get(c) == industry_raw

    # 上证50 成分最像"龙头"，优先；不足再按成分顺序补沪深300
    leaders = [c for c in _sz50 if is_leader(c[0])]
    seen = {c for c, _ in leaders}
    leaders += [c for c in _hs300 if is_leader(c[0]) and c[0] not in seen]
    # 去重并最多取 2 个龙头
    dedup: list[tuple[str, str]] = []
    got = set()
    for c, n in leaders:
        if c not in got:
            dedup.append((c, n))
            got.add(c)
    leaders = dedup[:2]

    factors = [{"code": c, "name": n} for c, n in leaders]
    factors.append({"code": "sh.000300", "name": "沪深300指数"})
    note = ("已自动关联：同板块龙头（上证50/沪深300成分）+ 沪深300指数"
            if leaders else "同板块暂无上证50/沪深300成分股，仅关联沪深300指数")
    return {"industry": industry, "factors": factors, "source": "auto", "note": note}

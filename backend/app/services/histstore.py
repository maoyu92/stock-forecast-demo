"""本地历史K线仓库 —— 通达信式"先下载数据、本地选股"

设计：
- 全市场 A 股日K（前复权）落在 SQLite `kline_daily`，与通达信"下载盘后数据"同理；
- 同步用 ProcessPoolExecutor（baostock 单连接单进程，多进程各持登录）；
- 增量更新（update）：只抓 last_date 前推 12 天到今天，替换该区间行；重叠窗口价格
  对不上说明期间发生过除权（前复权基准整体漂移），自动把该股票加入二次整窗重下；
- 全量重下（full）：整窗抓取替换；
- 通达信本地 vipdoc（TDX_VIPDOC_PATH）优先级最高：有本地 .day 文件且行数更全时直接用。
"""
import logging
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd

from .. import config
from . import tdxfile

log = logging.getLogger("histstore")

_FIELDS = "date,open,high,low,close,volume,amount"
_OVERLAP_DAYS = 12          # 增量更新向前重叠的天数（也用于除权漂移检测）
_CHUNK = 40                 # 每个进程任务处理的股票数
_DRIFT_TOL = 0.001          # 重叠区收盘价相对差异容限（0.1%）

# ---------- 同步任务状态（进程内） ----------
_sync_lock = threading.Lock()
_sync_state: dict = {"running": False, "phase": "", "done": 0, "total": 0,
                     "ok": 0, "failed": 0, "refetched": 0, "errors": [],
                     "started_at": None, "finished_at": None, "mode": None}


def sync_state() -> dict:
    with _sync_lock:
        return dict(_sync_state)


def _set_state(**kw) -> None:
    with _sync_lock:
        _sync_state.update(kw)


_NAME_MAP: dict[str, str] = {}

# ---------- 子进程工作函数（Windows spawn，需模块级可 pickle） ----------

_TASK_TIMEOUT_S = 300   # 单批次看门狗：超时强制结束 worker（由父进程重建池重试）

def _bs_init() -> None:
    """worker 进程初始化：登录 baostock（每进程一次，后续批次复用会话）"""
    import faulthandler
    faulthandler.enable()
    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")


def _bs_watchdog() -> None:
    import os
    os._exit(1)  # 看门狗到期：硬退出当前 worker，父进程会重建进程池


def bs_fetch_chunk(args: tuple) -> tuple[str | None, list[tuple], dict[str, str]]:
    """worker：抓取一批股票的日K（复用 initializer 登录的会话）。

    返回 (全局错误或 None, 数据行 [(code,date,o,h,l,c,v,amt)...], {code: 错误})
    """
    import faulthandler
    import threading
    import baostock as bs

    codes, start, end = args
    watchdog = threading.Timer(_TASK_TIMEOUT_S, _bs_watchdog)
    watchdog.daemon = True
    watchdog.start()

    rows: list[tuple] = []
    failed: dict[str, str] = {}
    try:
        for code in codes:
            try:
                rs = bs.query_history_k_data_plus(
                    code, _FIELDS, start_date=start, end_date=end,
                    frequency="d", adjustflag="2")  # 2=前复权
                got = []
                while (rs.error_code == "0") and rs.next():
                    got.append(rs.get_row_data())
                if rs.error_code != "0":
                    # 会话可能失效 → 重登一次再试
                    lg = bs.login()
                    if lg.error_code != "0":
                        raise RuntimeError(f"re-login 失败: {lg.error_msg}")
                    rs = bs.query_history_k_data_plus(
                        code, _FIELDS, start_date=start, end_date=end,
                        frequency="d", adjustflag="2")
                    got = []
                    while (rs.error_code == "0") and rs.next():
                        got.append(rs.get_row_data())
                    if rs.error_code != "0":
                        raise RuntimeError(rs.error_msg)
                for r in got:
                    try:
                        o, h, l, c = float(r[1]), float(r[2]), float(r[3]), float(r[4])
                        if c <= 0:
                            continue
                        rows.append((code, r[0], o, h, l, c,
                                     float(r[5] or 0), float(r[6] or 0)))
                    except (TypeError, ValueError):
                        continue
            except Exception as e:  # noqa: BLE001 —— 单只失败不阻断
                failed[code] = f"{type(e).__name__}: {e}"
        return None, rows, failed
    finally:
        watchdog.cancel()


# ---------- 股票清单 ----------

def _fetch_universe() -> pd.DataFrame:
    """全部 A 股清单（沪深主板/创业板/科创板，排除指数与 ETF/北交所）"""
    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
    try:
        rs = bs.query_stock_basic()
        rows = []
        while (rs.error_code == "0") and rs.next():
            rows.append(rs.get_row_data())
        df = pd.DataFrame(rows, columns=rs.fields)
        df = df[(df["type"] == "1") & (df["status"] == "1")]
        df = df[df["code"].str.startswith(("sh.", "sz."))]
        return pd.DataFrame({"code": df["code"].values, "name": df["code_name"].values})
    finally:
        try:
            bs.logout()
        except Exception:  # noqa: BLE001
            pass


# ---------- 写库与除权漂移检测 ----------

def _stock_name(code: str) -> str:
    return _NAME_MAP.get(code, "")


def _write_stock(conn, code: str, recs: list[tuple], delete_from: str) -> tuple[bool, str]:
    """写入一只股票：删除 delete_from 日期之后的旧行再插入（保留更早历史）。

    新股且行数不足（次新/数据异常）不入库；已入库的股票即使本轮只抓到少数几行
    （如长期停牌后复牌）也要把新行合并进去。
    """
    if not recs:
        return False, "无数据"
    existing = conn.execute(
        "SELECT last_date FROM kline_meta WHERE code=?", (code,)).fetchone()
    if len(recs) < config.HIST_SYNC_MIN_BARS and not existing:
        return False, f"行数不足({len(recs)})"
    conn.execute("DELETE FROM kline_daily WHERE code=? AND date>=?", (code, delete_from))
    conn.executemany(
        "INSERT OR REPLACE INTO kline_daily VALUES (?,?,?,?,?,?,?,?)",
        [(code, *rec) for rec in recs])
    lo, hi, n = conn.execute(
        "SELECT MIN(date), MAX(date), COUNT(*) FROM kline_daily WHERE code=?",
        (code,)).fetchone()
    conn.execute(
        "INSERT OR REPLACE INTO kline_meta (code,name,first_date,last_date,rows,updated_at)"
        " VALUES (?,?,?,?,?,?)",
        (code, _stock_name(code), lo, hi, n, datetime.now().isoformat(timespec="seconds")))
    return True, ""


def _detect_drift(conn, code: str, recs: list[tuple]) -> bool:
    """重叠区收盘价是否与库中已有值不一致（除权导致前复权基准漂移）"""
    stored = dict(conn.execute(
        "SELECT date, close FROM kline_daily WHERE code=? AND date>=? AND date<=?",
        (code, recs[0][0], recs[-1][0])).fetchall())
    if not stored:
        return False
    diff = sum(1 for d, _o, _h, _l, c, _v, _a in recs
               if d in stored and abs(c - stored[d]) > max(_DRIFT_TOL * stored[d], 0.005))
    return diff >= 3


def _run_chunks(plans: list[tuple[str, str]], end: str,
                allow_drift_refetch: bool) -> tuple[int, int, list[str], list[str]]:
    """分批经进程池抓取并写库。返回 (ok, fail, 错误样本, 漂移需整窗重下的股票)

    健壮性设计：worker 卡死（看门狗硬退出）导致 BrokenProcessPool 时，
    重建进程池并把未完成批次重新入队（最多重试 3 轮）。
    """
    from .. import db
    from concurrent.futures import BrokenExecutor

    ok = fail = 0
    err_samples: list[str] = []
    drifted: list[str] = []
    all_chunks = [plans[i:i + _CHUNK] for i in range(0, len(plans), _CHUNK)]
    tdx_root = tdxfile.vipdoc_root()

    def _process_chunk(ch, rows, failed):
        nonlocal ok, fail
        with _sync_lock:
            _sync_state["done"] += len(ch)
        rows_by_code: dict[str, list[tuple]] = {}
        for r in rows or []:
            rows_by_code.setdefault(r[0], []).append(r[1:])

        # 通达信本地 .day 文件合并：本地更全时优先用本地
        if tdx_root is not None:
            for code, start in ch:
                if code in failed:
                    continue
                tdf = tdxfile.read_stock(code)
                if tdf is not None and len(tdf) > 0:
                    tdf = tdf[(tdf["date"] >= start) & (tdf["date"] <= end)]
                    if len(tdf) > len(rows_by_code.get(code, [])):
                        rows_by_code[code] = [
                            (d.strftime("%Y-%m-%d"), float(r.open), float(r.high),
                             float(r.low), float(r.close), float(r.volume), float(r.amount))
                            for d, r in zip(tdf["date"], tdf.itertuples(index=False))]

        conn = db.get_conn()
        with conn:
            for code, start in ch:
                if code in failed and code not in rows_by_code:
                    fail += 1
                    if len(err_samples) < 8:
                        err_samples.append(f"{code}: {failed[code]}")
                    continue
                recs = rows_by_code.get(code)
                if not recs:
                    fail += 1
                    continue
                if allow_drift_refetch and _detect_drift(conn, code, recs):
                    drifted.append(code)
                    continue
                good, why = _write_stock(conn, code, recs, start)
                if good:
                    ok += 1
                else:
                    fail += 1
                    if len(err_samples) < 8:
                        err_samples.append(f"{code}: {why}")
        with _sync_lock:
            _sync_state.update(ok=ok, failed=fail, errors=err_samples[-8:])

    remaining = all_chunks
    for round_no in (1, 2, 3):
        if not remaining:
            break
        done: set[int] = set()
        try:
            with ProcessPoolExecutor(
                    max_workers=config.SYNC_WORKERS, initializer=_bs_init,
                    max_tasks_per_child=40) as pool:
                futs = {}
                for ch in remaining:
                    start = min(p[1] for p in ch)
                    futs[pool.submit(bs_fetch_chunk, ([p[0] for p in ch], start, end))] = ch
                for fut in as_completed(futs):
                    ch = futs[fut]
                    try:
                        err, rows, failed = fut.result()
                    except BrokenExecutor:
                        break  # 池已坏 → 外层重建
                    if err and not rows and not failed:
                        # 登录失败等整批错误 → 留待下一轮
                        with _sync_lock:
                            _sync_state["done"] += len(ch)
                        if len(err_samples) < 8:
                            err_samples.append(f"批次({len(ch)}只): {err}")
                        continue
                    _process_chunk(ch, rows, failed)
                    done.add(id(ch))
        except BrokenExecutor:
            pass
        remaining = [ch for ch in remaining if id(ch) not in done]
        if remaining:
            log.warning("同步第 %d 轮有 %d 个批次未完成，重建进程池重试", round_no, len(remaining))
            with _sync_lock:
                _sync_state["done"] = max(0, _sync_state["done"] - sum(len(c) for c in remaining))
            if round_no < 3:
                time.sleep(5)
    for ch in remaining:  # 三轮都失败的批次记为失败
        fail += len(ch)
        if len(err_samples) < 8:
            err_samples.append(f"{len(ch)}只批次三轮失败（baostock 不可用?）")
    with _sync_lock:
        _sync_state.update(ok=ok, failed=fail, errors=err_samples[-8:])
    return ok, fail, err_samples, drifted


def _sync_worker(years: float, mode: str, only_codes: list[str]) -> None:
    try:
        _set_state(phase="获取股票清单")
        universe = _fetch_universe()
        _NAME_MAP.update(dict(zip(universe["code"], universe["name"])))

        if only_codes:
            universe = universe[universe["code"].isin(set(only_codes))]
        codes = universe["code"].tolist()

        end = datetime.now().strftime("%Y-%m-%d")
        default_start = (datetime.now() - timedelta(days=int(365 * years) + 20)).strftime("%Y-%m-%d")

        from .. import db
        meta = {r["code"]: r["last_date"] for r in
                db.get_conn().execute("SELECT code, last_date FROM kline_meta WHERE last_date IS NOT NULL")}

        plans: list[tuple[str, str]] = []
        for code in codes:
            last = meta.get(code)
            if mode == "full" or not last:
                plans.append((code, default_start))
            else:
                plans.append((code, (pd.Timestamp(last) - pd.Timedelta(days=_OVERLAP_DAYS)).strftime("%Y-%m-%d")))

        _set_state(phase="下载K线", total=len(plans), done=0)
        t0 = time.time()
        _ok, _fail, _errs, drifted = _run_chunks(
            plans, end, allow_drift_refetch=(mode == "update"))

        # 除权漂移的股票整窗重下（第二轮）
        if drifted:
            _set_state(phase=f"复权漂移整窗重下({len(drifted)})", refetched=len(drifted))
            drift_plans = [(c, default_start) for c in drifted]
            with _sync_lock:
                _sync_state["done"] = 0
                _sync_state["total"] = len(drift_plans)
            _run_chunks(drift_plans, end, allow_drift_refetch=False)
            with _sync_lock:
                _sync_state["done"] = _sync_state["total"]

        _set_state(phase="完成", running=False,
                   finished_at=datetime.now().isoformat(timespec="seconds"),
                   elapsed=int(time.time() - t0))
    except Exception as e:  # noqa: BLE001
        log.exception("同步任务失败")
        _set_state(phase=f"失败: {e}", running=False,
                   finished_at=datetime.now().isoformat(timespec="seconds"))


def sync(years: float = 2.0, mode: str = "update", codes: list[str] | None = None) -> dict:
    """启动全市场同步（后台线程）。mode: update=增量 / full=整窗重下。

    已有任务在跑时直接返回当前状态，不重复启动。
    """
    from .. import db
    db.init_db()
    with _sync_lock:
        if _sync_state["running"]:
            return dict(_sync_state)
        _sync_state.update(running=True, phase="排队", done=0, total=0, ok=0, failed=0,
                           refetched=0, errors=[],
                           started_at=datetime.now().isoformat(timespec="seconds"),
                           finished_at=None, mode=mode)
    threading.Thread(target=_sync_worker, args=(years, mode, codes or []),
                     daemon=True, name="hist-sync").start()
    return sync_state()


# ---------- 读取 ----------

def all_codes() -> pd.DataFrame:
    """已入库股票清单 DataFrame[code, name, last_date]"""
    from .. import db
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT m.code, COALESCE(m.name, '') AS name, m.last_date FROM kline_meta m"
        " WHERE m.last_date IS NOT NULL").fetchall()
    return pd.DataFrame([dict(r) for r in rows], columns=["code", "name", "last_date"])


def read_kline(code: str, bars: int = 320) -> pd.DataFrame:
    """读取某股票最近 bars 根日K → DataFrame[date, open, high, low, close, volume, amount]"""
    from .. import db
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume, amount FROM kline_daily"
        " WHERE code=? ORDER BY date DESC LIMIT ?", (code, bars)).fetchall()
    rows.reverse()
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df


def status() -> dict:
    """数据仓库状态：覆盖股票数、数据截至日、同步进度"""
    from .. import db
    db.init_db()
    conn = db.get_conn()
    total_stocks = 0
    try:
        total_stocks = conn.execute("SELECT COUNT(*) FROM stock_list").fetchone()[0]
    except Exception:  # noqa: BLE001
        pass
    row = conn.execute(
        "SELECT COUNT(*) AS n, MAX(last_date) AS asof,"
        " SUM(CASE WHEN last_date >= date('now', '-5 days') THEN 1 ELSE 0 END) AS fresh"
        " FROM kline_meta WHERE last_date IS NOT NULL").fetchone()
    rows_n = conn.execute("SELECT COUNT(*) FROM kline_daily").fetchone()[0]
    return {
        "synced_stocks": row["n"] or 0,
        "fresh_stocks": row["fresh"] or 0,
        "total_stocks": total_stocks,
        "data_as_of": row["asof"],
        "kline_rows": rows_n,
        "sync": sync_state(),
        "tdx_vipdoc": bool(tdxfile.vipdoc_root()),
    }

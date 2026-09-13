"""SQLite 数据库层 —— 预测历史 + 用户自定义因子组合"""
import json
import sqlite3
import threading
from typing import Any, Optional

from . import config

_local = threading.local()
_init_lock = threading.Lock()
_initialized = False


def get_conn() -> sqlite3.Connection:
    """线程内复用连接（FastAPI 线程池下安全）"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(config.DATABASE_PATH, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS forecast_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,          -- baostock 代码，如 sh.601601
    stock_name TEXT NOT NULL,
    period TEXT NOT NULL,              -- daily / weekly / monthly
    horizon INTEGER NOT NULL,
    context_len INTEGER NOT NULL,
    factor_codes TEXT,                 -- JSON 数组，因子 baostock 代码
    factor_names TEXT,                 -- JSON 数组，因子名称
    inference_mode TEXT,               -- remote / local / mock
    model_version TEXT DEFAULT 'TimesFM-3.0',
    last_value REAL,
    forecast_mean REAL,
    forecast_min REAL,
    forecast_max REAL,
    predicted_change_pct REAL,
    historical_dates TEXT,             -- JSON
    historical_values TEXT,            -- JSON
    forecast_dates TEXT,               -- JSON
    forecast_values TEXT,              -- JSON
    quantile_lower TEXT,               -- JSON
    quantile_upper TEXT,               -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fh_stock ON forecast_history(stock_code);
CREATE INDEX IF NOT EXISTS idx_fh_time ON forecast_history(created_at DESC);

CREATE TABLE IF NOT EXISTS factor_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_code TEXT NOT NULL,
    target_name TEXT NOT NULL,
    factors TEXT NOT NULL,             -- JSON: [{"code","name"}]
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS screen_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,         -- 选股策略 id
    strategy_name TEXT NOT NULL,
    params TEXT NOT NULL,              -- JSON: 本次运行参数
    snapshot_time TEXT,                -- 行情快照时间
    total_screened INTEGER,            -- 快筛前股票数
    result_count INTEGER,              -- 入选股票数
    elapsed_ms INTEGER,                -- 耗时(毫秒)
    results TEXT NOT NULL,             -- JSON: 结果列表
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sr_time ON screen_runs(created_at DESC);

CREATE TABLE IF NOT EXISTS kline_daily (
    code TEXT NOT NULL,               -- baostock 代码，如 sh.600000
    date TEXT NOT NULL,               -- YYYY-MM-DD
    open REAL, high REAL, low REAL, close REAL,
    volume REAL,                      -- 股
    amount REAL,                      -- 元
    PRIMARY KEY (code, date)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_kd_date ON kline_daily(date);

CREATE TABLE IF NOT EXISTS kline_meta (
    code TEXT PRIMARY KEY,
    name TEXT,
    first_date TEXT,
    last_date TEXT,
    rows INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watch_group (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watch_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES watch_group(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT DEFAULT '',
    sort INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (group_id, code)
);

CREATE TABLE IF NOT EXISTS portfolio_backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    months REAL,
    groups TEXT,
    mode TEXT,
    status TEXT,
    elapsed_s REAL,
    params TEXT,
    summary TEXT,
    result TEXT
);
CREATE INDEX IF NOT EXISTS idx_pbr_time ON portfolio_backtest_runs(created_at DESC);
"""


def init_db() -> None:
    global _initialized
    with _init_lock:
        if _initialized:
            return
        conn = get_conn()
        conn.executescript(SCHEMA)
        conn.commit()
        _initialized = True


# ---------- 预测历史 ----------

def save_forecast(record: dict) -> int:
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO forecast_history (
            stock_code, stock_name, period, horizon, context_len,
            factor_codes, factor_names, inference_mode, model_version,
            last_value, forecast_mean, forecast_min, forecast_max, predicted_change_pct,
            historical_dates, historical_values, forecast_dates, forecast_values,
            quantile_lower, quantile_upper
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            record["stock_code"], record["stock_name"], record["period"],
            record["horizon"], record["context_len"],
            json.dumps(record.get("factor_codes") or [], ensure_ascii=False),
            json.dumps(record.get("factor_names") or [], ensure_ascii=False),
            record.get("inference_mode"), record.get("model_version", "TimesFM-3.0"),
            record["metrics"]["last_value"], record["metrics"]["forecast_mean"],
            record["metrics"]["forecast_min"], record["metrics"]["forecast_max"],
            record["metrics"]["predicted_change_pct"],
            json.dumps(record["historical"]["dates"], ensure_ascii=False),
            json.dumps(record["historical"]["values"]),
            json.dumps(record["forecast"]["dates"], ensure_ascii=False),
            json.dumps(record["forecast"]["values"]),
            json.dumps(record["quantiles"]["lower"]) if record.get("quantiles") else None,
            json.dumps(record["quantiles"]["upper"]) if record.get("quantiles") else None,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


_JSON_FIELDS = {
    "factor_codes", "factor_names",
    "historical_dates", "historical_values",
    "forecast_dates", "forecast_values", "quantile_lower", "quantile_upper",
}


def _row_to_record(row: sqlite3.Row) -> dict:
    d = dict(row)
    for f in _JSON_FIELDS:
        if d.get(f):
            d[f] = json.loads(d[f])
    # 与 predict 接口一致的嵌套结构
    d["metrics"] = {
        "last_value": d.get("last_value"),
        "forecast_mean": d.get("forecast_mean"),
        "forecast_min": d.get("forecast_min"),
        "forecast_max": d.get("forecast_max"),
        "predicted_change_pct": d.get("predicted_change_pct"),
    }
    if d.get("quantile_lower") is None:
        d["quantiles"] = {"lower": None, "upper": None}
    else:
        d["quantiles"] = {"lower": d.get("quantile_lower"), "upper": d.get("quantile_upper")}
    return d


def list_history(limit: int = 50, stock_code: Optional[str] = None) -> list[dict]:
    conn = get_conn()
    if stock_code:
        rows = conn.execute(
            "SELECT * FROM forecast_history WHERE stock_code=? ORDER BY id DESC LIMIT ?",
            (stock_code, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM forecast_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_history(record_id: int) -> Optional[dict]:
    row = get_conn().execute(
        "SELECT * FROM forecast_history WHERE id=?", (record_id,)
    ).fetchone()
    return _row_to_record(row) if row else None


def delete_history(record_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM forecast_history WHERE id=?", (record_id,))
    conn.commit()
    return cur.rowcount > 0


def history_stats() -> dict:
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM forecast_history").fetchone()[0]
    stocks = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM forecast_history").fetchone()[0]
    return {"total_forecasts": total, "unique_stocks": stocks}


# ---------- 自定义因子组合 ----------

def save_factor_group(name: str, target_code: str, target_name: str,
                      factors: list[dict]) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO factor_groups (name, target_code, target_name, factors) VALUES (?,?,?,?)",
        (name, target_code, target_name, json.dumps(factors, ensure_ascii=False)),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_factor_groups() -> list[dict]:
    rows = get_conn().execute(
        "SELECT * FROM factor_groups ORDER BY id DESC"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["factors"] = json.loads(d["factors"])
        out.append(d)
    return out


def delete_factor_group(group_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM factor_groups WHERE id=?", (group_id,))
    conn.commit()
    return cur.rowcount > 0


# ---------- 智能选股历史 ----------

def save_screen_run(strategy_id: str, strategy_name: str, params: dict,
                    snapshot_time: str, total_screened: int,
                    elapsed_ms: int, results: list[dict]) -> int:
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO screen_runs (
            strategy_id, strategy_name, params, snapshot_time,
            total_screened, result_count, elapsed_ms, results
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            strategy_id, strategy_name, json.dumps(params, ensure_ascii=False),
            snapshot_time, total_screened, len(results), elapsed_ms,
            json.dumps(results, ensure_ascii=False),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_screen_runs(limit: int = 50) -> list[dict]:
    """选股历史列表（不含结果明细，减少传输）"""
    rows = get_conn().execute(
        """SELECT id, strategy_id, strategy_name, params, snapshot_time,
                  total_screened, result_count, elapsed_ms, created_at
           FROM screen_runs ORDER BY id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d["params"])
        out.append(d)
    return out


def get_screen_run(run_id: int) -> Optional[dict]:
    row = get_conn().execute("SELECT * FROM screen_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["params"] = json.loads(d["params"])
    d["results"] = json.loads(d["results"])
    return d


def delete_screen_run(run_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM screen_runs WHERE id=?", (run_id,))
    conn.commit()
    return cur.rowcount > 0


# ---------- 组合策略组回测历史 ----------

def save_portfolio_run(params: dict, result: dict, elapsed_s: float) -> int:
    conn = get_conn()
    group_ids = ",".join(result.get("group_ids", []) or [])
    summary = result.get("runs", [{}])[-1].get("metrics", {})
    cur = conn.execute(
        """
        INSERT INTO portfolio_backtest_runs (
            months, groups, mode, status, elapsed_s, params, summary, result
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            params.get("months"), group_ids, params.get("mode"), "done",
            elapsed_s, json.dumps(params, ensure_ascii=False),
            json.dumps(summary, ensure_ascii=False),
            json.dumps(result, ensure_ascii=False),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_portfolio_runs(limit: int = 50) -> list[dict]:
    rows = get_conn().execute(
        """SELECT id, created_at, months, groups, mode, status, elapsed_s, params, summary
           FROM portfolio_backtest_runs ORDER BY id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d["params"]) if d.get("params") else {}
        d["summary"] = json.loads(d["summary"]) if d.get("summary") else {}
        d["group_ids"] = d.pop("groups", "").split(",") if d.get("groups") else []
        out.append(d)
    return out


def get_portfolio_run(run_id: int) -> Optional[dict]:
    row = get_conn().execute(
        "SELECT * FROM portfolio_backtest_runs WHERE id=?", (run_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["params"] = json.loads(d["params"]) if d.get("params") else {}
    d["summary"] = json.loads(d["summary"]) if d.get("summary") else {}
    d["result"] = json.loads(d["result"]) if d.get("result") else None
    d["group_ids"] = d.pop("groups", "").split(",") if d.get("groups") else []
    return d


# ---------- 自选分组 ----------

def list_watch_groups() -> list[dict]:
    """分组 + 组内成员（含排序）"""
    conn = get_conn()
    groups = [dict(r) for r in
              conn.execute("SELECT id, name, sort FROM watch_group ORDER BY sort, id")]
    for g in groups:
        g["items"] = [dict(r) for r in conn.execute(
            "SELECT id, code, name, sort FROM watch_item WHERE group_id=? ORDER BY sort, id",
            (g["id"],))]
    return groups


def create_watch_group(name: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO watch_group (name, sort) VALUES (?,"
        " COALESCE((SELECT MAX(sort)+1 FROM watch_group), 0))", (name,))
    conn.commit()
    return int(cur.lastrowid)


def rename_watch_group(group_id: int, name: str) -> bool:
    conn = get_conn()
    cur = conn.execute("UPDATE watch_group SET name=? WHERE id=?", (name, group_id))
    conn.commit()
    return cur.rowcount > 0


def delete_watch_group(group_id: int) -> bool:
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM watch_item WHERE group_id=?", (group_id,))
    cur = conn.execute("DELETE FROM watch_group WHERE id=?", (group_id,))
    conn.commit()
    return cur.rowcount > 0


def add_watch_item(group_id: int, code: str, name: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT OR IGNORE INTO watch_item (group_id, code, name, sort) VALUES (?,?,?,"
        " COALESCE((SELECT MAX(sort)+1 FROM watch_item WHERE group_id=?), 0))",
        (group_id, code, name, group_id))
    conn.commit()
    if cur.rowcount == 0:
        raise ValueError(f"{code} 已在该分组中")
    return int(cur.lastrowid)


def remove_watch_item(item_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM watch_item WHERE id=?", (item_id,))
    conn.commit()
    return cur.rowcount > 0

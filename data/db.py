"""SQLite 数据库模块 - 保存预测历史"""
import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Optional
import numpy as np

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forecast_history.db")


def get_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 预测历史主表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS forecast_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            frequency TEXT NOT NULL,
            horizon INTEGER NOT NULL,
            context_len INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            -- 预测配置
            last_value REAL,
            forecast_mean REAL,
            forecast_min REAL,
            forecast_max REAL,
            forecast_std REAL,
            predicted_change_pct REAL,
            
            -- 完整数据（JSON）
            historical_dates TEXT,
            historical_values TEXT,
            forecast_dates TEXT,
            forecast_values TEXT,
            forecast_quantiles TEXT,
            model_version TEXT DEFAULT 'TimesFM-3.0',
            factor_list TEXT
        )
    """)
    
    # 兼容旧库：增量添加新列
    for col, col_type in [("model_version", "TEXT DEFAULT 'TimesFM-3.0'"), ("factor_list", "TEXT")]:
        try:
            cursor.execute(f"ALTER TABLE forecast_history ADD COLUMN {col} {col_type}")
        except Exception:
            pass
    
    # 创建索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_stock_code 
        ON forecast_history(stock_code)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_created_at 
        ON forecast_history(created_at DESC)
    """)
    
    conn.commit()
    conn.close()
    print(f"[DB] ✅ 数据库初始化完成: {DB_PATH}")


def save_forecast(
    stock_code: str,
    stock_name: str,
    frequency: str,
    horizon: int,
    context_len: int,
    historical_dates: list,
    historical_values: list,
    forecast_dates: list,
    forecast_values: list,
    forecast_quantiles: Optional[list] = None,
    metrics: Optional[dict] = None,
    model_version: str = 'TimesFM-3.0',
    factor_list: Optional[list] = None,
) -> int:
    """保存一次预测结果"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if metrics is None:
        metrics = {}
    
    cursor.execute("""
        INSERT INTO forecast_history (
            stock_code, stock_name, frequency, horizon, context_len,
            last_value, forecast_mean, forecast_min, forecast_max, 
            forecast_std, predicted_change_pct,
            historical_dates, historical_values,
            forecast_dates, forecast_values, forecast_quantiles,
            model_version, factor_list
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        stock_code, stock_name, frequency, horizon, context_len,
        metrics.get('last_value'),
        metrics.get('forecast_mean'),
        metrics.get('forecast_min'),
        metrics.get('forecast_max'),
        metrics.get('forecast_std'),
        metrics.get('predicted_change_pct'),
        json.dumps(historical_dates, ensure_ascii=False),
        json.dumps(historical_values),
        json.dumps(forecast_dates, ensure_ascii=False),
        json.dumps(forecast_values),
        json.dumps(forecast_quantiles) if forecast_quantiles is not None else None,
        model_version,
        json.dumps(factor_list, ensure_ascii=False) if factor_list is not None else None,
    ))
    
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    print(f"[DB] 保存预测记录 #{record_id}: {stock_name}({stock_code}) {frequency} {horizon}步")
    return record_id


def get_history(limit: int = 20, stock_code: Optional[str] = None) -> List[Dict]:
    """获取预测历史列表"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if stock_code:
        cursor.execute("""
            SELECT * FROM forecast_history 
            WHERE stock_code = ?
            ORDER BY created_at DESC 
            LIMIT ?
        """, (stock_code, limit))
    else:
        cursor.execute("""
            SELECT * FROM forecast_history 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        d = dict(row)
        # 解析JSON字段
        for field in ['historical_dates', 'historical_values', 'forecast_dates', 
                      'forecast_values', 'forecast_quantiles']:
            if d.get(field):
                d[field] = json.loads(d[field])
        results.append(d)
    
    return results


def get_record_by_id(record_id: int) -> Optional[Dict]:
    """根据ID获取单条记录"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM forecast_history WHERE id = ?", (record_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row is None:
        return None
    
    d = dict(row)
    for field in ['historical_dates', 'historical_values', 'forecast_dates', 
                  'forecast_values', 'forecast_quantiles']:
        if d.get(field):
            d[field] = json.loads(d[field])
    
    return d


def delete_record(record_id: int) -> bool:
    """删除一条记录"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM forecast_history WHERE id = ?", (record_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_stats() -> Dict:
    """获取统计信息"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM forecast_history")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT stock_code) FROM forecast_history")
    unique_stocks = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT stock_code, stock_name, COUNT(*) as cnt 
        FROM forecast_history 
        GROUP BY stock_code 
        ORDER BY cnt DESC 
        LIMIT 5
    """)
    top_stocks = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    
    return {
        "total_forecasts": total,
        "unique_stocks": unique_stocks,
        "top_stocks": top_stocks,
    }


# 初始化
if __name__ == "__main__":
    init_db()
    print(get_stats())

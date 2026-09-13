# -*- coding: utf-8 -*-
"""拉取沪深300成分股 + 指数日线(后复权)到本地缓存。
只读 stock_forecast.db 获取成分名单与行业映射；行情走 baostock，请求间隔限速。
输出: cache/klines.pkl, cache/meta.pkl
"""
import os
import pickle
import sqlite3
import sys
import time

import baostock as bs
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)

REPO_DB = os.path.join(HERE, "..", "..", "data", "stock_forecast.db")
START = "2022-06-01"
END = "2026-09-12"
FIELDS = "date,code,open,high,low,close,preclose,volume,amount,turn,tradestatus,pctChg,isST"
SLEEP = 0.25


def load_universe():
    conn = sqlite3.connect(f"file:{REPO_DB}?mode=ro", uri=True)
    members = pd.read_sql("SELECT code FROM index_members WHERE list_name='hs300'", conn)
    industry = pd.read_sql("SELECT code, industry FROM stock_industry", conn)
    conn.close()
    return members["code"].tolist(), dict(industry.values.tolist())


def fetch_one(code):
    rs = bs.query_history_k_data_plus(code, FIELDS, start_date=START, end_date=END,
                                      frequency="d", adjustflag="1")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if rs.error_code != "0":
        raise RuntimeError(f"{code}: {rs.error_code} {rs.error_msg}")
    df = pd.DataFrame(rows, columns=FIELDS.split(","))
    for c in ["open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["tradestatus"] = pd.to_numeric(df["tradestatus"], errors="coerce").fillna(1).astype(int)
    df["isST"] = pd.to_numeric(df["isST"], errors="coerce").fillna(0).astype(int)
    return df


def main():
    codes, industry = load_universe()
    print(f"universe={len(codes)} (hs300), industry_map={len(industry)}", flush=True)
    lg = bs.login()
    assert lg.error_code == "0", f"baostock login failed: {lg.error_msg}"

    store = {}
    fail = []
    for i, code in enumerate(codes, 1):
        for attempt in (1, 2):
            try:
                store[code] = fetch_one(code)
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    fail.append(code)
                    print(f"FAIL {code}: {e}", flush=True)
                else:
                    time.sleep(1.0)
        if i % 20 == 0:
            print(f"... {i}/{len(codes)}", flush=True)
        time.sleep(SLEEP)

    # 基准指数
    idx = bs.query_history_k_data_plus("sh.000300",
        "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg",
        start_date=START, end_date=END, frequency="d", adjustflag="3")
    rows = []
    while idx.error_code == "0" and idx.next():
        rows.append(idx.get_row_data())
    idx_df = pd.DataFrame(rows, columns="date,code,open,high,low,close,preclose,volume,amount,turn,pctChg".split(","))
    for c in ["open", "high", "low", "close", "preclose"]:
        idx_df[c] = pd.to_numeric(idx_df[c], errors="coerce")
    print(f"index sh.000300 rows={len(idx_df)}", flush=True)
    bs.logout()

    with open(os.path.join(CACHE, "klines.pkl"), "wb") as f:
        pickle.dump({"klines": store, "index": idx_df}, f)
    with open(os.path.join(CACHE, "meta.pkl"), "wb") as f:
        pickle.dump({"industry": industry, "codes": codes, "failed": fail}, f)
    print(f"DONE store={len(store)} failed={len(fail)} -> {CACHE}", flush=True)


if __name__ == "__main__":
    sys.exit(main())

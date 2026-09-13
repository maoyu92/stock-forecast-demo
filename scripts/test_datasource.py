"""临时脚本：验证 baostock 数据源可用性"""
import baostock as bs
import pandas as pd

lg = bs.login()
print("login:", lg.error_code, lg.error_msg)

def q(code, freq="d", start="2025-06-01", end="2026-09-10", fields="date,code,close,volume"):
    rs = bs.query_history_k_data_plus(code, fields, start_date=start, end_date=end,
                                      frequency=freq, adjustflag="2")
    rows = []
    while (rs.error_code == "0") and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    print(f"{code} [{freq}]: {len(df)} rows, err={rs.error_code}")
    if len(df):
        print(df.tail(2).to_string())
    return df

# 1. 股票列表（看是否包含ETF/指数）
rs = bs.query_stock_basic()
rows = []
while (rs.error_code == "0") and rs.next():
    rows.append(rs.get_row_data())
basic = pd.DataFrame(rows, columns=rs.fields)
print("stock_basic total:", len(basic))
for kw in ["510300", "512800", "515170", "159611", "sh.000300", "601601", "600900", "601398", "600887"]:
    hit = basic[basic["code"].str.contains(kw, na=False)]
    print(f"  {kw}: {'FOUND ' + str(hit[['code','code_name']].values.tolist()) if len(hit) else 'NOT FOUND'}")

# 2. K线: 股票 / ETF / 指数
q("sh.601601")          # 中国太保
q("sh.510300")          # 沪深300ETF
q("sh.000300")          # 沪深300指数
q("sz.159611")          # 电力ETF(深)

bs.logout()

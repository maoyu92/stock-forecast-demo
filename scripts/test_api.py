"""后端 API 端到端自测：4 只测试股票 + 预设因子 + 历史/组合接口"""
import json
import os
import sys
import time

import httpx

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")

CASES = [
    {"code": "sh.601601", "name": "中国太保", "factors": [
        {"code": "sh.601318", "name": "中国平安"},
        {"code": "sh.601336", "name": "新华保险"},
        {"code": "sh.000300", "name": "沪深300指数"}]},
    {"code": "sh.600900", "name": "长江电力", "factors": [
        {"code": "sh.600886", "name": "国投电力"},
        {"code": "sh.600025", "name": "华能水电"},
        {"code": "sh.000300", "name": "沪深300指数"}]},
    {"code": "sh.601398", "name": "工商银行", "factors": [
        {"code": "sh.601939", "name": "建设银行"},
        {"code": "sh.601288", "name": "农业银行"},
        {"code": "sh.000300", "name": "沪深300指数"}]},
    {"code": "sh.600887", "name": "伊利股份", "factors": [
        {"code": "sh.600597", "name": "光明乳业"},
        {"code": "sz.000876", "name": "新希望"},
        {"code": "sh.000300", "name": "沪深300指数"}]},
]


def main() -> int:
    c = httpx.Client(timeout=600)
    ok = True

    print("== 1. 预设接口 ==")
    r = c.get(f"{BASE}/api/factors/presets")
    presets = r.json()["presets"]
    print(f"  {len(presets)} 个内置预设:", [p["name"] for p in presets])
    ok &= r.status_code == 200 and len(presets) == 4

    print("== 2. K线（含 ETF 新浪回退）==")
    for code, days in [("sh.601601", 400), ("sh.510300", 730)]:
        r = c.get(f"{BASE}/api/stocks/kline", params={"code": code, "period": "daily", "days": days})
        d = r.json()
        n = len(d.get("dates", []))
        print(f"  {code}: {n} 条, 最近 {d.get('dates', ['-'])[-1]}")
        ok &= r.status_code == 200 and n > 100

    print("== 3. 4 只测试股票多因子预测 ==")
    for case in CASES:
        t0 = time.time()
        body = {**case, "period": "daily", "horizon": 7, "context_len": 180, "save": True}
        r = c.post(f"{BASE}/api/predict", json=body)
        if r.status_code != 200:
            print(f"  ✗ {case['name']}: {r.status_code} {r.text[:200]}")
            ok = False
            continue
        d = r.json()
        m = d["metrics"]
        print(f"  ✓ {d['stock_name']} [{d['inference_mode']}] {time.time()-t0:.1f}s | "
              f"ctx={d['context_len']} 因子={len(d['factor_names'])} "
              f"现价={m['last_value']} 7日→{d['forecast']['values'][-1]} ({m['predicted_change_pct']:+.2f}%) "
              f"带=[{d['quantiles']['lower'][-1]},{d['quantiles']['upper'][-1]}] id=#{d.get('id')}")
        if d["inference_mode"] not in ("local", "remote", "mock"):
            ok = False

    print("== 4. 单变量预测（无因子）+ 周线 ==")
    r = c.post(f"{BASE}/api/predict", json={
        "code": "sh.600900", "name": "长江电力", "period": "weekly",
        "horizon": 4, "context_len": 120, "factors": [], "save": True})
    d = r.json()
    print(f"  weekly h=4 → mode={d['inference_mode']} dates={d['forecast']['dates']}")
    ok &= r.status_code == 200

    print("== 5. 自定义因子组合 CRUD ==")
    r = c.post(f"{BASE}/api/factors/groups", json={
        "name": "太保-我的组合", "target_code": "sh.601601", "target_name": "中国太保",
        "factors": [{"code": "sh.512800", "name": "银行ETF"}]})
    gid = r.json()["id"]
    r = c.get(f"{BASE}/api/factors/groups")
    print(f"  保存 #{gid}, 当前组合数: {len(r.json()['groups'])}")
    r = c.delete(f"{BASE}/api/factors/groups/{gid}")
    ok &= r.status_code == 200

    print("== 6. 历史记录 ==")
    r = c.get(f"{BASE}/api/history?limit=10")
    d = r.json()
    print(f"  共 {d['stats']['total_forecasts']} 条, 最近:", [
        f"#{x['id']}{x['stock_name']}({x['inference_mode']})" for x in d["records"][:5]])
    ok &= d["stats"]["total_forecasts"] >= 5
    if d["records"]:
        rid = d["records"][0]["id"]
        r = c.delete(f"{BASE}/api/history/{rid}")
        print(f"  删除 #{rid}: {r.json()}")

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

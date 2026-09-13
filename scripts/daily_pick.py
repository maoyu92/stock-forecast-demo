"""每日荐股 —— 头部策略组合 × 质量门控，只给"确定性较高"的标的

逻辑（对应"不是每天都有机会，可以空仓但要抓住机会"）：
1. 读取回测报告（data/backtest_report.json；缺失或超过 refresh_days 天则先重新回测）；
2. 取综合分前 K 的合格策略（默认前 5），用组合扫描器一次性评估今日信号；
3. 荐股 = 命中 ≥ min_strategies 个头部策略的股票，且通过质量门控：
   - 当日涨幅 -2%~7%（不追高、不接飞刀）
   - 信号日成交额 ≥ 1 亿（流动性）
   - 排除风险策略命中（顶分型/断头铡刀/高位揉搓线）——作为排除集传入
4. 一个都不满足 → 输出"今日无高确定性机会，建议观望/空仓"，绝不硬推。

用法：
    python scripts/daily_pick.py                 # 荐股（报告过期自动回测，较久）
    python scripts/daily_pick.py --no-backtest   # 只用现有报告
    python scripts/daily_pick.py --top 5 --min-hit 2
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

PICKS_DIR = Path(__file__).resolve().parent.parent / "data" / "daily_picks"
RISK_IDS = ["risk_fd_top", "risk_duandao", "risk_rub_high"]


def maybe_backtest(report, refresh_days: int, force: bool):
    from app.services import backtest
    if force or report is None:
        print(">> 无回测报告，开始全市场回测（约 5~15 分钟）…", flush=True)
        return backtest.run_backtest(months=12, min_signals=100)
    gen = datetime.fromisoformat(report["generated_at"])
    age = (datetime.now() - gen).days
    if age >= refresh_days:
        print(f">> 回测报告已 {age} 天，自动刷新…", flush=True)
        return backtest.run_backtest(months=12, min_signals=100)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="每日荐股（头部策略组合 + 质量门控）")
    ap.add_argument("--top", type=int, default=5, help="取回测排名前 K 的策略")
    ap.add_argument("--min-hit", type=int, default=2, help="至少命中 K 个头部策略才推荐")
    ap.add_argument("--refresh-days", type=int, default=7, help="回测报告超过 N 天自动刷新")
    ap.add_argument("--no-backtest", action="store_true", help="不自动回测（无报告则报错）")
    ap.add_argument("--pct-max", type=float, default=7.0)
    ap.add_argument("--pct-min", type=float, default=-2.0)
    ap.add_argument("--min-amount", type=float, default=1.0, help="信号日成交额下限（亿）")
    args = ap.parse_args()

    from app.services import backtest, histstore
    from app.services.screener import base
    from app.services.screener.formula import runner

    st = histstore.status()
    today = datetime.now().strftime("%Y-%m-%d")
    # 收盘后运行：数据截至日不是今天就增量同步（交易日晚上 baostock 已更新当日K线）
    if st.get("data_as_of") and st["data_as_of"][:10] != today:
        print(f">> 本地数据截至 {st['data_as_of'][:10]}，增量同步到今日（约 5 分钟）…", flush=True)
        histstore.sync(mode="update")
        while histstore.sync_state().get("running"):
            time.sleep(5)
        st = histstore.status()
        print(f">> 同步完成，数据截至 {st['data_as_of']}", flush=True)

    report = backtest.load_report() if not args.no_backtest else backtest.load_report()
    if args.no_backtest and report is None:
        print("无回测报告（--no-backtest 模式），请先运行 scripts/backtest.py")
        sys.exit(1)
    report = maybe_backtest(report, args.refresh_days, force=False)
    top = report["top"][:args.top]
    print(f">> 使用回测报告 {report['generated_at']}，头部策略：")
    for t in top:
        print(f"   #{t['rank']} {t['name']}（{t['cat']}） 5日胜率{t['win5']}% 均收益{t['avg5']}% 信号{t['signals']}")

    defs = [base.get_strategy(t["sid"]) for t in top]
    excl_defs = []
    for rid in RISK_IDS:
        try:
            excl_defs.append(base.get_strategy(rid))
        except ValueError:
            pass

    def merged_for(st_):
        out = {}
        for p in st_.params:
            out[p.key] = p.default
        out.update({"within_n": 1, "exclude_st": True, "min_amount": args.min_amount})
        return out

    params_by_sid = {s.id: merged_for(s) for s in defs}
    excl_params = {s.id: merged_for(s) for s in excl_defs}

    print(f">> 扫描今日信号（{len(defs)} 策略 + 排除 {len(excl_defs)} 风险策略）…", flush=True)
    results, meta = runner.run_multi_strategy(defs, params_by_sid, excl_defs, excl_params, "or")

    picks = []
    for r in results:
        hits = len(r["factors"])
        if hits < args.min_hit:
            continue
        if not (args.pct_min <= r["pct"] <= args.pct_max):
            continue
        if r["amount"] < args.min_amount * 1e8:
            continue
        r["hit_strategies"] = [f["name"] for f in r["factors"]]
        r["hits"] = hits
        picks.append(r)
    picks.sort(key=lambda r: (-r["hits"], -r["score"]))

    asof = meta.get("snapshot_time", "")[:10]
    verdict = {
        "date": asof or datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "report_date": report["generated_at"][:10],
        "top_strategies": [{"sid": t["sid"], "name": t["name"], "win5": t["win5"],
                            "avg5": t["avg5"], "rank": t["rank"]} for t in top],
        "min_hit": args.min_hit,
        "scanned": meta["total_screened"],
        "today_signal_stocks": meta["candidates"],
        "pick_count": len(picks),
        "picks": picks,
        "disclaimer": "历史胜率不代表未来表现，仅供研究参考，不构成投资建议。",
    }

    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    out = PICKS_DIR / f"{verdict['date']}.json"
    out.write_text(json.dumps(verdict, ensure_ascii=False), encoding="utf-8")

    print()
    if not picks:
        print(f"=== {verdict['date']} 今日无高确定性机会（命中≥{args.min_hit}个头部策略的标的为 0）===")
        print(">>> 建议：观望 / 空仓，等机会再动手。历史信号今日共",
              meta["candidates"], "只，但确定性不足。")
    else:
        print(f"=== {verdict['date']} 每日荐股（命中≥{args.min_hit}个头部策略）===")
        for r in picks[:15]:
            print(f"  {r['code']} {r['name']}  {r['price']:.2f}  {r['pct']:+.2f}%  "
                  f"命中{r['hits']}策略  强度分{r['score']}")
            print(f"     策略：{'、'.join(r['hit_strategies'])}")
    print(f"\n已保存 {out}")


if __name__ == "__main__":
    main()

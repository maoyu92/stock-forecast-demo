"""从期望值排名中挑选核心策略，并做组合级回测

与 backtest_exit_rules.py 的差异：
- 那个脚本衡量“单个策略如果把每个信号都做一遍”的期望值；
- 这个脚本把若干高期望策略合成一个组合，受同一本金、最大持仓和同股不重复持仓约束；
- 目标是看这些信号合在一起后，是否仍然保留正期望。
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_exit_rules import Trade, metric_block, simulate_stock

REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "core_portfolio_expected_value_report.json"


def load_source_report(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["all"]
    for r in rows:
        if "ev_per_10k" not in r:
            r["ev_per_10k"] = round(r["avg_pnl_pct"] * 100, 2)
    rows = [r for r in rows if r["trades"] > 0]
    rows.sort(key=lambda r: (-r["ev_per_10k"], -r["trades"], -r["profit_factor"]))
    return rows


def select_rows(rows: list[dict], mode: str, top_n: int, min_trades: int) -> list[dict]:
    pool = [r for r in rows if r["trades"] >= min_trades]
    if mode == "top":
        return pool[:top_n]
    if mode == "diversified":
        picked, seen_cats = [], defaultdict(int)
        for r in pool:
            cat = r.get("cat") or "未分类"
            if seen_cats[cat] >= 1:
                continue
            picked.append(r)
            seen_cats[cat] += 1
            if len(picked) >= top_n:
                break
        return picked
    raise ValueError(f"未知 mode: {mode}")


def dedupe_same_stock_day(candidates: list[Trade], rank_by_sid: dict[str, int]) -> list[Trade]:
    """同一天同一股票如果多个策略同时命中，只保留期望值排名最高的一个"""
    best: dict[tuple[str, str], Trade] = {}
    for t in candidates:
        key = (t.code, t.entry_date)
        if key not in best or rank_by_sid.get(t.sid, 9999) < rank_by_sid.get(best[key].sid, 9999):
            best[key] = t
    return list(best.values())


def select_portfolio(candidates: list[Trade], rank_by_sid: dict[str, int],
                     capital: float, max_positions: int) -> tuple[list[Trade], dict[str, int]]:
    candidates = sorted(candidates, key=lambda t: (t.entry_date, rank_by_sid.get(t.sid, 9999), t.code))
    active: list[Trade] = []
    occupied_until: dict[str, str] = {}
    accepted: list[Trade] = []
    rejected = defaultdict(int)

    for t in candidates:
        # 同一只股票已有仓位未结束则不加仓
        if t.code in occupied_until and t.entry_date <= occupied_until[t.code]:
            rejected["same_stock_overlap"] += 1
            continue
        # 清理已到期的持仓
        active = [p for p in active if p.exit_date >= t.entry_date]
        if len(active) >= max_positions:
            rejected["max_positions"] += 1
            continue
        reserved = sum(p.buy_amount for p in active)
        if t.buy_amount > capital - reserved:
            rejected["insufficient_cash"] += 1
            continue
        active.append(t)
        occupied_until[t.code] = t.exit_date
        accepted.append(t)

    return accepted, dict(rejected)


def summarize_by_strategy(trades: list[Trade]) -> list[dict]:
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        grouped[t.sid].append(t)
    out = []
    for sid, ts in grouped.items():
        m = metric_block(ts)
        out.append({"sid": sid, **m})
    out.sort(key=lambda x: -x["total_pnl"])
    return out


def run_mode(name: str, selected: list[dict], candidates_by_sid: dict[str, list[Trade]],
             args, rank_by_sid: dict[str, int]) -> dict:
    candidates = []
    for r in selected:
        candidates.extend(candidates_by_sid.get(r["sid"], []))
    deduped = dedupe_same_stock_day(candidates, rank_by_sid)
    accepted, rejected = select_portfolio(
        deduped, rank_by_sid, args.capital, args.max_positions)
    metrics = metric_block(accepted)
    metrics["ev_per_10k"] = round(metrics["avg_pnl_pct"] * 100, 2)
    metrics["return_on_capital_pct"] = round(metrics["total_pnl"] / args.capital * 100, 2)
    metrics["avg_exposure_per_trade_pct"] = round(
        metrics["avg_notional"] / args.capital * 100, 2)

    return {
        "mode": name,
        "selected_strategies": [r["sid"] for r in selected],
        "selected_details": [
            {
                "sid": r["sid"], "name": r["name"], "cat": r["cat"],
                "source_ev_per_10k": r["ev_per_10k"],
                "source_trades": r["trades"],
            } for r in selected
        ],
        "candidate_trades": len(candidates),
        "deduped_trades": len(deduped),
        "accepted_trades": len(accepted),
        "rejected": rejected,
        "metrics": metrics,
        "strategy_contribution": summarize_by_strategy(accepted),
    }


def main():
    ap = argparse.ArgumentParser(description="核心策略组合回测（期望值口径）")
    ap.add_argument("--report", default=str(Path(__file__).resolve().parent.parent / "data" / "exit_rules_expected_value_report.json"))
    ap.add_argument("--mode", choices=["top", "diversified", "both"], default="both")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--min-trades", type=int, default=500)
    ap.add_argument("--months", type=float, default=12)
    ap.add_argument("--max-hold", type=int, default=10)
    ap.add_argument("--take-profit", type=float, default=3.0)
    ap.add_argument("--stop-loss", type=float, default=10.0)
    ap.add_argument("--capital", type=float, default=100000)
    ap.add_argument("--cash-per-trade", type=float, default=5000)
    ap.add_argument("--max-positions", type=int, default=10)
    ap.add_argument("--fee-threshold", type=float, default=5000)
    ap.add_argument("--fee-rate", type=float, default=0.0008)
    ap.add_argument("--extra-cost", type=float, default=0.0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    from app.services import histstore
    from app.services.screener import base
    from app.services.screener.formula import engine

    t0 = time.time()
    source_rows = load_source_report(Path(args.report))
    selected_top = select_rows(source_rows, "top", args.top, args.min_trades)
    selected_div = select_rows(source_rows, "diversified", args.top, args.min_trades)
    if args.mode == "top":
        mode_rows = {"top": selected_top}
    elif args.mode == "diversified":
        mode_rows = {"diversified": selected_div}
    else:
        mode_rows = {"top": selected_top, "diversified": selected_div}

    union_rows = {r["sid"]: r for rs in mode_rows.values() for r in rs}
    sids = list(union_rows)
    jobs = []
    for sid in sids:
        try:
            st = base.get_strategy(sid)
            params = {p.key: p.default for p in st.params}
            jobs.append((sid, engine.compile_formula(st.formula), params))
        except Exception as e:
            print(f"跳过公式 {sid}: {e}")

    codes_df = histstore.all_codes()
    codes = codes_df["code"].tolist()
    if args.limit:
        codes = codes[:args.limit]
    bars = min(int(args.months * 21) + 60, 320)

    print(f"候选策略 {len(jobs)} 个，股票 {len(codes)} 只，K线 {bars} 根")
    print(f"组合约束：本金 {args.capital:.0f}，单笔 {args.cash_per_trade:.0f}，最大持仓 {args.max_positions}")
    print(f"交易规则：持有>{args.max_hold}日退出 / +{args.take_profit}% / -{args.stop_loss}%")
    print(f"费用：单边 <{args.fee_threshold:.0f} 免收费，>= {args.fee_threshold:.0f} 万分之{args.fee_rate*10000:.0f}")

    candidates_by_sid: dict[str, list[Trade]] = {sid: [] for sid in sids}
    done = 0

    def work(code):
        df = histstore.read_kline(code, bars)
        if len(df) < 80:
            return code, {}
        return simulate_stock(code, df, jobs, args.max_hold,
                              args.take_profit / 100, args.stop_loss / 100,
                              args.cash_per_trade, args.capital,
                              args.fee_threshold, args.fee_rate, args.extra_cost)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for code, result in pool.map(work, codes):
            done += 1
            if done % max(1, len(codes) // 50) == 0:
                print(f"进度 {done}/{len(codes)}", flush=True)
            for sid, ts in result.items():
                candidates_by_sid[sid].extend(ts)

    rank_by_sid = {sid: i for i, sid in enumerate(sids)}
    runs = []
    for mode, rows in mode_rows.items():
        runs.append(run_mode(mode, rows, candidates_by_sid, args, rank_by_sid))

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_report": args.report,
        "stocks": len(codes),
        "params": {
            "months": args.months, "max_hold": args.max_hold,
            "take_profit_pct": args.take_profit, "stop_loss_pct": args.stop_loss,
            "capital": args.capital, "cash_per_trade": args.cash_per_trade,
            "max_positions": args.max_positions,
            "fee_threshold": args.fee_threshold, "fee_rate": args.fee_rate,
            "extra_cost_pct": args.extra_cost, "min_trades": args.min_trades,
        },
        "runs": runs,
        "elapsed_s": round(time.time() - t0, 1),
        "disclaimer": "历史回测仅供研究，不构成投资建议。",
    }

    for run in runs:
        print(f"\n=== {run['mode']} ===")
        print("策略：", "、".join(run["selected_strategies"]))
        print(f"候选 {run['candidate_trades']}，去重后 {run['deduped_trades']}，实际接纳 {run['accepted_trades']}")
        m = run["metrics"]
        print(f"总盈亏 {m['total_pnl']} 元，本金收益率 {m['return_on_capital_pct']}%，"
              f"平均每笔 {m['avg_pnl']} 元，每万元投入期望 {m['ev_per_10k']} 元")
        print(f"胜率 {m['win_rate']}%，盈亏比 {m['profit_factor']}，"
              f"平均持仓 {m['avg_holding_days']} 天，平均手续费 {m['avg_fees']} 元")

    if not args.no_save:
        REPORT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已保存 {REPORT_PATH}")
    print(f"耗时 {result['elapsed_s']}s")


if __name__ == "__main__":
    main()

"""116 个公式策略 + 统一买卖规则回测（期望值口径）

规则：
- 信号日收盘买入；
- 最多持有 N 个交易日；
- 期间达到止盈价卖出；
- 达到止损价卖出；
- 同一天同时触及止盈/止损时，保守假设先触发止损；
- 到期未触发则按第 N 日收盘卖出。

费用：
- 默认按一笔 5000 元左右的名义仓位估算；
- 单边成交金额 < 5000 元：手续费 0；
- 单边成交金额 >= 5000 元：手续费万分之8；
- 买卖两侧分别计算。
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "exit_rules_expected_value_report.json"


@dataclass
class Trade:
    sid: str
    code: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    buy_amount: float
    sell_amount: float
    fees: float
    pnl: float
    pnl_pct: float
    holding_days: int
    exit_reason: str


def fee_for(amount: float, threshold: float, rate: float) -> float:
    return 0.0 if amount < threshold else amount * rate


def simulate_stock(code: str, df, jobs, max_hold: int, tp: float, sl: float,
                  cash_per_trade: float, capital: float,
                  fee_threshold: float, fee_rate: float, extra_cost: float = 0.0):
    """单只股票上，对每个公式策略做持仓状态机模拟，并计算期望值口径盈亏"""
    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    n = len(df)
    last_entry_idx = n - max_hold - 2  # 保证入场后还有 max_hold 根K线可判定

    out: dict[str, list[Trade]] = {}
    for sid, comp, params in jobs:
        trades: list[Trade] = []
        try:
            sig, _ = comp.eval(df, params)
            sig = sig.fillna(False).astype(bool).to_numpy()
        except Exception:
            out[sid] = trades
            continue

        i = 0
        while i <= last_entry_idx:
            if not sig[i] or close[i] <= 0:
                i += 1
                continue
            entry_price = close[i]

            # 按 100 股一手取整；若目标仓位不足一手，至少买一手；
            # 若超过可用本金则按本金能买入的最大手数缩仓。
            shares = int(cash_per_trade / entry_price / 100) * 100
            if shares <= 0:
                shares = 100
            max_affordable = int(capital / entry_price / 100) * 100
            shares = min(shares, max_affordable)
            if shares <= 0:
                i += 1
                continue

            buy_amount = shares * entry_price
            buy_fee = fee_for(buy_amount, fee_threshold, fee_rate)
            tp_price = entry_price * (1 + tp)
            sl_price = entry_price * (1 - sl)
            exit_idx = None
            exit_price = None
            exit_reason = ""

            for j in range(i + 1, min(i + max_hold + 1, n)):
                o, h, l = open_[j], high[j], low[j]
                if o >= tp_price:
                    exit_idx, exit_price, exit_reason = j, o, "target_gap_up"
                    break
                if o <= sl_price:
                    exit_idx, exit_price, exit_reason = j, o, "stop_gap_down"
                    break
                if h >= tp_price and l <= sl_price:
                    # 日线无法判定先后，保守按止损处理
                    exit_idx, exit_price, exit_reason = j, sl_price, "stop_loss_same_day"
                    break
                if h >= tp_price:
                    exit_idx, exit_price, exit_reason = j, tp_price, "take_profit"
                    break
                if l <= sl_price:
                    exit_idx, exit_price, exit_reason = j, sl_price, "stop_loss"
                    break

            if exit_idx is None:
                j = min(i + max_hold, n - 1)
                exit_idx, exit_price, exit_reason = j, close[j], "time_exit"

            sell_amount = shares * exit_price
            sell_fee = fee_for(sell_amount, fee_threshold, fee_rate)
            fees = buy_fee + sell_fee
            pnl = sell_amount - buy_amount - fees
            cost_basis = buy_amount + buy_fee
            pnl_pct = pnl / cost_basis if cost_basis > 0 else 0.0
            if extra_cost:
                pnl -= (buy_amount + sell_amount) * extra_cost / 100
                pnl_pct = pnl / cost_basis if cost_basis > 0 else 0.0

            trades.append(Trade(
                sid=sid,
                code=code,
                entry_date=dates[i],
                exit_date=dates[exit_idx],
                entry_price=float(entry_price),
                exit_price=float(exit_price),
                shares=shares,
                buy_amount=float(buy_amount),
                sell_amount=float(sell_amount),
                fees=float(fees),
                pnl=float(pnl),
                pnl_pct=round(pnl_pct * 100, 4),
                holding_days=exit_idx - i,
                exit_reason=exit_reason,
            ))
            i = exit_idx + 1  # 卖出后下一根才允许重新评估

        out[sid] = trades
    return code, out


def metric_block(trades: list[Trade]) -> dict:
    if not trades:
        return {
            "trades": 0, "win_rate": 0, "avg_pnl": 0, "median_pnl": 0,
            "avg_pnl_pct": 0, "median_pnl_pct": 0, "total_pnl": 0,
            "profit_factor": 0, "avg_holding_days": 0,
            "avg_fees": 0, "avg_notional": 0, "positive_trades": 0,
        }
    pnls = [t.pnl for t in trades]
    pnl_pcts = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else (99 if wins else 0)
    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(pnls) * 100, 2),
        "avg_pnl": round(mean(pnls), 2),
        "median_pnl": round(median(pnls), 2),
        "avg_pnl_pct": round(mean(pnl_pcts), 3),
        "median_pnl_pct": round(median(pnl_pcts), 3),
        "total_pnl": round(sum(pnls), 2),
        "profit_factor": round(pf, 2),
        "avg_holding_days": round(mean(t.holding_days for t in trades), 2),
        "avg_fees": round(mean(t.fees for t in trades), 2),
        "avg_notional": round(mean(t.buy_amount for t in trades), 2),
        "positive_trades": len(wins),
    }


def main():
    ap = argparse.ArgumentParser(description="116策略 + 统一止盈止损/持有期规则回测（期望值口径）")
    ap.add_argument("--months", type=float, default=12)
    ap.add_argument("--max-hold", type=int, default=10)
    ap.add_argument("--take-profit", type=float, default=3.0, help="止盈百分比")
    ap.add_argument("--stop-loss", type=float, default=10.0, help="止损百分比")
    ap.add_argument("--capital", type=float, default=100000, help="账户本金")
    ap.add_argument("--cash-per-trade", type=float, default=5000, help="单笔目标名义仓位")
    ap.add_argument("--fee-threshold", type=float, default=5000, help="单边成交金额免收费上限")
    ap.add_argument("--fee-rate", type=float, default=0.0008, help="超过免收费门槛后的费率，如万分之8=0.0008")
    ap.add_argument("--extra-cost", type=float, default=0.0, help="额外滑点/成本百分比")
    ap.add_argument("--limit", type=int, default=None, help="只测前 N 只股票")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    from app.services import histstore
    from app.services.screener import base
    from app.services.screener.formula import engine

    t0 = time.time()
    strategies = [s for s in base.list_strategies() if s["kind"] == "formula"]
    jobs = []
    for s in strategies:
        params = {p["key"]: p["default"] for p in s["params"]}
        try:
            comp = engine.compile_formula(s["formula"])
            jobs.append((s["id"], comp, params))
        except Exception as e:
            print(f"跳过公式 {s['id']}: {e}")

    codes_df = histstore.all_codes()
    codes = codes_df["code"].tolist()
    names = dict(zip(codes_df["code"], codes_df["name"]))
    if args.limit:
        codes = codes[:args.limit]

    bars = min(int(args.months * 21) + 60, 320)
    print(f"策略 {len(jobs)} 个，股票 {len(codes)} 只，K线 {bars} 根")
    print(f"规则：持有>{args.max_hold}日退出 / +{args.take_profit}% / -{args.stop_loss}%")
    print(f"费用：本金 {args.capital:.0f}，单笔目标 {args.cash_per_trade:.0f}，"
          f"单边 <{args.fee_threshold:.0f} 免收费，>= {args.fee_threshold:.0f} 万分之{args.fee_rate*10000:.0f}")

    all_trades: dict[str, list[Trade]] = {sid: [] for sid, *_ in jobs}
    done = 0

    def work(code):
        df = histstore.read_kline(code, bars)
        if len(df) < 80:
            return code, {}
        return simulate_stock(code, df, jobs, args.max_hold,
                              args.take_profit / 100, args.stop_loss / 100,
                              args.cash_per_trade, args.capital,
                              args.fee_threshold, args.fee_rate,
                              args.extra_cost)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for code, result in pool.map(work, codes):
            done += 1
            if done % max(1, len(codes) // 50) == 0:
                print(f"进度 {done}/{len(codes)}", flush=True)
            for sid, ts in result.items():
                all_trades[sid].extend(ts)

    sid_to_meta = {s["id"]: s for s in strategies}
    rows = []
    for sid, trades in all_trades.items():
        m = metric_block(trades)
        meta = sid_to_meta.get(sid, {})
        rows.append({
            "sid": sid,
            "name": meta.get("name", sid),
            "cat": meta.get("category", ""),
            **m,
        })

    overall = metric_block([t for ts in all_trades.values() for t in ts])
    # 统一期望值口径：每 10000 元投入的期望盈亏
    for r in rows:
        r["ev_per_10k"] = round(r["avg_pnl_pct"] * 100, 2)
    overall["ev_per_10k"] = round(overall["avg_pnl_pct"] * 100, 2)
    # 期望值优先排序：先看每万元投入期望盈亏，再看交易数，最后看盈亏比
    rows.sort(key=lambda r: (-r["ev_per_10k"], -r["trades"], -r["profit_factor"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    # 分类汇总
    cat_stats = {}
    for r in rows:
        cat = r["cat"] or "未分类"
        if cat not in cat_stats:
            cat_stats[cat] = {"cat": cat, "strategies": 0, "trades": 0,
                              "avg_pnl_sum": 0, "avg_pnl_pct_sum": 0,
                              "profitable_strategies": 0}
        cat_stats[cat]["strategies"] += 1
        cat_stats[cat]["trades"] += r["trades"]
        cat_stats[cat]["avg_pnl_sum"] += r["avg_pnl"]
        cat_stats[cat]["avg_pnl_pct_sum"] += r["avg_pnl_pct"]
        if r["avg_pnl"] > 0:
            cat_stats[cat]["profitable_strategies"] += 1
    for c in cat_stats.values():
        c["avg_strategy_pnl"] = round(c["avg_pnl_sum"] / c["strategies"], 2)
        c["avg_strategy_pnl_pct"] = round(c["avg_pnl_pct_sum"] / c["strategies"], 3)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "months": args.months,
        "stocks": len(codes),
        "strategies_total": len(rows),
        "max_hold": args.max_hold,
        "take_profit_pct": args.take_profit,
        "stop_loss_pct": args.stop_loss,
        "capital": args.capital,
        "cash_per_trade": args.cash_per_trade,
        "fee_threshold": args.fee_threshold,
        "fee_rate": args.fee_rate,
        "extra_cost_pct": args.extra_cost,
        "overall": overall,
        "category_stats": sorted(cat_stats.values(),
                                 key=lambda x: -x["avg_strategy_pnl"]),
        "top": rows[:args.top],
        "all": rows,
        "elapsed_s": round(time.time() - t0, 1),
    }

    print("\n=== 全部策略整体（期望值口径） ===")
    print(f"交易数 {overall['trades']}，平均每笔盈亏 {overall['avg_pnl']} 元，"
          f"中位每笔盈亏 {overall['median_pnl']} 元，平均收益率 {overall['avg_pnl_pct']}%")
    print(f"总盈亏 {overall['total_pnl']} 元，平均手续费 {overall['avg_fees']} 元/笔，"
          f"平均持仓 {overall['avg_holding_days']} 天，胜率 {overall['win_rate']}%")

    print(f"\n=== Top {args.top}（按平均每笔盈亏） ===")
    header = (f"{'排名':<4}{'策略':<24}{'分类':<14}{'交易':>6}{'期望值':>10}"
              f"{'收益率':>9}{'总盈亏':>12}{'胜率':>7}{'持仓':>7}")
    print(header)
    for r in rows[:args.top]:
        print(f"{r['rank']:<4}{r['name'][:22]:<24}{r['cat'][:12]:<14}{r['trades']:>6}"
              f"{r['avg_pnl']:>10}{r['avg_pnl_pct']:>8}%{r['total_pnl']:>12}"
              f"{r['win_rate']:>6}%{r['avg_holding_days']:>7}")

    print("\n=== 分类汇总（按平均每笔盈亏） ===")
    print(f"{'分类':<16}{'策略数':>6}{'交易数':>8}{'平均期望值':>12}{'平均收益率':>12}{'正期望策略':>12}")
    for c in report["category_stats"]:
        print(f"{c['cat'][:14]:<16}{c['strategies']:>6}{c['trades']:>8}"
              f"{c['avg_strategy_pnl']:>12}{c['avg_strategy_pnl_pct']:>11}%{c['profitable_strategies']:>12}")

    if not args.no_save:
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已保存 {REPORT_PATH}")
    print(f"耗时 {report['elapsed_s']}s")


if __name__ == "__main__":
    main()

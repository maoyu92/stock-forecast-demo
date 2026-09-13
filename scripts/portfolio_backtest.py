"""命令行组合策略组回测：完整买卖/止损/仓位/净值"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def main() -> None:
    ap = argparse.ArgumentParser(description="组合策略组回测（买入+卖出+仓位）")
    ap.add_argument("--months", type=float, default=12, help="回溯月数")
    ap.add_argument("--groups", default="", help="逗号分隔策略组 id，留空=全部")
    ap.add_argument("--mode", choices=["individual", "combined", "both"], default="both")
    ap.add_argument("--initial-cash", type=float, default=1_000_000)
    ap.add_argument("--max-positions", type=int, default=8)
    ap.add_argument("--max-exposure", type=float, default=0.95)
    ap.add_argument("--fee-rate", type=float, default=0.0003)
    ap.add_argument("--stamp-tax-rate", type=float, default=0.0005)
    ap.add_argument("--slippage", type=float, default=0.001)
    ap.add_argument("--market-breadth-threshold", type=float, default=0.45)
    ap.add_argument("--board", default="全部")
    ap.add_argument("--no-market-timing", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="只回测前 N 只股票（冒烟测试）")
    args = ap.parse_args()

    from app.services import portfolio_backtest

    group_ids = [x.strip() for x in args.groups.split(",") if x.strip()]
    r = portfolio_backtest.run_backtest(
        months=args.months,
        group_ids=group_ids or None,
        mode=args.mode,
        initial_cash=args.initial_cash,
        max_positions=args.max_positions,
        max_exposure=args.max_exposure,
        fee_rate=args.fee_rate,
        stamp_tax_rate=args.stamp_tax_rate,
        slippage=args.slippage,
        market_timing_enabled=not args.no_market_timing,
        market_breadth_threshold=args.market_breadth_threshold,
        board=args.board,
        limit=args.limit,
    )
    print(f"回测完成：{r['generated_at']}  股票 {r['universe_size']}  区间 {r['start_date']}~{r['end_date']}  耗时 {r['elapsed_s']}s")
    if r["warnings"]:
        for w in r["warnings"]:
            print(f"⚠️ {w}")
    print()
    header = f"{'模式':<12}{'策略组':<22}{'收益':>8}{'年化':>8}{'回撤':>8}{'夏普':>7}{'胜率':>7}{'盈亏比':>8}{'交易':>6}"
    print(header)
    for run in r["runs"]:
        m = run["metrics"]
        name = run.get("group_name", run.get("group_id", ""))
        print(f"{run['mode']:<12}{name[:20]:<22}"
              f"{m['total_return_pct']:>7}%{m['annualized_return_pct']:>7}%"
              f"{m['max_drawdown_pct']:>7}%{m['sharpe']:>7}"
              f"{m['win_rate_pct']:>6}%{m['profit_factor']:>8}{m['trades']:>6}")
    print("\n报告已保存 data/portfolio_backtest_report.json")


if __name__ == "__main__":
    main()

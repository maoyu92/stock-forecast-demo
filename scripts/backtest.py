"""命令行回测：全市场 × 全公式策略 胜率统计"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def main() -> None:
    ap = argparse.ArgumentParser(description="策略历史回测（信号胜率统计）")
    ap.add_argument("--months", type=float, default=12, help="回溯月数（≤~14，受本地K线长度限制）")
    ap.add_argument("--min-signals", type=int, default=100, help="参与排名的最少信号数")
    args = ap.parse_args()

    from app.services import backtest

    r = backtest.run_backtest(months=args.months, min_signals=args.min_signals)
    print(f"回测完成：{r['generated_at']}  策略 {r['strategies_total']} / 合格 {r['eligible']} / 耗时 {r['elapsed_s']}s")
    print()
    header = f"{'排名':<4}{'策略':<22}{'分类':<12}{'信号数':>6}{'5日胜率':>8}{'3日胜率':>8}{'10日':>7}{'5日均收益':>9}{'盈亏比':>7}{'综合分':>7}"
    print(header)
    for t in r["top"]:
        print(f"{t['rank']:<4}{t['name'][:20]:<22}{t['cat'][:10]:<12}{t['signals']:>6}"
              f"{t['win5']:>7}%{t['win3']:>7}%{str(t['win10']):>7}%{t['avg5']:>8}%{t['pf5']:>7}{t['score']:>7}")
    print("\n报告已保存 data/backtest_report.json")


if __name__ == "__main__":
    main()

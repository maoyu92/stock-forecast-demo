"""命令行历史数据同步（不依赖后端服务运行）

用法（在项目根目录）:
    .venv/Scripts/python scripts/sync_history.py                 # 增量更新全市场，2 年窗口
    .venv/Scripts/python scripts/sync_history.py --mode full     # 整窗重下
    .venv/Scripts/python scripts/sync_history.py --years 3       # 3 年历史（仅全量模式生效）
    .venv/Scripts/python scripts/sync_history.py --limit 300     # 只同步前 300 只（测试用）

同步期间会实时打印进度；数据写入 data/stock_forecast.db 的 kline_daily/kline_meta 表。
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    ap = argparse.ArgumentParser(description="A股历史K线全市场同步")
    ap.add_argument("--mode", choices=["update", "full"], default="update")
    ap.add_argument("--years", type=float, default=2.0, help="历史年限（全量模式生效）")
    ap.add_argument("--limit", type=int, default=0, help="只同步前 N 只（测试）")
    args = ap.parse_args()

    from app.services import histstore

    codes = []
    if args.limit:
        from app.services import datasource
        df = datasource.get_stock_list()
        codes = df["code"].tolist()[:args.limit]
        print(f"只同步前 {len(codes)} 只（--limit 测试模式）")

    st = histstore.sync(years=args.years, mode=args.mode, codes=codes or None)
    if not st.get("running"):
        print(f"同步未启动：{st}")
        return

    while True:
        time.sleep(3)
        s = histstore.sync_state()
        if not s.get("running"):
            break
        if s.get("total"):
            pct = s["done"] / s["total"] * 100
            print(f"\r[{s.get('phase','')}] {s['done']}/{s['total']} ({pct:.1f}%) "
                  f"成功 {s.get('ok',0)} 失败 {s.get('failed',0)}", end="", flush=True)
    s = histstore.sync_state()
    print(f"\n同步结束：{s.get('phase')}  成功 {s.get('ok',0)}  失败 {s.get('failed',0)}  "
          f"重下 {s.get('refetched',0)}  耗时 {s.get('elapsed','?')}s")
    stat = histstore.status()
    print(f"仓库状态：{stat['synced_stocks']} 只股票 / 数据截至 {stat['data_as_of']} / "
          f"{stat['kline_rows']} 行K线")


if __name__ == "__main__":
    main()

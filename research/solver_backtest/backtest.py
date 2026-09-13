# -*- coding: utf-8 -*-
"""10万本金 A股 求解器仓位策略回测
口径:
- 本金 100,000; 整手 100 股; 后复权价
- 费率: 单笔委托金额 ≤ 5000 元免佣金; > 5000 元佣金万8; 卖出另收印花税 0.05%; 滑点单边 0.1%
- 信号: 每周最后一个交易日收盘生成 → 下周首个交易日开盘执行 (周频, T+1 天然满足)
- 信号(纯价格): mom20/mom60 动量 + 低波动; 期望收益 r5 = 5日漂移估计(z分缩放)
- 评估: 期望值(每笔往返全含成本盈亏均值) + 年化/夏普/回撤; 胜率仅作参考
"""
import math
import os
import pickle
import sys
import time
from collections import deque

import cvxpy as cp
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)

# ---------------- 参数 ----------------
INIT_CASH = 100_000.0
LOT = 100
FREE_ORDER = 5_000.0          # 单笔 ≤5000 免佣
COMM = 8e-4                   # 万8
STAMP = 5e-4                  # 卖出印花税
SLIP = 1e-3                   # 单边滑点
START_TRADE = "2023-01-01"    # 回测起点(信号需60日预热)
W_MAX = 0.08                  # 单票上限(NAV占比)
IND_CAP = 0.30                # 行业上限
CARD_MAX = 22                 # MILP 持仓数上限
TURN_PEN = 0.002              # 换手惩罚(占NAV)
R5_SCALE = 0.01               # 5日期望收益截面缩放


def fee_buy_pure(v):
    return 0.0 if v <= FREE_ORDER else COMM * v


def fee_sell_pure(v):
    return (0.0 if v <= FREE_ORDER else COMM * v) + STAMP * v


def board_limit(code):
    if code.startswith("sh.688") or code.startswith("sz.30"):
        return 0.20
    if code.startswith("bj."):
        return 0.30
    return 0.10


# ---------------- 数据加载 ----------------
def load_panel():
    with open(os.path.join(CACHE, "klines.pkl"), "rb") as f:
        blob = pickle.load(f)
    klines, index_df = blob["klines"], blob["index"]
    with open(os.path.join(CACHE, "meta.pkl"), "rb") as f:
        meta = pickle.load(f)
    industry = meta["industry"]

    klines = {c: df.assign(date=pd.to_datetime(df["date"])).set_index("date")
              for c, df in klines.items()}

    def pivot(field):
        return pd.DataFrame({c: df[field] for c, df in klines.items()})

    close = pivot("close")
    openp = pivot("open")
    preclose = pivot("preclose")
    tstat = pivot("tradestatus")
    isst = pivot("isST")

    dates = pd.DatetimeIndex(index_df["date"]).sort_values()
    dates = dates[dates >= pd.Timestamp(START_TRADE)]
    close = close.reindex(dates).ffill()
    openp = openp.reindex(dates)
    preclose = preclose.reindex(dates)
    tstat = tstat.reindex(dates).fillna(0).astype(int)      # 无记录=停牌
    isst = isst.reindex(dates).fillna(0).astype(int)

    ret = close / preclose - 1.0
    lim = pd.Series({c: board_limit(c) for c in close.columns})
    limit_up = openp >= preclose.mul(1 + lim, axis=1) - 0.004
    limit_dn = openp <= preclose.mul(1 - lim, axis=1) + 0.004

    idx_close = index_df.assign(date=pd.to_datetime(index_df["date"])).set_index("date")["close"]
    return dict(dates=dates, close=close, open=openp, preclose=preclose, ret=ret,
                tstat=tstat, isst=isst, limit_up=limit_up, limit_dn=limit_dn,
                industry={c: industry.get(c, "未知") for c in close.columns},
                index=idx_close)


def rebalance_days(dates):
    s = pd.Series(dates, index=dates)
    iso = s.dt.isocalendar()
    wk = iso.year * 100 + iso.week
    firsts = s.groupby(wk.values).min()
    return set(dates.get_loc(d) for d in sorted(firsts))


# ---------------- 信号 ----------------
def signals_at(P, t):
    close, ret = P["close"], P["ret"]
    c0 = close.iloc[t]
    mom20 = c0 / close.iloc[t - 20] - 1
    mom60 = c0 / close.iloc[t - 60] - 1
    vol20 = ret.iloc[t - 19:t + 1].std()

    ok = (mom60.notna() & (P["isst"].iloc[t] == 0) & (P["tstat"].iloc[t] == 1)
          & (c0 >= 2.0) & vol20.notna())
    df = pd.DataFrame({"mom20": mom20, "mom60": mom60, "vol20": vol20})[ok]

    def z(s):
        sd = s.std()
        return ((s - s.mean()) / sd if sd > 0 else s * 0).clip(-3, 3)

    df["score"] = z(df["mom60"]) + z(df["mom20"]) - z(df["vol20"])
    r5_raw = 5.0 * (0.5 * df["mom20"] / 20 + 0.5 * df["mom60"] / 60)
    df["s5"] = R5_SCALE * z(r5_raw)
    df["lotval"] = c0[df.index] * LOT
    df["industry"] = pd.Series(P["industry"]).reindex(df.index)
    return df


def cov5_at(P, t, cols):
    r = P["ret"].iloc[t - 59:t + 1][cols].dropna(axis=1, thresh=40)
    cov = r.cov().reindex(index=cols, columns=cols).fillna(0.0)
    d = np.diag(cov.values).copy()
    shrunk = 0.5 * cov.values + 0.5 * np.diag(d)
    return shrunk * 5.0                        # 5日协方差


# ---------------- 组合引擎 ----------------
class Portfolio:
    def __init__(self, P, name):
        self.P, self.name = P, name
        self.cash = INIT_CASH
        self.lots = {}                          # code -> 手数
        self.fifo = {}                          # code -> deque[(手数, 全含成本/股)]
        self.nav_hist = []                      # (date, nav, n_pos)
        self.trades = []
        self.round_trips = []
        self.fees_paid = {"comm": 0.0, "stamp": 0.0, "slip": 0.0}
        self.n_orders_free = 0
        self.n_orders_all = 0
        self.turnover_val = 0.0

    def _record_buy_fee(self, v):
        self.n_orders_all += 1
        f = fee_buy_pure(v)
        if v <= FREE_ORDER:
            self.n_orders_free += 1
        else:
            self.fees_paid["comm"] += COMM * v
        return f

    def _record_sell_fee(self, v):
        self.n_orders_all += 1
        f = 0.0
        if v <= FREE_ORDER:
            self.n_orders_free += 1
        else:
            f += COMM * v
            self.fees_paid["comm"] += COMM * v
        f += STAMP * v
        self.fees_paid["stamp"] += STAMP * v
        return f

    def nav_at(self, t):
        close = self.P["close"].iloc[t]
        return self.cash + sum(l * LOT * close[c] for c, l in self.lots.items())

    def execute(self, t, target_lots, score_rank):
        P = self.P
        o = P["open"].iloc[t]
        tradable = (P["tstat"].iloc[t] == 1) & o.notna()
        lup, ldn = P["limit_up"].iloc[t], P["limit_dn"].iloc[t]

        # --- 先卖 ---
        for code in list(self.lots.keys()):
            if self.lots[code] <= 0:
                continue
            if not tradable.get(code, False) or bool(ldn.get(code, False)):
                continue                        # 停牌/跌停无法卖出
            sell_lots = self.lots[code] - target_lots.get(code, 0)
            if sell_lots <= 0:
                continue
            px = o[code] * (1 - SLIP)
            v = sell_lots * LOT * px
            fee = self._record_sell_fee(v)
            self.cash += v - fee
            self.fees_paid["slip"] += sell_lots * LOT * o[code] * SLIP
            self.turnover_val += v
            fee_ps = fee / (sell_lots * LOT)
            remain, pnl, cost_total = sell_lots, 0.0, 0.0
            q = self.fifo.setdefault(code, deque())
            while remain > 0 and q:
                blots, basis = q[0]
                use = min(blots, remain)
                pnl += use * LOT * (px - fee_ps - basis)
                cost_total += use * LOT * basis
                remain -= use
                if use == blots:
                    q.popleft()
                else:
                    q[0] = (blots - use, basis)
            self.lots[code] -= sell_lots
            if self.lots[code] == 0:
                del self.lots[code]
            if cost_total > 0:
                self.round_trips.append(dict(code=code, date=P["dates"][t], pnl=pnl,
                                             cost=cost_total, ret=pnl / cost_total))
            self.trades.append(dict(strategy=self.name, date=P["dates"][t], code=code,
                                    side="SELL", lots=sell_lots, value=v, fee=fee))

        # --- 后买 ---
        for code in score_rank:
            tgt = target_lots.get(code, 0)
            cur = self.lots.get(code, 0)
            need = tgt - cur
            if need <= 0 or self.cash < 200:
                continue
            if (not tradable.get(code, False) or bool(lup.get(code, False))
                    or P["isst"].iloc[t].get(code, 0) == 1):
                continue                        # 停牌/涨停买不进/ST 不新开仓
            px = o[code] * (1 + SLIP)
            lots = need
            while lots > 0 and lots * LOT * px + fee_buy_pure(lots * LOT * px) > self.cash:
                lots -= 1
            if lots <= 0:
                continue
            v = lots * LOT * px
            fee = self._record_buy_fee(v)
            self.cash -= v + fee
            self.fees_paid["slip"] += lots * LOT * o[code] * SLIP
            self.turnover_val += v
            self.fifo.setdefault(code, deque()).append((lots, px + fee / (lots * LOT)))
            self.lots[code] = cur + lots
            self.trades.append(dict(strategy=self.name, date=P["dates"][t], code=code,
                                    side="BUY", lots=lots, value=v, fee=fee))

    def mark(self, t):
        close = self.P["close"].iloc[t]
        n_pos = sum(1 for l in self.lots.values() if l > 0)
        self.nav_hist.append((self.P["dates"][t], self.nav_at(t), n_pos))


# ---------------- 策略 ----------------
def run_strategy(P, name, target_fn, rb_days):
    pf = Portfolio(P, name)
    dates = P["dates"]
    warm = 61
    for t in range(warm, len(dates)):
        if t in rb_days:
            t_sig = t - 1
            sig = signals_at(P, t_sig)
            nav_est = pf.nav_at(t_sig)
            target, rank = target_fn(sig, pf, t_sig, t, nav_est)
            pf.execute(t, target, rank)
        pf.mark(t)
    return pf


def naive_target(sig, pf, t_sig, t, nav_est, topn):
    elig = sig.sort_values("score", ascending=False).head(topn)
    budget = nav_est * 0.98 / topn
    target, rank = {}, []
    for code, row in elig.iterrows():
        lots = int(budget // row["lotval"])
        if lots >= 1:
            target[code] = lots
            rank.append(code)
    return target, rank


def make_naive(topn):
    def f(sig, pf, t_sig, t, nav_est):
        return naive_target(sig, pf, t_sig, t, nav_est, topn)
    return f


def _pool_with_prices(P, pf, sig, t_sig, topk):
    top = list(sig.sort_values("score", ascending=False).head(topk).index)
    pool = top + [c for c in pf.lots if c not in top]
    lc = P["close"].iloc[t_sig].reindex(pool)
    s = sig["s5"].reindex(pool).fillna(0.0)
    lotval = lc * LOT
    keep = [i for i, c in enumerate(pool)
            if (not math.isnan(lotval.iloc[i])) or pf.lots.get(c, 0) > 0]
    pool = [pool[i] for i in keep]
    s = s.iloc[keep].fillna(0.0).values
    lotval = lotval.iloc[keep].fillna(0.0).values
    return pool, s, lotval


def qp_target(sig, pf, t_sig, t, nav_est, lam):
    pool, s, lotval = _pool_with_prices(pf.P, pf, sig, t_sig, 100)
    if len(pool) < 5 or np.all(lotval == 0):
        return naive_target(sig, pf, t_sig, t, nav_est, 20)
    cov = cov5_at(pf.P, t_sig, pool)
    n = len(pool)
    w = cp.Variable(n)
    w_prev = np.array([pf.lots.get(c, 0) * lotval[i] / nav_est for i, c in enumerate(pool)])
    cons = [cp.sum(w) <= 0.995, w >= 0, w <= W_MAX]
    ind = np.array([pf.P["industry"][c] for c in pool])
    for g in pd.unique(ind):
        cons.append(cp.sum(w[ind == g]) <= IND_CAP)
    obj = cp.Maximize(s @ w - lam * cp.quad_form(w, cp.psd_wrap(cov))
                      - TURN_PEN * cp.norm1(w - w_prev))
    try:
        cp.Problem(obj, cons).solve(solver=cp.CLARABEL)
    except Exception:
        return naive_target(sig, pf, t_sig, t, nav_est, 20)
    if w.value is None:
        return naive_target(sig, pf, t_sig, t, nav_est, 20)
    target, rank = {}, []
    for i in np.argsort(-w.value):
        if w.value[i] <= 0:
            continue
        lots = int(w.value[i] * nav_est // lotval[i]) if lotval[i] > 0 else 0
        if lots >= 1:
            target[pool[i]] = lots
            rank.append(pool[i])
    return target, rank


def make_qp(lam):
    def f(sig, pf, t_sig, t, nav_est):
        return qp_target(sig, pf, t_sig, t, nav_est, lam)
    return f


def milp_target(sig, pf, t_sig, t, nav_est, fee_aware=True, w_max=W_MAX,
                turn_pen=TURN_PEN, card=CARD_MAX):
    pool, s, lotval = _pool_with_prices(pf.P, pf, sig, t_sig, 80)
    n = len(pool)
    if n == 0:
        return naive_target(sig, pf, t_sig, t, nav_est, 20)
    h = np.array([pf.lots.get(c, 0) for c in pool], dtype=int)
    cash_sig = pf.cash
    ind = np.array([pf.P["industry"][c] for c in pool])

    cap = np.minimum(np.where(lotval > 0, (w_max * nav_est) / np.maximum(lotval, 1), h), 200)
    cap = np.maximum(cap.astype(int), h)
    m = cp.Variable(n, integer=True)
    b = cp.Variable(n, boolean=True)
    zb = cp.Variable(n, boolean=True)
    zs = cp.Variable(n, boolean=True)
    buyv = cp.Variable(n, nonneg=True)
    sellv = cp.Variable(n, nonneg=True)
    fb = cp.Variable(n, nonneg=True)
    fs = cp.Variable(n, nonneg=True)

    d = cp.multiply(m - h, lotval)
    cons = [m >= 0, m <= cap, m <= cp.multiply(cap, b), m >= b,
            buyv >= d, sellv >= -d]
    if fee_aware:
        Mb = np.maximum(cap.astype(float) * lotval - FREE_ORDER, 0)
        cons += [buyv <= FREE_ORDER + cp.multiply(Mb, zb),
                 sellv <= FREE_ORDER + cp.multiply(Mb, zs),
                 fb >= COMM * buyv - COMM * FREE_ORDER * (1 - zb),
                 fs >= COMM * sellv - COMM * FREE_ORDER * (1 - zs)]
    else:
        cons += [fb >= COMM * buyv, fs >= COMM * sellv]
    cons.append(cash_sig + cp.sum(cp.multiply(sellv, 1 - STAMP - SLIP) - fs)
                - cp.sum(cp.multiply(buyv, 1 + SLIP) + fb) >= 0)
    cons.append(cp.sum(cp.multiply(m, lotval)) <= 0.995 * nav_est)
    for g in pd.unique(ind):
        cons.append(cp.sum(cp.multiply(m[ind == g], lotval[ind == g])) <= IND_CAP * nav_est)
    cons.append(cp.sum(b) <= card)

    obj = cp.Maximize(cp.sum(cp.multiply(cp.multiply(m, lotval), s))
                      - turn_pen / nav_est * cp.sum(buyv + sellv)
                      - cp.sum(fb + fs))
    try:
        cp.Problem(obj, cons).solve(solver=cp.HIGHS, time_limit=30.0)
    except Exception:
        return naive_target(sig, pf, t_sig, t, nav_est, 20)
    if m.value is None:
        return naive_target(sig, pf, t_sig, t, nav_est, 20)
    mv = np.round(m.value).astype(int)
    target, rank = {}, []
    for i in np.argsort(-s):
        if mv[i] >= 1:
            target[pool[i]] = int(mv[i])
            rank.append(pool[i])
    return target, rank


def make_milp(fee_aware, w_max=W_MAX, turn_pen=TURN_PEN, card=CARD_MAX):
    def f(sig, pf, t_sig, t, nav_est):
        return milp_target(sig, pf, t_sig, t, nav_est, fee_aware,
                           w_max=w_max, turn_pen=turn_pen, card=card)
    return f


# ---------------- 指标 ----------------
def metrics(pf):
    nav = pd.Series({d: v for d, v, _ in pf.nav_hist}).sort_index()
    r = nav.pct_change().dropna()
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    total = nav.iloc[-1] / INIT_CASH - 1
    cagr = (nav.iloc[-1] / INIT_CASH) ** (1 / years) - 1 if years > 0 else np.nan
    sharpe = r.mean() / r.std() * math.sqrt(252) if r.std() > 0 else np.nan
    dd = (nav / nav.cummax() - 1).min()
    rt = pd.DataFrame(pf.round_trips)
    return dict(name=pf.name, total=total, cagr=cagr, sharpe=sharpe, maxdd=dd,
                years=years, avg_pos=np.mean([p for _, _, p in pf.nav_hist]),
                fees_comm=pf.fees_paid["comm"], fees_stamp=pf.fees_paid["stamp"],
                fees_slip=pf.fees_paid["slip"],
                orders_free=pf.n_orders_free, orders_all=pf.n_orders_all,
                turnover_yy=pf.turnover_val / INIT_CASH / years if years else 0,
                n=len(rt),
                pnl_mean=rt["pnl"].mean() if len(rt) else 0.0,
                bps_mean=rt["ret"].mean() * 1e4 if len(rt) else 0.0,
                bps_median=rt["ret"].median() * 1e4 if len(rt) else 0.0,
                win_rate=rt["ret"].gt(0).mean() if len(rt) else np.nan)


def main():
    only = sys.argv[1:] or None
    P = load_panel()
    rb = rebalance_days(P["dates"])
    print(f"dates={len(P['dates'])} rebalances={len(rb)} codes={P['close'].shape[1]}", flush=True)

    configs = [
        ("naive_eq20", make_naive(20)),
        ("naive_eq10", make_naive(10)),
        ("qp_lam5", make_qp(5.0)),
        ("qp_lam20", make_qp(20.0)),
        ("milp_feeaware", make_milp(True)),
        ("milp_feeblind", make_milp(False)),
        ("milp_w5", make_milp(True, w_max=0.05)),
        ("milp_tp5", make_milp(True, turn_pen=0.005)),
    ]
    if only:
        configs = [c for c in configs if c[0] in only]

    summary = []
    for name, fn in configs:
        t0 = time.time()
        pf = run_strategy(P, name, fn, rb)
        m = metrics(pf)
        summary.append(m)
        pd.DataFrame(pf.trades).to_csv(os.path.join(RESULTS, f"{name}_trades.csv"),
                                       index=False, encoding="utf-8-sig")
        pd.DataFrame(pf.nav_hist, columns=["date", "nav", "n_pos"]).to_csv(
            os.path.join(RESULTS, f"{name}_equity.csv"), index=False)
        print(f"[{name}] {time.time()-t0:.0f}s | total={m['total']*100:.1f}% "
              f"cagr={m['cagr']*100:.1f}% sharpe={m['sharpe']:.2f} dd={m['maxdd']*100:.1f}% "
              f"E[pnl]={m['pnl_mean']:.1f}元 E[bps]={m['bps_mean']:.0f} n={m['n']} "
              f"pos={m['avg_pos']:.0f} free单={m['orders_free']}/{m['orders_all']}", flush=True)

    idx = P["index"].reindex(P["dates"]).dropna()
    years = (idx.index[-1] - idx.index[0]).days / 365.25
    ridx = idx.pct_change().dropna()
    summary.append(dict(name="hs300_bh", total=idx.iloc[-1] / idx.iloc[0] - 1,
                        cagr=(idx.iloc[-1] / idx.iloc[0]) ** (1 / years) - 1,
                        sharpe=ridx.mean() / ridx.std() * math.sqrt(252),
                        maxdd=(idx / idx.cummax() - 1).min(), n=np.nan, pnl_mean=np.nan,
                        bps_mean=np.nan, bps_median=np.nan, win_rate=np.nan, avg_pos=1,
                        fees_comm=0, fees_stamp=0, fees_slip=0, orders_free=0, orders_all=0,
                        turnover_yy=0, years=years))
    cols = ["name", "total", "cagr", "sharpe", "maxdd", "n", "pnl_mean", "bps_mean",
            "bps_median", "win_rate", "fees_comm", "fees_stamp", "fees_slip",
            "orders_free", "orders_all", "turnover_yy", "avg_pos"]
    sdf = pd.DataFrame(summary)[cols]
    old_path = os.path.join(RESULTS, "summary.csv")
    if os.path.exists(old_path):                    # 合并历史运行, 便于分批跑
        old = pd.read_csv(old_path)
        sdf = pd.concat([old[old["name"].isin(sdf["name"]) == False], sdf])[cols] \
            if len(old) else sdf
        sdf = sdf.drop_duplicates(subset="name", keep="last")
    sdf.to_csv(old_path, index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(sdf.to_string(index=False, float_format=lambda x: f"{x:,.4f}"), flush=True)


if __name__ == "__main__":
    main()

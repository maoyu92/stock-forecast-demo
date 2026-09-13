"""通达信风格公式引擎 —— 词法/语法/向量化求值

支持通达信选股公式的主要语法子集：
- 数据引用：OPEN/O HIGH/H LOW/L CLOSE/C VOL/V AMOUNT（大小写不敏感）
- 赋值：中间变量 `V:=表达式;`，输出线 `OUT:表达式;`（最后一条输出线为选股信号）
- 运算：+ - * / 比较(> < >= <= = <> !=) 逻辑(&& || AND OR NOT !)
- 注释：{...} 与 //...
- 函数：MA EMA SMA WMA HHV LLV HHVBARS LLVBARS REF CROSS COUNT EVERY EXIST
        BARSLAST BARSCOUNT SUM ABS MAX MIN IF POW SQRT LN LOG EXP SIGN MOD
        STD VAR AVEDEV VALUEWHEN CONST FILTER BACKSET BETWEEN UPNDAY DOWNNDAY SAR
- 语义尽量对齐通达信：CROSS=上穿、BARSLAST=距上次成立的天数、SMA(X,N,M)递归平滑等。
  注意：刻意不实现 ZIG/PEAK 等含未来函数的公式（用未来数据，选股结果会"回看修正"）。

求值为 pandas 向量化运算：整个公式对一只股票(约300根日K)毫秒级完成。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

# ============================ 词法 ============================

_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>\{[^}]*\}|//[^\n]*)
  | (?P<num>\d+\.\d*(?:[Ee][+-]?\d+)?|\.\d+(?:[Ee][+-]?\d+)?|\d+(?:[Ee][+-]?\d+)?)
  | (?P<id>[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*)
  | (?P<op>:=|<=|>=|<>|!=|==|&&|\|\||[-+*/<>=!(),;:])
""", re.VERBOSE)

_CMP_OPS = {">", "<", ">=", "<=", "=", "==", "<>", "!="}


def tokenize(src: str) -> list[tuple[str, str]]:
    """→ [(kind, text)]，kind ∈ num/id/op；标识符统一大写（通达信不区分大小写，
    支持中文变量名，如 多头排列、双阴埋伏）"""
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(src):
        m = _TOKEN_RE.match(src, pos)
        if not m:
            raise SyntaxError(f"公式第 {pos} 字符附近无法识别: {src[pos:pos + 12]!r}")
        pos = m.end()
        kind = m.lastgroup
        text = m.group()
        if kind in ("ws", "comment"):
            continue
        out.append((kind, text.upper() if kind == "id" else text))
    return out


# ============================ 语法树 ============================

@dataclass
class Num:
    v: float


@dataclass
class Var:
    name: str


@dataclass
class Call:
    name: str
    args: list


@dataclass
class Bin:
    op: str            # + - * / AND OR CMP
    l: object
    r: object


@dataclass
class Cmp:
    op: str            # 归一化后的比较符：> < >= <= = <>
    l: object
    r: object


@dataclass
class Un:
    op: str            # - + NOT
    x: object


@dataclass
class Stmt:
    name: str          # 变量名（裸表达式自动命名）
    expr: object
    is_output: bool


class Parser:
    def __init__(self, toks: list[tuple[str, str]]):
        self.toks = toks
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def next(self) -> tuple[str, str]:
        t = self.peek()
        if t is None:
            raise SyntaxError("公式意外结束")
        self.i += 1
        return t

    def expect(self, text: str) -> None:
        k, t = self.next()
        if t != text:
            raise SyntaxError(f"期望 {text!r}，实际 {t!r}")

    def parse_program(self) -> list[Stmt]:
        stmts: list[Stmt] = []
        out_idx = 0
        while self.peek() is not None:
            if self.peek()[1] == ";":  # 空语句
                self.next()
                continue
            t = self.peek()
            if t[0] == "id" and self.i + 1 < len(self.toks) \
                    and self.toks[self.i + 1][1] in (":=", ":"):
                name = self.next()[1]
                assign = self.next()[1]
                stmts.append(Stmt(name, self.parse_expr(), assign == ":"))
            else:
                out_idx += 1
                stmts.append(Stmt(f"_OUT{out_idx}", self.parse_expr(), True))
        if not stmts:
            raise SyntaxError("空公式")
        return stmts

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        l = self.parse_and()
        while (t := self.peek()) and t[1] in ("||", "OR"):
            self.next()
            l = Bin("OR", l, self.parse_and())
        return l

    def parse_and(self):
        l = self.parse_not()
        while (t := self.peek()) and t[1] in ("&&", "AND"):
            self.next()
            l = Bin("AND", l, self.parse_not())
        return l

    def parse_not(self):
        t = self.peek()
        if t and t[1] in ("!", "NOT"):
            self.next()
            return Un("NOT", self.parse_not())
        return self.parse_cmp()

    def parse_cmp(self):
        l = self.parse_add()
        t = self.peek()
        if t and t[1] in _CMP_OPS:
            self.next()
            op = {"==": "=", "!=": "<>"}.get(t[1], t[1])
            return Cmp(op, l, self.parse_add())
        return l

    def parse_add(self):
        l = self.parse_mul()
        while (t := self.peek()) and t[1] in ("+", "-"):
            self.next()
            l = Bin(t[1], l, self.parse_mul())
        return l

    def parse_mul(self):
        l = self.parse_unary()
        while (t := self.peek()) and t[1] in ("*", "/"):
            self.next()
            l = Bin(t[1], l, self.parse_unary())
        return l

    def parse_unary(self):
        t = self.peek()
        if t and t[1] in ("-", "+"):
            self.next()
            return Un(t[1], self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        k, t = self.next()
        if k == "num":
            return Num(float(t))
        if t == "(":
            e = self.parse_expr()
            self.expect(")")
            return e
        if k == "id":
            nxt = self.peek()
            if nxt and nxt[1] == "(":
                self.next()
                args = []
                if self.peek() and self.peek()[1] != ")":
                    args.append(self.parse_expr())
                    while self.peek() and self.peek()[1] == ",":
                        self.next()
                        args.append(self.parse_expr())
                self.expect(")")
                return Call(t, args)
            return Var(t)
        raise SyntaxError(f"意外的符号 {t!r}")


# ============================ 求值辅助 ============================

def _as_bool(x) -> pd.Series:
    if isinstance(x, pd.Series):
        return x.fillna(False).astype(bool)
    return pd.Series([bool(x)])


def _as_series(x, n: int) -> pd.Series:
    if isinstance(x, pd.Series):
        return x.astype(float)
    return pd.Series([float(x)] * n)


def _shift(x, k: int):
    return x.shift(k) if isinstance(x, pd.Series) else x


def _roll(x: pd.Series, n: int, fn: str):
    """rolling 聚合；n<=0 表示 expanding（通达信 HHV(X,0) 语义）"""
    if n <= 0:
        return getattr(x.expanding(), fn)()
    return getattr(x.rolling(n, min_periods=n), fn)()


def _ext_bars(x: pd.Series, n: int, sign: float) -> pd.Series:
    """距 n 周期极值点的天数：sign=1 最高 / -1 最低（含当日=0）"""
    out = np.full(len(x), np.nan)
    arr = (x.to_numpy(dtype=float)) * sign
    idx = np.arange(len(x))
    if n <= 0:
        run_max = pd.Series(arr).expanding().max().to_numpy()
        pos = np.where(arr >= run_max, idx, -1)
        last = np.maximum.accumulate(pos)
        out[:] = idx - last
        return pd.Series(out, index=x.index)
    if len(x) < n:
        return pd.Series(out, index=x.index)
    w = np.lib.stride_tricks.sliding_window_view(arr, n)
    arg = np.argmax(w, axis=1)  # 窗口内无 NaN 时正确（日K数据无缺口）
    out[n - 1:] = (n - 1) - arg
    return pd.Series(out, index=x.index)


def _sar(high: pd.Series, low: pd.Series, n: int, step: float, mx: float) -> pd.Series:
    """抛物线 SAR（通达信 SAR(N,S,M) 口径近似，S/M 为百分数值如 2/20）"""
    h, l = high.to_numpy(dtype=float), low.to_numpy(dtype=float)
    m = len(h)
    out = np.full(m, np.nan)
    if m < n + 2:
        return pd.Series(out, index=high.index)
    trend_up = h[n - 1] >= h[n - 2]
    ep = h[n - 1] if trend_up else l[n - 1]
    sar_v = l[n - 1] if trend_up else h[n - 1]
    af = step / 100.0
    for i in range(n, m):
        sar_v = sar_v + af * (ep - sar_v)
        if trend_up:
            sar_v = min(sar_v, l[i - 1], l[i - 2] if i >= 2 else l[i - 1])
            if l[i] < sar_v:               # 反转向下
                trend_up, sar_v, ep, af = False, ep, l[i], step / 100.0
            elif h[i] > ep:
                ep, af = h[i], min(af + step / 100.0, mx / 100.0)
        else:
            sar_v = max(sar_v, h[i - 1], h[i - 2] if i >= 2 else h[i - 1])
            if h[i] > sar_v:               # 反转向上
                trend_up, sar_v, ep, af = True, ep, h[i], step / 100.0
            elif l[i] < ep:
                ep, af = l[i], min(af + step / 100.0, mx / 100.0)
        out[i] = sar_v
    return pd.Series(out, index=high.index)


def _filter(x: pd.Series, n: int) -> pd.Series:
    """FILTER(X,N)：X 成立后其后 N-1 根K线信号清零（防止连续出信号）"""
    b = _as_bool(x).to_numpy()
    out = b.copy()
    cool = 0
    for i, v in enumerate(b):
        if cool > 0:
            out[i] = False
            cool -= 1
            if v:
                cool = n - 1
        elif v:
            cool = n - 1
    return pd.Series(out, index=x.index)


def _backset(x: pd.Series, n: int) -> pd.Series:
    """BACKSET(X,N)：X 成立位置及其之前 N-1 根置 1"""
    b = _as_bool(x).to_numpy()
    out = b.copy()
    for i in np.where(b)[0]:
        out[max(0, i - n + 1):i + 1] = True
    return pd.Series(out, index=x.index)


def _updown_nday(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).apply(
        lambda w: float(all(w[i] > w[i - 1] for i in range(1, len(w)))), raw=True)


def _make_env(df: pd.DataFrame, params: dict) -> dict:
    c, o, h, l = df["close"].astype(float), df["open"].astype(float), \
        df["high"].astype(float), df["low"].astype(float)
    v = df["volume"].astype(float)
    amt = df["amount"].astype(float) if "amount" in df else v * c
    return {
        "CLOSE": c, "C": c, "OPEN": o, "O": o, "HIGH": h, "H": h,
        "LOW": l, "L": l, "VOL": v, "V": v, "AMOUNT": amt,
        **{k.upper(): val for k, val in params.items()},
    }


def _call(name: str, a: list, env: dict):
    """内置函数求值。a 为已求值的参数（Series/float）"""

    def as_f(x, default=0.0) -> float:
        """参数位置的 Series 取最后有效值（周期参数允许传变量）"""
        if isinstance(x, pd.Series):
            s = x.dropna()
            return float(s.iloc[-1]) if len(s) else float(default)
        return float(x)

    n_rows = len(next(iter(env.values())))

    if name == "MA":
        return _roll(_as_series(a[0], n_rows), int(as_f(a[1])), "mean")
    if name == "EMA":
        return _as_series(a[0], n_rows).ewm(span=int(as_f(a[1])), adjust=False).mean()
    if name == "SMA":
        x = _as_series(a[0], n_rows)
        n, m = int(as_f(a[1])), float(as_f(a[2]))
        return x.ewm(alpha=m / n, adjust=False).mean()
    if name == "WMA":
        x, n = _as_series(a[0], n_rows), int(as_f(a[1]))
        w = np.arange(1, n + 1, dtype=float)
        return x.rolling(n, min_periods=n).apply(lambda win: float(np.dot(win, w) / w.sum()), raw=True)
    if name == "HHV":
        return _roll(_as_series(a[0], n_rows), int(as_f(a[1])), "max")
    if name == "LLV":
        return _roll(_as_series(a[0], n_rows), int(as_f(a[1])), "min")
    if name == "HHVBARS":
        return _ext_bars(_as_series(a[0], n_rows), int(as_f(a[1])), 1.0)
    if name == "LLVBARS":
        return _ext_bars(_as_series(a[0], n_rows), int(as_f(a[1])), -1.0)
    if name == "REF":
        return _shift(a[0], int(as_f(a[1])))
    if name == "CROSS":
        x, y = _as_series(a[0], n_rows), _as_series(a[1], n_rows)
        return (x > y) & (_shift(x, 1) <= _shift(y, 1))
    if name == "COUNT":
        return _roll(_as_bool(a[0]).astype(float), int(as_f(a[1])), "sum")
    if name == "EVERY":
        return _roll(_as_bool(a[0]).astype(float), int(as_f(a[1])), "min") > 0
    if name == "EXIST":
        return _roll(_as_bool(a[0]).astype(float), int(as_f(a[1])), "max") > 0
    if name == "BARSLAST":
        b = _as_bool(a[0]).to_numpy()
        idx = np.arange(len(b))
        last = np.maximum.accumulate(np.where(b, idx, -1))
        out = (idx - last).astype(float)
        out[last < 0] = len(b)  # 从未成立 → 大数
        return pd.Series(out, index=env["CLOSE"].index)
    if name == "BARSCOUNT":
        return pd.Series(np.arange(1, n_rows + 1, dtype=float), index=env["CLOSE"].index)
    if name == "SUM":
        return _roll(_as_series(a[0], n_rows), int(as_f(a[1])), "sum")
    if name == "ABS":
        return a[0].abs() if isinstance(a[0], pd.Series) else abs(a[0])
    if name in ("MAX", "MIN"):
        fn = np.maximum if name == "MAX" else np.minimum
        r = a[0]
        for b in a[1:]:
            if isinstance(r, pd.Series) or isinstance(b, pd.Series):
                r = pd.Series(fn(_as_series(r, n_rows), _as_series(b, n_rows)))
            else:
                r = fn(r, b)
        return r
    if name == "IF":
        cond = _as_bool(a[0])
        x = _as_series(a[1], n_rows)
        y = _as_series(a[2], n_rows)
        return pd.Series(np.where(cond, x, y), index=cond.index)
    if name == "POW":
        return _as_series(a[0], n_rows) ** as_f(a[1])
    if name == "SQRT":
        return np.sqrt(a[0])
    if name == "LN":
        return np.log(a[0])
    if name == "LOG":
        return np.log10(a[0])
    if name == "EXP":
        return np.exp(a[0])
    if name == "SIGN":
        return np.sign(a[0])
    if name == "MOD":
        x, y = _as_series(a[0], n_rows), _as_series(a[1], n_rows)
        return x - (x / y).round() * y
    if name == "STD":
        return _roll(_as_series(a[0], n_rows), int(as_f(a[1])), "std")
    if name == "VAR":
        return _roll(_as_series(a[0], n_rows), int(as_f(a[1])), "var")
    if name == "AVEDEV":
        x, n = _as_series(a[0], n_rows), int(as_f(a[1]))
        return x.rolling(n, min_periods=n).apply(
            lambda w: float(np.abs(w - w.mean()).mean()), raw=True)
    if name == "VALUEWHEN":
        cond = _as_bool(a[0])
        return _as_series(a[1], n_rows).where(cond).ffill()
    if name == "CONST":
        s = _as_series(a[0], n_rows).dropna()
        return float(s.iloc[-1]) if len(s) else float("nan")
    if name == "FILTER":
        return _filter(_as_series(a[0], n_rows), int(as_f(a[1])))
    if name == "BACKSET":
        return _backset(_as_series(a[0], n_rows), int(as_f(a[1])))
    if name == "BETWEEN":
        x, lo, hi = _as_series(a[0], n_rows), _as_series(a[1], n_rows), _as_series(a[2], n_rows)
        return (x >= lo) & (x <= hi)
    if name == "UPNDAY":
        return _updown_nday(_as_series(a[0], n_rows), int(as_f(a[1]))) > 0
    if name == "DOWNNDAY":
        return _updown_nday(-_as_series(a[0], n_rows), int(as_f(a[1]))) > 0
    if name == "SAR":
        return _sar(env["HIGH"], env["LOW"], int(as_f(a[0])), as_f(a[1], 2.0), as_f(a[2], 20.0))
    raise SyntaxError(f"不支持的函数: {name}")


# ============================ 编译与执行 ============================

class CompiledFormula:
    """编译后的公式：parse 一次，反复对多只股票求值"""

    def __init__(self, src: str):
        self.src = src
        self.stmts = Parser(tokenize(src)).parse_program()
        self.outputs = [s for s in self.stmts if s.is_output]
        if not self.outputs:
            raise SyntaxError("公式缺少输出线（形如 XG: 条件;）")

    def eval(self, df: pd.DataFrame, params: dict | None = None,
             at: int = -1, out: int = -1) -> tuple[pd.Series, dict]:
        """对单只股票求值。

        out 选择第几条输出线作为"信号"（-1=最后一条，-2=倒数第二条…），
        可让附加输出线（如强度 STRENGTH）不影响信号取值。
        返回 (信号 bool Series, 各变量在第 at 根K线(默认最后一根)的有效值 dict)
        """
        env = _make_env(df, params or {})
        with np.errstate(all="ignore"):
            for st in self.stmts:
                env[st.name] = self._eval_node(st.expr, env)
            sig = env[self.outputs[out].name]
        sig = _as_bool(sig) if not isinstance(sig, pd.Series) else sig.fillna(False).astype(bool)
        detail = {}
        for st in self.stmts:
            val = env[st.name]
            if isinstance(val, pd.Series):
                pos = len(val) + at if at < 0 else at
                s = val.iloc[:pos + 1].dropna()
                if len(s):
                    detail[st.name] = float(s.iloc[-1])
            else:
                detail[st.name] = float(val)
        # 基础序列也暴露给详情模板（C/O/H/L/V/AMOUNT）
        for key in ("C", "O", "H", "L", "V", "AMOUNT"):
            val = env.get(key)
            if isinstance(val, pd.Series):
                pos = len(val) + at if at < 0 else at
                s = val.iloc[:pos + 1].dropna()
                if len(s):
                    detail[key] = float(s.iloc[-1])
        return sig, detail

    def _eval_node(self, node, env: dict):
        if isinstance(node, Num):
            return node.v
        if isinstance(node, Var):
            if node.name not in env:
                raise NameError(f"未定义的变量或参数: {node.name}")
            return env[node.name]
        if isinstance(node, Call):
            return _call(node.name, [self._eval_node(a, env) for a in node.args], env)
        if isinstance(node, Un):
            v = self._eval_node(node.x, env)
            if node.op == "NOT":
                return ~_as_bool(v)
            return -v if node.op == "-" else v
        if isinstance(node, Bin):
            if node.op in ("AND", "OR"):
                l = _as_bool(self._eval_node(node.l, env))
                r = _as_bool(self._eval_node(node.r, env))
                return (l & r) if node.op == "AND" else (l | r)
            l = self._eval_node(node.l, env)
            r = self._eval_node(node.r, env)
            if node.op == "+":
                return l + r
            if node.op == "-":
                return l - r
            if node.op == "*":
                return l * r
            if node.op == "/":
                if isinstance(r, pd.Series):
                    r = r.replace(0, np.nan)
                    return l / r if isinstance(l, pd.Series) else l / r
                if r == 0:
                    if isinstance(l, pd.Series):
                        return pd.Series(np.full(len(l), np.nan), index=l.index)
                    return float("nan")
                return l / r
        if isinstance(node, Cmp):
            l = self._eval_node(node.l, env)
            r = self._eval_node(node.r, env)
            return {
                ">": lambda: l > r, "<": lambda: l < r,
                ">=": lambda: l >= r, "<=": lambda: l <= r,
                "=": lambda: l == r, "<>": lambda: l != r,
            }[node.op]()
        raise SyntaxError(f"无法求值的节点: {node!r}")


_parse_cache: dict[str, CompiledFormula] = {}


def compile_formula(src: str) -> CompiledFormula:
    key = src.strip()
    if key not in _parse_cache:
        _parse_cache[key] = CompiledFormula(key)
    return _parse_cache[key]

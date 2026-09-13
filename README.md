# A股 TimesFM 多因子预测系统

基于 Google **TimesFM 3.0** 时间序列基础模型的 A 股多因子价格预测系统。
选择目标股票 → 使用内置预设因子组合或自行添加任意个股/ETF/指数作为因子 → 一键预测，输出中位数走势 + 80% 置信带。

> 仅供学习研究，不构成任何投资建议。

## 功能

- 🔍 **股票搜索**：全 A 股代码/名称模糊匹配（约 5000 只）
- 🎯 **多策略智能选股**（通达信式，详见 [docs/PRD_多策略选股.md](docs/PRD_多策略选股.md) 与 [docs/PRD_智能选股.md](docs/PRD_智能选股.md)）：
  - **通达信风格公式引擎**：自建公式系统（`MA/CROSS/REF/HHV/BARSLAST/SMA...` 通达信语法子集，向量化求值，不含未来函数），策略全部用公式表达
  - **内置 116 个公式选股策略**（12 大类）：均线形态 / MACD动能 / 摆动指标 / BOLL轨道 / 量价关系 / K线形态 / 缠论结构(简化) / 趋势突破(海龟等) / 多条件共振 / 游资打法 / 资金监控(近似) / 风险提示——含用户材料整理的**均线金三角托、金蜘蛛、揉搓线（低位看涨/高位看跌）**与用户提供的通达信公式移植**游资进场、双阴等阳、BOLL强势回踩中轨、机构拉升·资金监控**
  - **本地历史K线仓库**（通达信式"先下载数据、本地选股"）：全市场 5000+ 只日K（前复权）落到 SQLite，多进程增量同步 + 除权漂移自愈；可选读取通达信本地 `.day` 文件（`TDX_VIPDOC_PATH`）
  - 全市场扫描 10~60 秒；信号有效期/板块/ST/成交额过滤；命中详情与强度百分位打分；CSV 导出、历史回看
  - **多策略组合选股**：多选公式策略做**交集**（全部命中，提纯）/ **并集**（任一命中，扩池），支持**排除集**（命中排除策略的股票剔除，如排除"顶分型"）；一次读K线评估全部公式，耗时与单策略相当
  - 保留并扩充**实时快照策略**（3 个）：摇钱树·量比选股法、主力动向、**主力净流入榜**（东财资金流聚合接口全市场排行 + 量价/趋势/强势状态打分，对标同花顺"主力净流入排行"）
  - 策略插件化注册，前端按参数 schema 动态渲染表单，新增方法零前端改动
  - **策略回测与每日荐股**：全市场全策略历史信号回测（1/3/5/10 日胜率、均收益、盈亏比、综合分排名），基于头部策略组合的每日荐股（命中≥2个头部策略 + 涨幅/流动性门控 + 风险信号排除），**无机会则明确提示观望/空仓**；定时任务每交易日收盘后自动运行（`scripts/backtest.py` / `scripts/daily_pick.py`）
  - **组合策略组回测**：5 个完整买卖策略组（趋势突破 / 回踩趋势 / 超跌反弹 / 资金动量 / TimesFM 增强），支持 ATR 止损、均线破位、时间退出、手续费/印花税/滑点、T+1、涨跌停近似约束、单票仓位与组合最大持仓，输出净值曲线、回撤、胜率、盈亏比和逐笔交易明细（`scripts/portfolio_backtest.py` / `/api/portfolio/*`）
  - 一键**「去预测」**：选股结果直接带入预测页联动
- 🧩 **多因子预测**：
  - **自动关联因子**：选股后自动识别板块（证监会行业分类），关联同板块龙头（上证50/沪深300成分，最多 2 个）+ 沪深300指数
  - 内置 4 组预设因子（中国太保 / 长江电力 / 工商银行 / 伊利股份，同业个股 + 沪深300 指数）
  - 自行添加任意 A 股个股、ETF、指数作为因子（因子逐个 z-score 标准化，防止量纲与信息泄漏问题）
  - 自定义因子组合可保存 / 复用 / 删除
- 🔮 **TimesFM 3.0 推理**，三种模式自动回退：
  | 模式 | 说明 |
  |---|---|
  | `remote` | SSH 连接局域网 GPU 服务器，常驻 worker（模型只加载一次，单次预测毫秒级） |
  | `local`  | 后端进程内直接加载 timesfm（需安装 `timesfm[torch]`） |
  | `mock`   | 模拟引擎（历史动量外推），保证无 GPU 环境全流程可用，前端明确标注 |
- 📈 **ECharts 可视化**：历史行情 / 预测曲线 / 置信带 / 预测明细表
- 💾 **SQLite**：预测历史 + 自定义因子组合持久化
- 🐳 **Docker Compose 一键部署**

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18 + Vite + TypeScript + Ant Design 5 + ECharts 5 |
| 后端 | FastAPI + Uvicorn |
| 存储 | SQLite（WAL） |
| 数据源 | baostock（K线主源）+ 东财直连（选股快照/资金流，主机回退链）+ akshare/新浪（备） |
| 模型 | TimesFM 3.0（`google/timesfm-3.0-pytorch`） |
| 部署 | Docker Compose（nginx + uvicorn） |

## 快速开始

### 方式一：Docker（推荐）

```bash
cp .env.example .env        # 按需修改（远程 GPU 地址、SSH 目录等）
docker compose up -d --build
```

访问 <http://localhost:8080>（前端），API 在 <http://localhost:8000/docs>。

> 注意：容器内不含 torch。`auto` 模式下会优先尝试远程 GPU 服务器（需要 `~/.ssh` 下有可用私钥），
> 不可达时自动回退到模拟模式，全流程仍可演示。

### 方式二：本地开发（真实 TimesFM 推理）

```bash
# 后端（Python ≥3.10）
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt
.venv/Scripts/pip install "timesfm[torch]"   # 本地推理需要（约 2GB）
cd backend
uvicorn app.main:app --port 8000 --reload

# 前端（Node ≥18）
cd frontend
npm install
npm run dev           # http://localhost:5173，已配置 /api 代理
```

### 启用局域网 GPU 服务器（毫秒级推理）

1. 确认本机 `ssh root@192.168.0.109` 可免密登录；
2. 一键部署常驻 worker（模型加载一次，常驻进程）：
   ```bash
   ./scripts/deploy_worker.sh        # 可传 host port 参数
   ```
3. 后端 `INFERENCE_MODE=auto`（或 `remote`）即可自动连接；
   页面右上角徽标显示 **远程 GPU TimesFM**。

## 测试股票（内置预设）

| 股票 | 代码 | 预设因子 |
|---|---|---|
| 中国太保 | sh.601601 | 中国平安、新华保险、沪深300指数 |
| 长江电力 | sh.600900 | 国投电力、华能水电、沪深300指数 |
| 工商银行 | sh.601398 | 建设银行、农业银行、沪深300指数 |
| 伊利股份 | sh.600887 | 光明乳业、新希望、沪深300指数 |

## API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务与各推理引擎健康状态 |
| GET | `/api/stocks/search?q=` | 股票搜索 |
| GET | `/api/stocks/kline?code=sh.601601&period=daily&days=365` | K线 |
| GET | `/api/data/status` | 本地K线仓库状态（覆盖/数据截至/同步进度） |
| POST | `/api/data/sync` | 启动历史数据同步（update=增量 / full=全量） |
| GET | `/api/screener/strategies` | 选股策略列表（119 个，含分类/参数/公式源码） |
| POST | `/api/screener/run` | 执行选股（公式策略走本地仓库，快照策略走实时快照） |
| POST | `/api/screener/run-multi` | 多策略组合选股（交集/并集 + 排除集，仅公式策略） |
| GET/DELETE | `/api/screener/runs` | 选股历史 |
| GET | `/api/factors/presets` | 内置预设因子组合 + ETF 快选 |
| GET | `/api/factors/auto?code=` | 自动关联因子（内置预设 / 板块龙头 + 沪深300） |
| GET/POST/DELETE | `/api/factors/groups` | 自定义因子组合 CRUD |
| POST | `/api/predict` | 预测（body: code, period, horizon, context_len, factors[]） |
| GET/DELETE | `/api/history` | 预测历史 |
| GET/POST | `/api/backtest/report` `/api/backtest/run` | 策略胜率回测报告 / 触发重跑 |
| GET/POST | `/api/portfolio/groups` `/api/portfolio/backtest` | 策略组定义 / 组合买卖回测 |
| GET | `/api/portfolio/report` `/api/portfolio/status` | 组合回测报告 / 运行状态 |
| GET | `/api/portfolio/runs` `/api/portfolio/runs/{id}` | 组合回测历史 / 单次明细 |

命令行同步历史数据（不依赖服务）：

```bash
.venv/Scripts/python scripts/sync_history.py                 # 增量更新全市场（2年窗口）
.venv/Scripts/python scripts/sync_history.py --mode full --years 3   # 全量重下 3 年
.venv/Scripts/python scripts/portfolio_backtest.py --months 12       # 组合策略组回测
.venv/Scripts/python scripts/portfolio_backtest.py --months 6 --limit 200  # 小样本冒烟
```

交互式文档：<http://localhost:8000/docs>

## 项目结构

```
stock-forecast-demo/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 入口
│   │   ├── config.py             # 环境变量配置
│   │   ├── db.py                 # SQLite（历史/因子组合/选股历史/K线仓库）
│   │   ├── schemas.py            # Pydantic 模型
│   │   ├── routers/              # stocks / factors / predict / history / screener / data / system
│   │   └── services/
│   │       ├── datasource.py     # baostock + akshare(新浪) 双源
│   │       ├── histstore.py      # 本地历史K线仓库（多进程同步/增量/除权自愈）
│   │       ├── tdxfile.py        # 通达信本地 .day 文件读取（可选）
│   │       ├── screener/
│   │       │   ├── moneytree.py / smartmoney.py   # V1 实时快照策略
│   │       │   └── formula/      # 公式引擎 engine.py + 112策略 catalog.py + 扫描 runner.py
│   │       ├── alignment.py      # 多因子对齐 + z-score（TimesFM §4.3 规范）
│   │       ├── predict.py        # 预测编排（引擎回退链）
│   │       └── inference/        # remote_ssh / local_timesfm / mock
│   ├── inference-worker/
│   │   └── infer_service.py      # GPU 服务器常驻 worker（仅 numpy+timesfm）
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/                # 预测 / 智能选股 / 历史 / 关于
│   │   ├── components/           # 图表、股票搜索
│   │   └── api.ts                # 类型化 API 客户端
│   ├── nginx.conf
│   └── Dockerfile
├── scripts/                      # 测试、历史数据同步（sync_history.py）与部署脚本
├── docs/                         # PRD 文档
├── docker-compose.yml
└── .env.example
```

## 关键设计说明

- **协变量形状规则**：`past_only_covariates` 严格等于上下文长度；每个因子用自身上下文段统计量 z-score（TimesFM 3.0 实战规范，防止数据泄漏）。
- **分位数方向兼容**：本地 timesfm 3.0.1 返回 `(horizon, 9)`，部分服务器版本返回 `(9, horizon)`，引擎层自动兼容。
- **引擎回退链**：`auto` 模式按 remote → local → mock 逐个尝试，单引擎故障不影响可用性；实际使用的模式会写进每条预测记录并在前端标注。
- **交易日历**：预测日期用 baostock 交易日历推算（缺失时退化为工作日）。
- **ETF 历史补全**：baostock 的 ETF 历史较短（2026 年起），自动回退新浪全历史数据。

## ⚠️ 免责声明

本工具仅供学习和研究使用，**不构成任何投资建议**。时间序列基础模型对股价的预测能力有限，
股市有风险，决策需谨慎。

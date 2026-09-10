# A股 TimesFM 3.0 多因子预测 Demo

基于 Google TimesFM 3.0 多因子时间序列基础模型的 A 股股票预测工具。

## 功能

- 🔍 股票搜索（代码/名称模糊匹配）
- 📊 多频率数据（1min/5min/15min/30min/60min/日线/周线/月线）
- 🧩 多因子模式：目标股票 + 行业 ETF + 沪深300 ETF + 美股 ETF
- 🔮 TimesFM 3.0 预测（支持协变量）
- 📈 ECharts 交互式图表（含置信区间）
- 💾 SQLite 预测历史保存

## 快速启动

```bash
cd /data/work/stock-forecast-demo
./start.sh
```

然后访问 http://localhost:8501

## 技术栈

| 组件 | 技术 |
|------|------|
| 模型 | Google TimesFM 2.5 (200M params, transformers) |
| 数据 | akshare (免费A股数据) |
| 前端 | Streamlit + ECharts |
| 存储 | SQLite |
| 运行时 | vllm_venv (PyTorch + CUDA) |

## 项目结构

```
stock-forecast-demo/
├── app.py                  # Streamlit 主界面
├── config.py               # 配置参数
├── start.sh                # 启动脚本
├── requirements.txt        # 依赖列表
├── data/
│   ├── stock_fetcher.py    # akshare 股票数据获取
│   └── db.py               # SQLite 数据库操作
├── model/
│   └── timesfm_predictor.py # TimesFM 预测封装
└── README.md
```

## 预测步长选项

- 7 步（短期）
- 16 步（中短期）
- 32 步（中期）
- 64 步（中长期）

## 数据频率

| 频率 | 说明 | 适用场景 |
|------|------|---------|
| 1分钟 | 分钟级K线 | 高频交易分析 |
| 5分钟 | 5分钟K线 | 短线分析 |
| 15分钟 | 15分钟K线 | 日内趋势 |
| 30分钟 | 30分钟K线 | 日内趋势 |
| 60分钟 | 60分钟K线 | 日内趋势 |
| 日线 | 每日K线 | 常规分析 |
| 周线 | 每周K线 | 中期趋势 |
| 月线 | 每月K线 | 长期趋势 |

## ⚠️ 免责声明

本工具仅供学习和研究使用，**不构成任何投资建议**。
股票市场存在风险，预测结果仅供参考，请谨慎决策。

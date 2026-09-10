# stock-forecast-demo 重写提示词

请基于 `/data/work/stock-forecast-demo/` 现有工程，重新设计并实现一个 A 股时序预测 Demo。先理解现有代码，再输出 PRD，然后按 PRD 增量实现。

## 一、现有工程理解要求
请先通读以下文件并总结：
- `README.md`
- `app.py`
- `config.py`
- `start.sh`
- `requirements.txt`
- `data/stock_fetcher.py`
- `data/multi_fetcher.py`
- `data/db.py`
- `model/timesfm_predictor.py`

## 二、PRD 输出要求
请输出完整 PRD，包含：
1. 产品定位与目标用户
2. 核心功能清单（MVP / V2）
3. 数据来源与处理逻辑
   - 明确主数据源、备用数据源
   - 数据清洗、缺失值处理、异常值处理
   - 复权方式、频率映射规则
4. 模型选型与推理逻辑
   - 明确 TimesFM 版本（2.5 或 3.0），说明选择理由
   - 单标的 / 多因子模式各自的输入构造方式
   - 预测步长、上下文长度、量化区间生成逻辑
5. 前后端交互流程
6. 数据库设计
7. 部署与运维要求
8. 风险与免责

## 三、实现要求
请直接对 `/data/work/stock-forecast-demo/` 做增量修改，不要新建平行项目。

### 强制约束
- 保留现有 `data/stock_fetcher.py` 的 baostock 为主、akshare 为备用的双源策略，不要改为单一 akshare
- 保留现有 `data/db.py` 的 SQLite 存储，不要引入新数据库
- 保留 Streamlit + ECharts 的技术栈
- 保留现有前端交互方式，可优化样式和错误提示

### 需要修复的问题
- 模型版本不一致：`config.py` 写的是 2.5，`timesfm_predictor.py` 和 `README.md` 写的是 3.0。请先调研最新官方文档，确认正确模型 ID 和 API，统一全项目版本。当前确认：`google/timesfm-3.0-pytorch` 为最新官方模型，API 使用 `timesfm.TimesFM3Forecaster`，调用方式为 `from_pretrained()` + `predict()`，不需要显式 `compile()` 或 `load_model()`；`ForecastConfig` 为 dataclass。
2. 分钟级频率支持缺失：`data/stock_fetcher.py` 目前不支持 1/5/15/30/60 分钟 K 线，需要补充 baostock 分钟级接口调用。
3. 多因子模式预设不足：目前只有中国太保一个预设，至少补充贵州茅台、宁德时代、比亚迪 3 个。
4. 错误处理不完整：baostock 登录失败、网络超时、空数据时前端提示不明确，需要统一异常处理。
5. 代码注释和类型提示不足，需要补充。

### 实现步骤
1. 先输出 PRD 文档到 `/data/work/stock-forecast-demo/docs/PRD.md`
2. 再按 PRD 逐步实现代码改动
3. 每完成一个模块，运行启动脚本验证
4. 最终交付可运行版本

## 四、验证要求
完成修改后，请执行 `./start.sh`，确认：
1. 服务正常启动在 8501
2. 能搜索到股票并显示名称
3. 能获取日线数据并预测
4. 历史记录页面正常显示

## 五、参考资料
- TimesFM 官方仓库：https://github.com/google-research/timesfm
- TimesFM 3.0 模型：https://huggingface.co/google/timesfm-3.0-pytorch
- baostock 文档：http://baostock.com/baostock/index.php

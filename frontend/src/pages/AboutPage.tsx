import { Card, Col, Row, Typography } from 'antd'

export default function AboutPage() {
  return (
    <Row justify="center">
      <Col xs={24} lg={18} xl={14}>
        <Card title="关于本项目">
          <Typography>
            <Typography.Title level={5}>🎯 项目简介</Typography.Title>
            <Typography.Paragraph>
              A 股多因子智能价格预测系统。用户自由选择目标股票后，系统自动关联
              <b>同板块龙头股（上证50/沪深300成分）与沪深300指数</b>作为多因子，
              也可自行添加任意个股/ETF/指数；底层由时间序列基础模型的协变量机制
              （past-only covariates，逐因子 z-score 标准化）完成预测。
            </Typography.Paragraph>

            <Typography.Title level={5}>🔧 技术栈</Typography.Title>
            <ul>
              <li>前端：React 18 + Vite + Ant Design + ECharts</li>
              <li>后端：FastAPI + SQLite（预测历史 / 自定义因子组合）</li>
              <li>数据源：baostock（主）+ akshare/新浪（备），日线/周线/月线</li>
              <li>推理：时间序列基础模型 —— 远程 GPU（SSH 常驻 worker）/ 本地 / 模拟 三模式自动回退</li>
              <li>部署：Docker Compose（frontend nginx + backend uvicorn）</li>
            </ul>

            <Typography.Title level={5}>🧩 多因子自动关联</Typography.Title>
            <ul>
              <li>检索选择任意 A 股后，自动识别其所属板块（证监会行业分类）。</li>
              <li>优先选取同板块的上证50成分股作为龙头因子，不足则按顺序补沪深300成分股（最多 2 个）。</li>
              <li>始终附加沪深300指数作为大盘基准因子；4 只热门股票提供人工校准的内置预设组合。</li>
            </ul>

            <Typography.Title level={5}>🔮 预测说明</Typography.Title>
            <ul>
              <li>上下文窗口取目标股票最近 N 个交易日的收盘价；因子对齐到目标交易日（停牌沿用前值）。</li>
              <li>预测输出为 9 分位中的中位数，前端展示 20%~80% 置信带。</li>
              <li>各因子使用自身上下文段统计量做标准化，避免未来信息泄漏。</li>
            </ul>

            <Typography.Title level={5}>⚠️ 免责声明</Typography.Title>
            <Typography.Paragraph type="warning">
              本工具仅供学习和研究使用，<b>不构成任何投资建议</b>。时间序列模型对股价的预测能力有限，
              股市有风险，决策需谨慎。
            </Typography.Paragraph>
          </Typography>
        </Card>
      </Col>
    </Row>
  )
}

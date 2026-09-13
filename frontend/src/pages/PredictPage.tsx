import {
  Alert, Button, Card, Col, Divider, Empty, Form, Input, List, Modal, Popconfirm,
  Row, Select, Space, Statistic, Table, Tag, Typography, message,
} from 'antd'
import { ClearOutlined, RocketOutlined, SaveOutlined, DeleteOutlined } from '@ant-design/icons'
import { useCallback, useEffect, useState } from 'react'
import { api, type FactorGroup, type ForecastRecord, type Preset, type StockRef } from '../api'
import ForecastChart from '../components/ForecastChart'
import StockSearch from '../components/StockSearch'

const PERIOD_OPTS = [
  { value: 'daily', label: '日线' },
  { value: 'weekly', label: '周线' },
  { value: 'monthly', label: '月线' },
]
const HORIZON_OPTS = [1, 3, 7, 14, 30].map(v => ({ value: v, label: `${v} 步` }))
const CONTEXT_OPTS = [60, 120, 180, 250, 365, 512].map(v => ({ value: v, label: `${v} 步` }))

const MODE_TAG: Record<string, { color: string; text: string }> = {
  remote: { color: 'green', text: '远程GPU推理' },
  local: { color: 'blue', text: '本地推理' },
  mock: { color: 'orange', text: '模拟模式（非真实推理）' },
}

export default function PredictPage({ presetStock }: { presetStock?: StockRef | null } = {}) {
  const [target, setTarget] = useState<StockRef | null>(null)
  const [period, setPeriod] = useState('daily')
  const [horizon, setHorizon] = useState(7)
  const [contextLen, setContextLen] = useState(180)
  const [factors, setFactors] = useState<StockRef[]>([])
  const [presets, setPresets] = useState<Preset[]>([])
  const [etfPicks, setEtfPicks] = useState<StockRef[]>([])
  const [groups, setGroups] = useState<FactorGroup[]>([])
  const [kline, setKline] = useState<{ dates: string[]; values: (number | null)[] } | null>(null)
  const [result, setResult] = useState<ForecastRecord | null>(null)
  const [factorSource, setFactorSource] = useState<{ industry: string | null; source: string; note: string } | null>(null)
  const [predicting, setPredicting] = useState(false)
  const [saveOpen, setSaveOpen] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [factorInput, setFactorInput] = useState<StockRef | null>(null)

  const refreshGroups = useCallback(() => {
    api.listGroups().then(d => setGroups(d.groups)).catch(() => {})
  }, [])

  useEffect(() => {
    api.presets().then(d => { setPresets(d.presets); setEtfPicks(d.etf_quick_picks) }).catch(() => {})
    refreshGroups()
    api.hotStocks().then(d => { if (d.results.length) setTarget(d.results[0]) }).catch(() => {})
  }, [refreshGroups])

  // 智能选股页"去预测"联动：外部带入目标股票时自动选中
  useEffect(() => {
    if (presetStock) setTarget(presetStock)
  }, [presetStock])

  // 选中目标后拉取 K线预览，并自动关联多因子（内置预设 / 同板块龙头 + 沪深300）
  useEffect(() => {
    setResult(null)
    setKline(null)
    setFactorSource(null)
    if (!target) return
    api.kline(target.code, period, 400)
      .then(k => setKline({ dates: k.dates, values: k.close }))
      .catch(() => {})
    api.autoFactors(target.code)
      .then(a => {
        setFactors(a.factors)
        setFactorSource(a)
      })
      .catch(() => {})
  }, [target, period])

  const addFactor = (s: StockRef | null) => {
    if (!s) return
    if (s.code === target?.code) { message.warning('目标股票本身无需作为因子'); return }
    if (factors.some(f => f.code === s.code)) { message.info('该因子已存在'); return }
    setFactors(fs => [...fs, s])
    setFactorInput(null)
  }

  const doPredict = async () => {
    if (!target) { message.warning('请先选择股票'); return }
    setPredicting(true)
    setResult(null)
    try {
      const rec = await api.predict({
        code: target.code, name: target.name, period, horizon, context_len: contextLen, factors,
      })
      setResult(rec)
      message.success(`预测完成（${MODE_TAG[rec.inference_mode]?.text ?? rec.inference_mode}）`)
    } catch (e) {
      message.error(`预测失败：${(e as Error).message}`)
    } finally {
      setPredicting(false)
    }
  }

  const applyPreset = (p: Preset) => {
    setTarget(p.target)
    setFactors(p.factors)
  }

  const saveGroup = async () => {
    if (!target || !saveName.trim()) return
    try {
      await api.saveGroup({ name: saveName.trim(), target_code: target.code, target_name: target.name, factors })
      message.success('组合已保存')
      setSaveOpen(false); setSaveName('')
      refreshGroups()
    } catch (e) { message.error((e as Error).message) }
  }

  const m = result?.metrics

  return (
    <Row gutter={[16, 16]}>
      {/* 左侧配置区 */}
      <Col xs={24} lg={9} xl={8}>
        <Card title="① 选择标的与参数" size="small">
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>目标股票</Typography.Text>
              <StockSearch value={target} onChange={setTarget} />
              {factorSource?.industry && (
                <Tag style={{ marginTop: 6 }} color="geekblue">板块：{factorSource.industry}</Tag>
              )}
              <div style={{ marginTop: 6 }}>
                <Space size={4} wrap>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>热门：</Typography.Text>
                  {presets.map(p => (
                    <Tag.CheckableTag key={p.name} checked={target?.code === p.target.code}
                      onClick={() => applyPreset(p)}>{p.name}</Tag.CheckableTag>
                  ))}
                </Space>
              </div>
            </div>
            <Row gutter={8}>
              <Col span={8}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>周期</Typography.Text>
                <Select value={period} onChange={setPeriod} options={PERIOD_OPTS} style={{ width: '100%' }} />
              </Col>
              <Col span={8}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>预测步长</Typography.Text>
                <Select value={horizon} onChange={setHorizon} options={HORIZON_OPTS} style={{ width: '100%' }} />
              </Col>
              <Col span={8}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>上下文长度</Typography.Text>
                <Select value={contextLen} onChange={setContextLen} options={CONTEXT_OPTS} style={{ width: '100%' }} />
              </Col>
            </Row>
          </Space>
        </Card>

        <Card title={`② 多因子配置（当前 ${factors.length} 个）`} size="small" style={{ marginTop: 16 }}
          extra={
            <Space>
              <Button size="small" icon={<SaveOutlined />} disabled={!factors.length}
                onClick={() => setSaveOpen(true)}>存为组合</Button>
              <Button size="small" icon={<ClearOutlined />} disabled={!factors.length}
                onClick={() => setFactors([])}>清空</Button>
            </Space>
          }>
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            <Space.Compact style={{ width: '100%' }}>
              <div style={{ flex: 1 }}>
                <StockSearch value={null} onChange={addFactor} placeholder="搜索并添加因子（个股 / ETF / 指数）" />
              </div>
            </Space.Compact>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>常用 ETF：</Typography.Text>
              {etfPicks.map(e => (
                <Tag key={e.code} style={{ cursor: 'pointer', marginBottom: 4 }}
                  onClick={() => addFactor(e)}>{e.name}</Tag>
              ))}
            </div>
            {factors.length === 0
              ? <Alert type="info" showIcon message="未选择因子：将进行单变量预测" />
              : (
                <List size="small" bordered header={
                  factorSource?.note ? (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      🔗 {factorSource.note}
                    </Typography.Text>
                  ) : undefined}
                  dataSource={factors} renderItem={(f, idx) => (
                  <List.Item
                    actions={[<Button key="del" type="text" size="small" danger icon={<DeleteOutlined />}
                      onClick={() => setFactors(fs => fs.filter((_, i) => i !== idx))} />]}
                  >
                    <span>{f.name}</span>
                    <Tag style={{ marginLeft: 8 }}>{f.code}</Tag>
                  </List.Item>
                )} />
              )}
            {groups.length > 0 && (
              <>
                <Divider style={{ margin: '4px 0' }} />
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>我保存的组合：</Typography.Text>
                  <List size="small" dataSource={groups} renderItem={g => (
                    <List.Item
                      actions={[
                        <Button key="apply" size="small" type="link"
                          onClick={() => { setTarget({ code: g.target_code, name: g.target_name }); setFactors(g.factors) }}>
                          应用
                        </Button>,
                        <Popconfirm key="del" title="删除该组合？" onConfirm={async () => {
                          await api.deleteGroup(g.id); refreshGroups()
                        }}>
                          <Button size="small" type="link" danger>删除</Button>
                        </Popconfirm>,
                      ]}
                    >
                      <span>{g.name}</span>
                      <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                        {g.target_name} · {g.factors.length} 因子
                      </Typography.Text>
                    </List.Item>
                  )} />
                </div>
              </>
            )}
          </Space>
        </Card>

        <Button type="primary" size="large" block icon={<RocketOutlined />} loading={predicting}
          onClick={doPredict} style={{ marginTop: 16 }}>
          {predicting ? '预测中（首次加载模型约需 1~2 分钟）…' : '③ 开始预测'}
        </Button>
      </Col>

      {/* 右侧结果区 */}
      <Col xs={24} lg={15} xl={16}>
        {result && (
          <Card size="small" title={
            <Space>
              <span>{result.stock_name} · 预测结果</span>
              <Tag color={MODE_TAG[result.inference_mode]?.color}>{MODE_TAG[result.inference_mode]?.text}</Tag>
              <Tag>{result.period === 'daily' ? '日线' : result.period === 'weekly' ? '周线' : '月线'} · {result.horizon}步 · 上下文{result.context_len}</Tag>
              {result.factor_names?.length ? <Tag>{result.factor_names.length} 因子</Tag> : <Tag>单变量</Tag>}
            </Space>
          }>
            <Row gutter={16} style={{ marginBottom: 12 }}>
              <Col span={5}><Statistic title="当前价格" value={m?.last_value} precision={2} /></Col>
              <Col span={5}><Statistic title={`${result.horizon}步后预测`} value={result.forecast.values[result.forecast.values.length - 1]} precision={2} /></Col>
              <Col span={5}>
                <Statistic title="预测涨跌" value={m?.predicted_change_pct} precision={2} suffix="%"
                  valueStyle={{ color: (m?.predicted_change_pct ?? 0) >= 0 ? '#cf1322' : '#3f8600' }} />
              </Col>
              <Col span={4}><Statistic title="预测最低" value={m?.forecast_min} precision={2} /></Col>
              <Col span={5}><Statistic title="预测最高" value={m?.forecast_max} precision={2} /></Col>
            </Row>
            {result.inference_detail && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>{result.inference_detail}</Typography.Text>
            )}
            <ForecastChart
              history={result.historical}
              forecast={result.forecast}
              band={result.quantiles}
              height={400}
            />
            {result.dropped_factors?.length ? (
              <Alert style={{ marginTop: 8 }} type="warning" showIcon
                message={`部分因子因数据不足未参与：${result.dropped_factors.map(d => `${d.name ?? d.code}(${d.reason})`).join('、')}`} />
            ) : null}
            <Table style={{ marginTop: 12 }} size="small" rowKey="date" pagination={false}
              columns={[
                { title: '日期', dataIndex: 'date' },
                { title: '预测值', dataIndex: 'value', render: (v: number) => v?.toFixed(2) },
                ...(result.quantiles.lower && result.quantiles.upper ? [
                  { title: '80%区间下界', dataIndex: 'lower', render: (v: number) => v?.toFixed(2) },
                  { title: '80%区间上界', dataIndex: 'upper', render: (v: number) => v?.toFixed(2) },
                ] : []),
              ]}
              dataSource={result.forecast.dates.map((d, i) => ({
                key: d, date: d, value: result.forecast.values[i],
                lower: result.quantiles.lower?.[i], upper: result.quantiles.upper?.[i],
              }))}
            />
          </Card>
        )}
        {!result && (
          <Card size="small" title="行情预览（最近 180 个交易日）">
            {kline
              ? <ForecastChart kline={kline} height={400} />
              : <Empty description={target ? '加载行情中…' : '请先在左侧选择股票'} style={{ padding: 60 }} />}
          </Card>
        )}
      </Col>

      <Modal title="保存因子组合" open={saveOpen} onOk={saveGroup} onCancel={() => setSaveOpen(false)}>
        <Form layout="vertical">
          <Form.Item label="组合名称" required>
            <Input value={saveName} onChange={e => setSaveName(e.target.value)}
              placeholder={`如：${target?.name ?? ''}-保险同业组合`} />
          </Form.Item>
          <Typography.Text type="secondary">
            目标：{target?.name}（{target?.code}）· {factors.length} 个因子
          </Typography.Text>
        </Form>
      </Modal>
    </Row>
  )
}

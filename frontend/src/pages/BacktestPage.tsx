import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts'
import {
  Alert, Button, Card, Col, Form, InputNumber, Progress, Row, Segmented, Select,
  Space, Statistic, Switch, Table, Tag, Typography, message,
} from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
import { api } from '../api'
import type {
  PortfolioBacktestRequest, PortfolioReport, PortfolioRun, PortfolioState, StrategyGroupDef,
} from '../api'

const EXIT_REASON_LABEL: Record<string, string> = {
  stop_loss: '止损',
  technical_exit: '技术破位',
  time_exit: '时间退出',
  signal_exit: '信号退出',
  backtest_end: '回测结束平仓',
}

function EquityChart({ runs }: { runs: PortfolioRun[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    const series = runs.map(r => ({
      name: r.group_name,
      type: 'line' as const,
      showSymbol: false,
      data: r.equity_curve.map(p => [p.date, p.equity]),
    }))
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { top: 0 },
      grid: { left: 60, right: 24, top: 36, bottom: 32 },
      xAxis: { type: 'category', data: runs[0]?.equity_curve.map(p => p.date) ?? [] },
      yAxis: { type: 'value', scale: true },
      series,
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [runs])
  return <div ref={ref} style={{ width: '100%', height: 360 }} />
}

export default function BacktestPage() {
  const [groups, setGroups] = useState<StrategyGroupDef[]>([])
  const [selectedGroups, setSelectedGroups] = useState<string[]>([])
  const [months, setMonths] = useState(12)
  const [initialCash, setInitialCash] = useState(1_000_000)
  const [maxPositions, setMaxPositions] = useState(8)
  const [maxExposure, setMaxExposure] = useState(0.95)
  const [feeRate, setFeeRate] = useState(0.0003)
  const [stampTaxRate, setStampTaxRate] = useState(0.0005)
  const [slippage, setSlippage] = useState(0.001)
  const [breadthThreshold, setBreadthThreshold] = useState(0.45)
  const [marketTiming, setMarketTiming] = useState(true)
  const [mode, setMode] = useState<'individual' | 'combined' | 'both'>('both')
  const [state, setState] = useState<PortfolioState | null>(null)
  const [report, setReport] = useState<PortfolioReport | null>(null)
  const [activeRun, setActiveRun] = useState<string>('')

  useEffect(() => {
    api.portfolioGroups()
      .then(d => {
        setGroups(d.groups)
        setSelectedGroups(d.groups.filter(g => g.enabled).map(g => g.id))
      })
      .catch(e => message.error((e as Error).message))
    api.portfolioReport().then(setReport).catch(() => setReport(null))
    api.portfolioStatus().then(setState).catch(() => {})
  }, [])

  useEffect(() => {
    if (!state?.running) return
    const t = setInterval(() => {
      api.portfolioStatus().then(s => {
        setState(s)
        if (!s.running) api.portfolioReport().then(setReport).catch(() => {})
      }).catch(() => {})
    }, 2000)
    return () => clearInterval(t)
  }, [state?.running])

  const run = useCallback(async () => {
    if (!selectedGroups.length) {
      message.warning('请至少选择一个策略组')
      return
    }
    const body: PortfolioBacktestRequest = {
      months, group_ids: selectedGroups, mode, initial_cash: initialCash,
      max_positions: maxPositions, max_exposure: maxExposure,
      fee_rate: feeRate, stamp_tax_rate: stampTaxRate, slippage,
      market_timing_enabled: marketTiming, market_breadth_threshold: breadthThreshold,
      board: '全部', exclude_st: true,
    }
    try {
      const r = await api.runPortfolioBacktest(body)
      setState(r.state)
      if (!r.started) message.info('已有回测在运行中')
    } catch (e) {
      message.error((e as Error).message)
    }
  }, [selectedGroups, months, mode, initialCash, maxPositions, maxExposure,
    feeRate, stampTaxRate, slippage, marketTiming, breadthThreshold])

  const runs = report?.runs ?? []
  const activeRunData = useMemo(() => {
    if (!runs.length) return null
    return runs.find(r => `${r.mode}:${r.group_id ?? r.group_name}` === activeRun) ?? runs[0]
  }, [runs, activeRun])

  useEffect(() => {
    if (runs.length && !activeRun) {
      const combined = runs.find(r => r.mode === 'combined')
      const first = combined ?? runs[0]
      setActiveRun(`${first.mode}:${first.group_id ?? first.group_name}`)
    }
  }, [runs, activeRun])

  const groupedOptions = useMemo(() => {
    const bySource = new Map<string, StrategyGroupDef[]>()
    groups.forEach(g => {
      const key = g.requires_forecast ? '模型增强' : '规则策略'
      if (!bySource.has(key)) bySource.set(key, [])
      bySource.get(key)!.push(g)
    })
    return [...bySource.entries()].map(([label, items]) => ({
      label, options: items.map(g => ({ value: g.id, label: g.name })),
    }))
  }, [groups])

  const tradeRows = useMemo(() => {
    if (!activeRunData) return []
    return activeRunData.trades.map((t, i) => ({ ...t, key: i }))
  }, [activeRunData])

  const exportCsv = () => {
    if (!activeRunData) return
    const header = ['group_id', 'code', 'name', 'signal_date', 'entry_date', 'exit_date',
      'entry_price', 'exit_price', 'shares', 'return_pct', 'pnl', 'holding_days', 'exit_reason']
    const lines = [header.join(',')]
    activeRunData.trades.forEach(t => {
      lines.push(header.map(k => (t as any)[k] ?? '').join(','))
    })
    const blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `组合回测交易_${activeRunData.group_name}_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const groupColumns = [
    { title: '模式', dataIndex: 'mode', width: 100, render: (v: string) => v === 'combined' ? '组合' : '单独' },
    { title: '策略组', dataIndex: 'group_name', width: 180 },
    { title: '收益', dataIndex: ['metrics', 'total_return_pct'], width: 90,
      render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{v}%</span> },
    { title: '年化', dataIndex: ['metrics', 'annualized_return_pct'], width: 90,
      render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{v}%</span> },
    { title: '最大回撤', dataIndex: ['metrics', 'max_drawdown_pct'], width: 100,
      render: (v: number) => <span style={{ color: '#3f8600' }}>{v}%</span> },
    { title: '夏普', dataIndex: ['metrics', 'sharpe'], width: 80 },
    { title: '胜率', dataIndex: ['metrics', 'win_rate_pct'], width: 90,
      render: (v: number) => `${v}%` },
    { title: '盈亏比', dataIndex: ['metrics', 'profit_factor'], width: 90 },
    { title: '交易', dataIndex: ['metrics', 'trades'], width: 80 },
    { title: '平均持仓', dataIndex: ['metrics', 'avg_holding_days'], width: 100,
      render: (v: number) => `${v} 日` },
    { title: '最大暴露', dataIndex: ['metrics', 'max_exposure_pct'], width: 100,
      render: (v: number) => `${v}%` },
  ]

  const tradeColumns = [
    { title: '策略组', dataIndex: 'group_id', width: 130 },
    { title: '代码', dataIndex: 'code', width: 100 },
    { title: '名称', dataIndex: 'name', width: 110 },
    { title: '信号日', dataIndex: 'signal_date', width: 100 },
    { title: '买入日', dataIndex: 'entry_date', width: 100 },
    { title: '卖出日', dataIndex: 'exit_date', width: 100 },
    { title: '买入价', dataIndex: 'entry_price', width: 90 },
    { title: '卖出价', dataIndex: 'exit_price', width: 90 },
    { title: '数量', dataIndex: 'shares', width: 80 },
    { title: '收益', dataIndex: 'return_pct', width: 90,
      render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{v}%</span> },
    { title: '盈亏', dataIndex: 'pnl', width: 100,
      render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{v}</span> },
    { title: '持仓天数', dataIndex: 'holding_days', width: 100 },
    { title: '退出原因', dataIndex: 'exit_reason', width: 110,
      render: (v: string) => EXIT_REASON_LABEL[v] ?? v },
  ]

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={8}>
        <Card size="small" title="回测设置">
          <Form layout="vertical" size="small">
            <Form.Item label="策略组">
              <Select
                mode="multiple"
                style={{ width: '100%' }}
                placeholder="选择策略组"
                value={selectedGroups}
                onChange={setSelectedGroups}
                options={groupedOptions}
                optionFilterProp="label"
              />
            </Form.Item>
            <Form.Item label="回测模式">
              <Segmented
                value={mode}
                onChange={v => setMode(v as any)}
                options={[
                  { label: '单独', value: 'individual' },
                  { label: '组合', value: 'combined' },
                  { label: '全部', value: 'both' },
                ]}
              />
            </Form.Item>
            <Row gutter={8}>
              <Col span={12}>
                <Form.Item label="回溯月数">
                  <InputNumber min={1} max={24} style={{ width: '100%' }}
                    value={months} onChange={v => setMonths(Number(v) || 12)} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="初始资金">
                  <InputNumber min={100000} step={100000} style={{ width: '100%' }}
                    value={initialCash} onChange={v => setInitialCash(Number(v) || 1000000)} />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={8}>
              <Col span={12}>
                <Form.Item label="最大持仓数">
                  <InputNumber min={1} max={50} style={{ width: '100%' }}
                    value={maxPositions} onChange={v => setMaxPositions(Number(v) || 8)} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="最大暴露">
                  <InputNumber min={0.1} max={1} step={0.05} style={{ width: '100%' }}
                    value={maxExposure} onChange={v => setMaxExposure(Number(v) || 0.95)} />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={8}>
              <Col span={8}>
                <Form.Item label="佣金">
                  <InputNumber min={0} max={0.01} step={0.0001} style={{ width: '100%' }}
                    value={feeRate} onChange={v => setFeeRate(Number(v) || 0)} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item label="印花税">
                  <InputNumber min={0} max={0.01} step={0.0001} style={{ width: '100%' }}
                    value={stampTaxRate} onChange={v => setStampTaxRate(Number(v) || 0)} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item label="滑点">
                  <InputNumber min={0} max={0.05} step={0.001} style={{ width: '100%' }}
                    value={slippage} onChange={v => setSlippage(Number(v) || 0)} />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={8}>
              <Col span={12}>
                <Form.Item label="市场宽度阈值">
                  <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }}
                    value={breadthThreshold}
                    onChange={v => setBreadthThreshold(Number(v) || 0)} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="启用择时">
                  <Switch checked={marketTiming} onChange={setMarketTiming} />
                </Form.Item>
              </Col>
            </Row>
            <Button type="primary" icon={<PlayCircleOutlined />} loading={state?.running}
              onClick={run} block>
              开始回测
            </Button>
            {state?.running && (
              <div style={{ marginTop: 12 }}>
                <Typography.Text type="secondary">{state.phase}</Typography.Text>
                <Progress
                  percent={state.total ? Math.round(state.done / state.total * 100) : 0}
                  status="active" />
              </div>
            )}
            {state?.error && <Alert type="error" message={state.error} style={{ marginTop: 12 }} />}
          </Form>
        </Card>
      </Col>

      <Col xs={24} lg={16}>
        <Card size="small" title="回测结果">
          {report?.warnings?.map((w, i) => <Alert key={i} type="warning" message={w} style={{ marginBottom: 12 }} />)}
          {!report && <Typography.Text type="secondary">尚无回测结果</Typography.Text>}
          {report && (
            <>
              <Space wrap style={{ marginBottom: 12 }}>
                <Tag color="blue">{report.universe_size} 只股票</Tag>
                <Tag>{report.start_date} ~ {report.end_date}</Tag>
                <Tag>{report.elapsed_s}s</Tag>
                <Tag color="geekblue">{report.generated_at}</Tag>
              </Space>
              <Row gutter={[12, 12]}>
                {(() => {
                  const combined = report.runs.find(r => r.mode === 'combined') ?? report.runs[0]
                  if (!combined) return null
                  return (
                    <>
                      <Col xs={12} md={6}><Statistic title="总收益" value={combined.metrics.total_return_pct} suffix="%" precision={2} /></Col>
                      <Col xs={12} md={6}><Statistic title="最大回撤" value={combined.metrics.max_drawdown_pct} suffix="%" precision={2} /></Col>
                      <Col xs={12} md={6}><Statistic title="胜率" value={combined.metrics.win_rate_pct} suffix="%" precision={2} /></Col>
                      <Col xs={12} md={6}><Statistic title="交易次数" value={combined.metrics.trades} /></Col>
                    </>
                  )
                })()}
              </Row>
              <div style={{ marginTop: 16 }}>
                <EquityChart runs={runs} />
              </div>
              <Table
                style={{ marginTop: 16 }}
                size="small"
                rowKey={r => `${r.mode}:${r.group_id ?? r.group_name}`}
                columns={groupColumns}
                dataSource={report.runs}
                pagination={false}
                scroll={{ x: 1100 }}
              />
              <Card size="small" title="交易明细" style={{ marginTop: 16 }}
                extra={(
                  <Space>
                    <Select
                      style={{ width: 220 }}
                      value={activeRun}
                      onChange={setActiveRun}
                      options={report.runs.map(r => ({
                        value: `${r.mode}:${r.group_id ?? r.group_name}`,
                        label: `${r.mode === 'combined' ? '组合' : '单独'} · ${r.group_name}`,
                      }))}
                    />
                    <Button size="small" onClick={exportCsv}>导出CSV</Button>
                  </Space>
                )}>
                <Table
                  size="small"
                  rowKey={r => r.key}
                  columns={tradeColumns}
                  dataSource={tradeRows}
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                  scroll={{ x: 1200 }}
                />
              </Card>
              <Alert
                style={{ marginTop: 12 }}
                type="info"
                message="回测包含手续费、印花税、滑点、T+1 与涨跌停近似约束；历史结果不代表未来表现。"
              />
            </>
          )}
        </Card>
      </Col>
    </Row>
  )
}

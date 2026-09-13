import {
  Alert, Button, Card, Col, Collapse, Drawer, Empty, InputNumber,
  Popconfirm, Progress, Row, Segmented, Select, Space, Switch, Table, Tag,
  Tooltip, Typography, message,
} from 'antd'
import {
  CloudDownloadOutlined, DatabaseOutlined, DownloadOutlined, HistoryOutlined,
  ReloadOutlined, RocketOutlined,
} from '@ant-design/icons'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api, type DataStatus, type ScreenRunMeta, type ScreenRunResult,
  type ScreenStock, type ScreenStrategy, type StockRef,
} from '../api'

/** 权重类参数单独分组渲染（key 以 w_ 开头） */
const isWeightParam = (key: string) => key.startsWith('w_')

/** 组合模式下各策略共享的公共参数（其余专属参数用各自默认值） */
const COMMON_KEYS = ['within_n', 'board', 'exclude_st', 'min_amount']

type ParamValue = number | boolean | string

function defaultParams(s: ScreenStrategy): Record<string, ParamValue> {
  const out: Record<string, ParamValue> = {}
  s.params.forEach(p => { out[p.key] = p.default })
  return out
}

export default function ScreenerPage({ onGoPredict }: { onGoPredict: (s: StockRef) => void }) {
  const [strategies, setStrategies] = useState<ScreenStrategy[]>([])
  const [strategyId, setStrategyId] = useState<string>('')
  const [comboMode, setComboMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [combine, setCombine] = useState<'or' | 'and'>('or')
  const [excludeIds, setExcludeIds] = useState<string[]>([])
  const [params, setParams] = useState<Record<string, ParamValue>>({})
  const [running, setRunning] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [result, setResult] = useState<ScreenRunResult | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [runs, setRuns] = useState<ScreenRunMeta[]>([])
  const [viewingRun, setViewingRun] = useState<number | null>(null)
  const [dataStatus, setDataStatus] = useState<DataStatus | null>(null)
  const [syncYears, setSyncYears] = useState(2)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const strategy = useMemo(() => strategies.find(s => s.id === strategyId), [strategies, strategyId])
  const isFormula = strategy?.kind === 'formula'

  // 组合模式：当前参数模板取第一个已选策略（公共参数各策略一致）
  const comboStrategy = useMemo(
    () => strategies.find(s => s.id === selectedIds[0] && s.kind === 'formula'),
    [strategies, selectedIds])
  const activeStrategy = comboMode ? comboStrategy : strategy
  const isCombo = comboMode && !!comboStrategy

  // 分组：公式策略按分类，快照策略归为"实时快照"
  const groupedOptions = useMemo(() => {
    const groups = new Map<string, { value: string; label: string }[]>()
    const order = ['均线形态', 'MACD动能', '摆动指标', 'BOLL轨道', '量价关系', 'K线形态',
      '缠论结构(简化)', '趋势突破', '多条件共振', '游资打法', '资金监控(近似)', '风险提示', '实时快照']
    const push = (cat: string, o: { value: string; label: string }) => {
      if (!groups.has(cat)) groups.set(cat, [])
      groups.get(cat)!.push(o)
    }
    strategies.forEach(s => {
      push(s.kind === 'formula' ? s.category || '公式策略' : '实时快照',
        { value: s.id, label: s.name })
    })
    return [...groups.entries()]
      .sort((a, b) => {
        const ia = order.indexOf(a[0]); const ib = order.indexOf(b[0])
        return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
      })
      .map(([cat, opts]) => ({ key: cat, label: `${cat}（${opts.length}）`, options: opts }))
  }, [strategies])

  // 组合模式下快照策略不可选（数据口径不同，不参与集合运算）
  const comboSelectOptions = useMemo(() => groupedOptions.map(g => ({
    ...g,
    options: g.options.map(o => {
      const st = strategies.find(s => s.id === o.value)
      return st?.kind === 'snapshot' ? { ...o, disabled: true } : o
    }),
  })), [groupedOptions, strategies])

  // 排除策略候选：未参与组合的公式策略
  const excludeOptions = useMemo(() =>
    strategies
      .filter(s => s.kind === 'formula' && !selectedIds.includes(s.id))
      .map(s => ({ value: s.id, label: `${s.category}·${s.name}` })),
  [strategies, selectedIds])

  const pollDataStatus = useCallback(async () => {
    try {
      const st = await api.dataStatus()
      setDataStatus(st)
      return st
    } catch { return null }
  }, [])

  useEffect(() => {
    api.screenerStrategies()
      .then(d => {
        setStrategies(d.strategies)
        if (d.strategies.length) {
          setStrategyId(d.strategies[0].id)
          setParams(defaultParams(d.strategies[0]))
        }
      })
      .catch(e => message.error(`加载选股方法失败：${(e as Error).message}`))
    pollDataStatus()
  }, [pollDataStatus])

  // 同步进行中每 2 秒轮询进度
  const syncRunning = dataStatus?.sync?.running
  useEffect(() => {
    if (!syncRunning) return
    const t = setInterval(pollDataStatus, 2000)
    return () => clearInterval(t)
  }, [syncRunning, pollDataStatus])

  const startSync = async (mode: 'update' | 'full') => {
    try {
      await api.dataSync({ mode, years: syncYears })
      message.info(mode === 'full' ? '全量同步已启动，请在下方查看进度' : '增量同步已启动')
      await pollDataStatus()
    } catch (e) { message.error((e as Error).message) }
  }

  const switchStrategy = (id: string) => {
    setStrategyId(id)
    const s = strategies.find(x => x.id === id)
    if (s) setParams(defaultParams(s))
    setResult(null)
    setViewingRun(null)
  }

  const startTimer = () => {
    setElapsed(0)
    timerRef.current = setInterval(() => setElapsed(t => t + 1), 1000)
  }
  const stopTimer = () => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
  }
  useEffect(() => stopTimer, [])

  const doRun = async () => {
    if (comboMode) {
      if (selectedIds.length === 0) { message.warning('请先选择至少 1 个策略'); return }
      if (combine === 'and' && selectedIds.length < 2) { message.warning('交集至少需要选择 2 个策略'); return }
      setRunning(true)
      setResult(null)
      setViewingRun(null)
      startTimer()
      try {
        const r = await api.runScreenMulti({
          strategy_ids: selectedIds, combine, exclude_ids: excludeIds, params,
        })
        setResult(r)
        const extra = r.excluded ? `，已排除 ${r.excluded} 只` : ''
        message.success(`组合选股完成：${r.result_count} 只入选${extra}（耗时 ${(r.elapsed_ms / 1000).toFixed(1)} 秒）`)
        pollDataStatus()
      } catch (e) {
        message.error(`组合选股失败：${(e as Error).message}`)
      } finally {
        stopTimer()
        setRunning(false)
      }
      return
    }
    if (!strategy) return
    setRunning(true)
    setResult(null)
    setViewingRun(null)
    startTimer()
    try {
      const r = await api.runScreen({ strategy_id: strategy.id, params })
      setResult(r)
      message.success(`选股完成：${r.result_count} 只入选（耗时 ${(r.elapsed_ms / 1000).toFixed(1)} 秒）`)
      pollDataStatus()
    } catch (e) {
      message.error(`选股失败：${(e as Error).message}`)
    } finally {
      stopTimer()
      setRunning(false)
    }
  }

  const openHistory = async () => {
    setHistoryOpen(true)
    try {
      const d = await api.screenRuns(50)
      setRuns(d.runs)
    } catch (e) { message.error((e as Error).message) }
  }

  const viewRun = async (id: number) => {
    try {
      const d = await api.screenRun(id)
      setResult({
        run_id: d.id, strategy_id: d.strategy_id, strategy_name: d.strategy_name,
        params: d.params, snapshot_time: d.snapshot_time ?? '',
        total_screened: d.total_screened ?? 0, candidates: d.result_count,
        elapsed_ms: d.elapsed_ms ?? 0, result_count: d.result_count,
        results: d.results, disclaimer: '',
      })
      setViewingRun(id)
      setHistoryOpen(false)
    } catch (e) { message.error((e as Error).message) }
  }

  const deleteRun = async (id: number) => {
    try {
      await api.deleteScreenRun(id)
      setRuns(rs => rs.filter(r => r.id !== id))
      if (viewingRun === id) { setViewingRun(null); setResult(null) }
      message.success('已删除')
    } catch (e) { message.error((e as Error).message) }
  }

  const exportCsv = () => {
    if (!result?.results.length) return
    const header = '排名,代码,名称,信号日,收盘价,涨跌幅%,成交额(亿),强度分,命中详情'
    const lines = result.results.map(r => {
      const hits = r.factors.filter(f => f.hit).map(f => f.name).join('；')
      return [r.rank, r.code, r.name, r.signal_date ?? '', r.price, r.pct,
        ((r.amount ?? 0) / 1e8).toFixed(2), r.score, `${hits} ${r.detail ?? ''}`.trim()].join(',')
    })
    const blob = new Blob(['\uFEFF' + [header, ...lines].join('\n')], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `智能选股_${result.strategy_name}_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const renderParam = (key: string) => {
    const p = activeStrategy?.params.find(x => x.key === key)
    if (!p) return null
    if (p.type === 'bool') {
      return (
        <Space key={p.key} style={{ marginBottom: 8 }}>
          <Tooltip title={p.description}><span style={{ fontSize: 13 }}>{p.label}</span></Tooltip>
          <Switch checked={Boolean(params[p.key])}
            onChange={v => setParams(ps => ({ ...ps, [p.key]: v }))} />
        </Space>
      )
    }
    if (p.type === 'select') {
      return (
        <div key={p.key} style={{ marginBottom: 8 }}>
          <Tooltip title={p.description}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{p.label}</Typography.Text>
          </Tooltip>
          <Select value={String(params[p.key] ?? p.default)} style={{ width: '100%' }}
            options={(p.options ?? []).map(o => ({ value: o.value, label: o.label }))}
            onChange={v => setParams(ps => ({ ...ps, [p.key]: v }))} />
        </div>
      )
    }
    return (
      <div key={p.key} style={{ marginBottom: 8 }}>
        <Tooltip title={p.description}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{p.label}</Typography.Text>
        </Tooltip>
        <InputNumber value={Number(params[p.key])} min={p.minimum ?? undefined} max={p.maximum ?? undefined}
          step={p.step ?? 1} style={{ width: '100%' }}
          addonAfter={p.unit || undefined}
          onChange={v => setParams(ps => ({ ...ps, [p.key]: v ?? p.default as number }))} />
      </div>
    )
  }

  const snapshotCols = result?.results.some(r => r.volume_ratio != null || r.turnover != null)
  const columns = [
    { title: '#', dataIndex: 'rank', width: 48 },
    {
      title: '股票', width: 145,
      render: (_: unknown, r: ScreenStock) => (
        <Space size={4}>
          <span>{r.name}</span>
          <Typography.Text type="secondary" copyable={{ text: r.code }} style={{ fontSize: 12 }}>{r.code}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '信号日', dataIndex: 'signal_date', width: 92,
      render: (v: string | undefined) => v ?? '—',
    },
    { title: '收盘价', dataIndex: 'price', width: 80, render: (v: number) => v?.toFixed(2) },
    {
      title: '涨跌幅', dataIndex: 'pct', width: 86,
      render: (v: number) => (
        <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{v >= 0 ? '+' : ''}{v?.toFixed(2)}%</span>
      ),
      sorter: (a: ScreenStock, b: ScreenStock) => a.pct - b.pct,
    },
    ...(snapshotCols ? [
      {
        title: '量比', dataIndex: 'volume_ratio', width: 70,
        render: (v: number | null) => (v != null ? v.toFixed(2) : '—'),
        sorter: (a: ScreenStock, b: ScreenStock) => (a.volume_ratio ?? 0) - (b.volume_ratio ?? 0),
      },
      {
        title: '换手率', dataIndex: 'turnover', width: 78,
        render: (v: number | null) => (v != null ? `${v.toFixed(2)}%` : '—'),
      },
    ] : []),
    {
      title: '成交额', width: 88,
      render: (_: unknown, r: ScreenStock) =>
        r.amount != null && r.amount > 0 ? `${(r.amount / 1e8).toFixed(2)}亿` : '—',
      sorter: (a: ScreenStock, b: ScreenStock) => (a.amount ?? 0) - (b.amount ?? 0),
    },
    {
      title: isFormula ? '强度分' : '综合得分', dataIndex: 'score', width: 96,
      defaultSortOrder: 'descend' as const,
      sorter: (a: ScreenStock, b: ScreenStock) => a.score - b.score,
      render: (v: number) => (
        <Tag color={v >= 80 ? 'red' : v >= 60 ? 'orange' : 'default'} style={{ fontSize: 13, fontWeight: 600 }}>{v}</Tag>
      ),
    },
    {
      title: '操作', width: 100,
      render: (_: unknown, r: ScreenStock) => (
        <Button type="link" size="small"
          onClick={() => onGoPredict({ code: r.code, name: r.name })}>
          去预测 →
        </Button>
      ),
    },
  ]

  const normalParams = activeStrategy?.params.filter(p =>
    !isWeightParam(p.key) && (!comboMode || COMMON_KEYS.includes(p.key))) ?? []
  const weightParams = activeStrategy && !comboMode
    ? activeStrategy.params.filter(p => isWeightParam(p.key))
    : []

  const sync = dataStatus?.sync
  const syncPct = sync && sync.total > 0 ? Math.round(sync.done / sync.total * 100) : 0

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={8} xl={7}>
        <Card title="① 选择选股方法" size="small"
          extra={
            <Space size={6}>
              <Tooltip title="组合模式：选多个公式策略，用交集/并集组合选股，还可设置排除策略">
                <span style={{ fontSize: 12 }}>组合</span>
              </Tooltip>
              <Switch size="small" checked={comboMode}
                onChange={v => {
                  setComboMode(v)
                  setResult(null)
                  setViewingRun(null)
                  if (!v) setExcludeIds([])
                }} />
              <Button size="small" icon={<HistoryOutlined />} onClick={openHistory}>历史</Button>
            </Space>
          }>
          {comboMode ? (
            <>
              <Select mode="multiple" value={selectedIds}
                onChange={ids => { setSelectedIds(ids); setExcludeIds(es => es.filter(e => !ids.includes(e))) }}
                showSearch optionFilterProp="label" style={{ width: '100%' }}
                maxTagCount={4} placeholder={`从 ${strategies.filter(s => s.kind === 'formula').length} 个公式策略中多选…`}
                options={comboSelectOptions.map(g => ({ ...g, title: g.key }))} />
              <Space wrap style={{ marginTop: 10 }} align="center">
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>组合方式</Typography.Text>
                <Segmented size="small" value={combine}
                  onChange={v => setCombine(v as 'or' | 'and')}
                  options={[
                    { value: 'or', label: '并集·任一命中' },
                    { value: 'and', label: '交集·全部命中' },
                  ]} />
              </Space>
              <div style={{ marginTop: 8 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  排除策略（命中的股票从结果剔除，可选）
                </Typography.Text>
                <Select mode="multiple" allowClear value={excludeIds} onChange={setExcludeIds}
                  showSearch optionFilterProp="label" style={{ width: '100%' }}
                  maxTagCount={3} placeholder="不排除"
                  options={excludeOptions} />
              </div>
              {combine === 'and' && selectedIds.length < 2 && (
                <Alert style={{ marginTop: 8 }} type="warning" showIcon
                  message="交集（全部命中）至少需要选择 2 个策略" />
              )}
              {selectedIds.length >= 2 && (
                <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: '8px 0 0' }}>
                  已选 {selectedIds.length} 个策略，将在一次扫描中同时评估全部公式（耗时与单策略相当）
                </Typography.Paragraph>
              )}
            </>
          ) : (
            <Select value={strategyId || undefined} onChange={switchStrategy}
              showSearch optionFilterProp="label" style={{ width: '100%' }}
              placeholder={`共 ${strategies.length} 个策略，可搜索…`}
              options={groupedOptions.map(g => ({ ...g, title: g.key }))} />
          )}
          {!comboMode && strategy && (
            <div style={{ marginTop: 10 }}>
              <Space wrap size={4} style={{ marginBottom: 4 }}>
                <Tag color="geekblue">{strategy.category || '实时快照'}</Tag>
                <Tag>{strategy.source}</Tag>
              </Space>
              <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 4 }}>
                {strategy.description}
              </Typography.Paragraph>
              {isFormula && strategy.formula && (
                <Collapse ghost size="small" style={{ margin: '0 -14px' }}
                  items={[{
                    key: 'f', label: <span style={{ fontSize: 12 }}>查看公式（通达信语法）</span>,
                    children: (
                      <pre style={{ fontSize: 11, lineHeight: 1.6, whiteSpace: 'pre-wrap',
                        background: '#f6f8fa', padding: 8, borderRadius: 6 }}>
                        {strategy.formula.replace(/;\s*/g, ';\n')}
                      </pre>
                    ),
                  }]} />
              )}
            </div>
          )}
        </Card>

        {(comboMode ? comboStrategy : strategy) && (
          <Card title={comboMode ? '② 组合公共参数' : '② 策略参数'} size="small" style={{ marginTop: 16 }}
            extra={<Button size="small"
              onClick={() => activeStrategy && setParams(defaultParams(activeStrategy))}>恢复默认</Button>}>
            <Row gutter={8}>
              {normalParams.map(p => (
                <Col span={p.type === 'bool' ? 24 : 12} key={p.key}>{renderParam(p.key)}</Col>
              ))}
            </Row>
            {weightParams.length > 0 && (
              <Collapse ghost size="small" style={{ margin: '4px -14px 0' }}
                items={[{
                  key: 'w', label: <span style={{ fontSize: 12 }}>因子权重（高级）</span>,
                  children: (
                    <Row gutter={8}>
                      {weightParams.map(p => <Col span={12} key={p.key}>{renderParam(p.key)}</Col>)}
                    </Row>
                  ),
                }]} />
            )}
          </Card>
        )}

        <Button type="primary" size="large" block icon={<RocketOutlined />} loading={running}
          onClick={doRun} style={{ marginTop: 16 }}>
          {running ? `选股中… 已用时 ${elapsed} 秒` : '③ 开始选股'}
        </Button>
        {running && (
          <Alert style={{ marginTop: 8 }} type="info" showIcon
            message={comboMode
              ? `本地扫描并同时评估 ${selectedIds.length} 个公式 + 排除集，约 1~2 分钟`
              : isFormula
                ? '本地历史数据全市场公式扫描，约 10~60 秒'
                : '全市场快照 + 逐只计算指标，首次约需 10~60 秒'} />
        )}
      </Col>

      <Col xs={24} lg={16} xl={17}>
        {(isFormula || comboMode) && (
          <Card size="small" style={{ marginBottom: 16 }}
            title={<Space><DatabaseOutlined /><span>历史数据仓库（通达信式：先下载数据，本地选股）</span></Space>}>
            <Space wrap size={16}>
              <span>
                已入库 <Typography.Text strong>{dataStatus?.synced_stocks ?? '—'}</Typography.Text> 只
                {dataStatus?.total_stocks ? ` / 全市场约 ${dataStatus.total_stocks}` : ''}
              </span>
              <span>数据截至 <Typography.Text strong>{dataStatus?.data_as_of ?? '—'}</Typography.Text></span>
              <span>{((dataStatus?.kline_rows ?? 0) / 1e4).toFixed(0)} 万行K线</span>
              <Select value={syncYears} onChange={setSyncYears} size="small" style={{ width: 90 }}
                options={[1, 2, 3, 5].map(y => ({ value: y, label: `${y} 年` }))} />
              <Button size="small" icon={<CloudDownloadOutlined />} loading={syncRunning}
                onClick={() => startSync('update')}>增量更新</Button>
              <Button size="small" icon={<CloudDownloadOutlined />} disabled={syncRunning}
                onClick={() => startSync('full')}>全量重下</Button>
            </Space>
            {syncRunning && (
              <div style={{ marginTop: 8 }}>
                <Progress percent={syncPct} size="small" status="active" />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {sync?.phase}：{sync?.done}/{sync?.total}（成功 {sync?.ok} 失败 {sync?.failed}）
                  ，首次全量约需 20~40 分钟，可后台等待
                </Typography.Text>
              </div>
            )}
            {!syncRunning && dataStatus && dataStatus.synced_stocks > 0 && dataStatus.fresh_stocks < dataStatus.synced_stocks * 0.9 && (
              <Alert style={{ marginTop: 8 }} type="warning" showIcon
                message="部分股票数据已过期（超过 5 个交易日未更新），建议先「增量更新」再选股" />
            )}
            {dataStatus?.synced_stocks === 0 && (
              <Alert style={{ marginTop: 8 }} type="warning" showIcon
                message="本地还没有历史数据，请先点击「增量更新」（或全量重下）下载全市场日K，之后选股完全走本地数据，速度极快" />
            )}
          </Card>
        )}

        <Card size="small" title={
          <Space wrap>
            <span>选股结果{viewingRun ? `（历史记录 #${viewingRun}）` : ''}</span>
            {result && <>
              <Tag>{result.strategy_name}</Tag>
              <Tag color="blue">入选 {result.result_count} / 扫描 {result.total_screened}</Tag>
              {isFormula || comboMode
                ? <Tag>数据截至 {result.snapshot_time?.slice(0, 10)}</Tag>
                : <Tag>快照时间 {result.snapshot_time?.replace('T', ' ').slice(0, 19)}</Tag>}
              <Tag>耗时 {(result.elapsed_ms / 1000).toFixed(1)}s</Tag>
            </>}
          </Space>
        } extra={
          <Space>
            <Button size="small" icon={<DownloadOutlined />} disabled={!result?.results.length} onClick={exportCsv}>
              导出 CSV
            </Button>
            <Button size="small" icon={<ReloadOutlined />} onClick={doRun} disabled={running}>刷新</Button>
          </Space>
        }>
          {result?.disclaimer && (
            <Alert style={{ marginBottom: 8 }} type="warning" showIcon message={result.disclaimer} />
          )}
          {result && result.result_count === 0 && (
            <Empty description={
              comboMode
                ? '组合条件太严没有命中。可尝试：改用并集、放宽「信号有效期」、减少交集策略数或去掉排除策略'
                : isFormula
                  ? '最近 N 个交易日内没有股票触发该信号。可尝试：加大「信号有效期」、放宽板块/成交额过滤，或换个策略'
                  : '没有符合条件的股票。可尝试：关闭「前日涨停」硬条件、放宽涨幅区间或加大取数范围'
            } style={{ padding: 40 }} />
          )}
          <Table rowKey="code" size="small" dataSource={result?.results ?? []}
            loading={running} pagination={{ pageSize: 20, showSizeChanger: false }}
            columns={columns}
            expandable={{
              rowExpandable: (r: ScreenStock) => (r.factors?.length > 0 || !!r.detail),
              expandedRowRender: (r: ScreenStock) => (
                <Space size={4} wrap style={{ padding: '4px 0' }}>
                  {r.factors.map(f => (
                    <Tooltip key={f.id} title={f.detail}>
                      <Tag color={f.hit === null ? 'default' : f.hit ? 'green' : 'red'}
                        style={{ fontSize: 12 }}>
                        {f.hit === null ? '—' : f.hit ? '✓' : '✗'} {f.name} {f.score}/{f.max}
                      </Tag>
                    </Tooltip>
                  ))}
                  {r.detail && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>{r.detail}</Typography.Text>
                  )}
                </Space>
              ),
            }} />
          {!result && !running && (
            <Empty description="选择方法与参数后点击「开始选股」" style={{ padding: 60 }} />
          )}
        </Card>
      </Col>

      <Drawer title="选股历史" width={560} open={historyOpen} onClose={() => setHistoryOpen(false)}>
        <Table rowKey="id" size="small" dataSource={runs}
          pagination={{ pageSize: 15, showSizeChanger: false }}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 50 },
            { title: '方法', dataIndex: 'strategy_name', width: 150 },
            {
              title: '时间', dataIndex: 'created_at', width: 150,
              render: (t: string) => t?.replace('T', ' ').slice(0, 19),
            },
            { title: '入选', dataIndex: 'result_count', width: 60 },
            {
              title: '操作', width: 110,
              render: (_: unknown, r: ScreenRunMeta) => (
                <Space size={0}>
                  <Button type="link" size="small" onClick={() => viewRun(r.id)}>查看</Button>
                  <Popconfirm title="删除该记录？" onConfirm={() => deleteRun(r.id)}>
                    <Button type="link" size="small" danger>删除</Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]} />
      </Drawer>
    </Row>
  )
}

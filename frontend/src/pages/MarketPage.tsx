import {
  AutoComplete, Button, Card, Col, Drawer, Empty, Input, Popconfirm, Row,
  Segmented, Select, Space, Spin, Tag, Typography, message,
} from 'antd'
import {
  DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, StarOutlined,
} from '@ant-design/icons'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts'
import {
  api, type IndexQuote, type Intraday, type KlineFull, type Spot,
  type WatchGroup, type WatchItem,
} from '../api'

const pctColor = (v: number | null | undefined) =>
  v == null ? undefined : v >= 0 ? '#cf1322' : '#3f8600'
const pctText = (v: number | null | undefined) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`

type Period = 'intraday' | 'daily' | 'weekly' | 'monthly'
type SubIndicator = 'macd' | 'kdj' | 'rsi' | 'boll' | 'vol'

const UP = '#cf1322'
const DOWN = '#3f8600'

/** 主图+副图 ECharts：分时/蜡烛+MA；副图 MACD/KDJ/RSI/VOL（BOLL 画主图） */
function PriceChart(props: {
  period: Period
  intraday: Intraday | null
  kline: KlineFull | null
  sub: SubIndicator
  loading: boolean
}) {
  const { period, intraday, kline, sub, loading } = props
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    chartRef.current = echarts.init(ref.current)
    const onResize = () => chartRef.current?.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (loading) { chart.showLoading(); return }
    chart.hideLoading()

    const legends: string[] = []
    const grids = [
      { left: 64, right: 64, top: 28, height: '54%' },
      { left: 64, right: 64, top: '68%', height: '16%' },
      { left: 64, right: 64, top: '88%', height: '9%' },
    ]
    const series: echarts.SeriesOption[] = []
    let xTimes: string[] = []

    if (period === 'intraday') {
      if (!intraday) { chart.clear(); return }
      xTimes = intraday.times
      series.push(
        {
          name: '价格', type: 'line', data: intraday.prices, showSymbol: false,
          lineStyle: { width: 1.4, color: '#1f3b8f' },
          areaStyle: { opacity: 0.08, color: '#1f3b8f' },
          markLine: intraday.prev_close ? {
            symbol: 'none', silent: true,
            label: { formatter: () => intraday.prev_close.toFixed(2), position: 'insideEndTop', fontSize: 10 },
            lineStyle: { type: 'dashed', color: '#999' },
            data: [{ yAxis: intraday.prev_close }],
          } : undefined,
        },
        {
          name: '均价', type: 'line', data: intraday.avgs, showSymbol: false,
          lineStyle: { width: 1.2, color: '#e8751a' },
        },
        {
          name: '分钟量', type: 'bar',
          data: intraday.volumes.map((v, i) => ({
            value: v,
            itemStyle: { color: (intraday.prices[i] ?? 0) >= (intraday.prices[i - 1] ?? intraday.prev_close) ? UP : DOWN },
          })),
        },
      )
      legends.push('价格', '均价', '分钟量')
    } else if (!kline || kline.dates.length === 0) {
      chart.clear()
      return
    } else {
      xTimes = kline.dates
      const candles = kline.close.map((c, i) => [kline.open[i], c, kline.low[i], kline.high[i]])
      const barColors = kline.close.map((c, i) =>
        ((c ?? 0) >= (kline.open[i] ?? 0) ? UP : DOWN))
      series.push(
        {
          name: 'K线', type: 'candlestick', data: candles,
          itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
        },
        line('MA5', kline.ma5, '#e8b004'), line('MA10', kline.ma10, '#1f77b4'),
        line('MA20', kline.ma20, '#c44ecc'), line('MA60', kline.ma60, '#7f7f7f'),
      )
      legends.push('MA5', 'MA10', 'MA20', 'MA60')

      if (sub === 'boll') {
        series.push(
          line('BOLL中', kline.boll_mid, '#e8b004', 0),
          line('BOLL上', kline.boll_up, '#999999', 0),
          line('BOLL下', kline.boll_low, '#999999', 0),
        )
        legends.push('BOLL中', 'BOLL上', 'BOLL下')
        series.push(volBars(barColors, 0))
        legends.push('成交量')
      } else if (sub === 'vol') {
        series.push(volBars(barColors, 0))
        legends.push('成交量')
      } else if (sub === 'macd') {
        series.push(
          line('DIF', kline.dif, '#e8b004', 0), line('DEA', kline.dea, '#1f77b4', 0),
          {
            name: 'MACD', type: 'bar', data: kline.macd,
            itemStyle: { color: (p: { data?: unknown }) => (Number(p.data) >= 0 ? UP : DOWN) },
          },
        )
        legends.push('DIF', 'DEA', 'MACD')
      } else if (sub === 'kdj') {
        series.push(
          line('K', kline.kdj_k, '#e8b004', 0), line('D', kline.kdj_d, '#1f77b4', 0),
          line('J', kline.kdj_j, '#c44ecc', 0),
        )
        legends.push('K', 'D', 'J')
      } else if (sub === 'rsi') {
        series.push({
          name: 'RSI6', type: 'line', data: kline.rsi6, showSymbol: false,
          lineStyle: { width: 1.2, color: '#c44ecc' },
          markLine: {
            symbol: 'none', silent: true, label: { formatter: '{b}' },
            lineStyle: { type: 'dashed', color: '#bbb' },
            data: [{ yAxis: 80 }, { yAxis: 20 }],
          },
        })
        legends.push('RSI6')
      }
    }

    chart.setOption({
      animation: false,
      legend: { data: legends, top: 2, type: 'scroll', textStyle: { fontSize: 11 } },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: grids,
      xAxis: [
        { type: 'category', data: xTimes, boundaryGap: period !== 'intraday', gridIndex: 0, axisLabel: { show: false } },
        { type: 'category', data: xTimes, boundaryGap: period !== 'intraday', gridIndex: 1, axisLabel: { show: false } },
        { type: 'category', data: xTimes, boundaryGap: period !== 'intraday', gridIndex: 2 },
      ],
      yAxis: [
        { type: 'value', scale: true, gridIndex: 0 },
        { type: 'value', gridIndex: 1, scale: period !== 'intraday' },
        { type: 'value', gridIndex: 2, axisLabel: { show: false }, splitLine: { show: false } },
      ],
      dataZoom: period === 'intraday' ? [
        { type: 'inside', xAxisIndex: [0, 1, 2], start: 30, end: 100 },
      ] : [
        { type: 'inside', xAxisIndex: [0, 1, 2], start: 55, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1, 2], start: 55, end: 100, height: 22, bottom: 0 },
      ],
      series,
    }, { notMerge: true })

    function line(name: string, data: (number | null)[], color: string, _gridIdx = 0): echarts.SeriesOption {
      legends.push(name)
      return {
        name, type: 'line', data, showSymbol: false, lineStyle: { width: 1, color },
      }
    }
    function volBars(colors: string[], _gridIdx = 0): echarts.SeriesOption {
      return {
        name: '成交量', type: 'bar',
        data: (kline?.volume ?? []).map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
      }
    }
  }, [period, intraday, kline, sub, loading])

  return <div ref={ref} style={{ width: '100%', height: 540 }} />
}

/** 行情中心：自选分组 + 指数条 + 分时/K线（副图指标切换） */
export default function MarketPage({ onGoPredict }: { onGoPredict: (s: { code: string; name: string }) => void }) {
  const [groups, setGroups] = useState<WatchGroup[]>([])
  const [indexes, setIndexes] = useState<IndexQuote[]>([])
  const [activeGroupId, setActiveGroupId] = useState<number | null>(null)
  const [selected, setSelected] = useState<WatchItem | null>(null)
  const [spot, setSpot] = useState<Record<string, Spot>>({})
  const [period, setPeriod] = useState<Period>('intraday')
  const [sub, setSub] = useState<SubIndicator>('macd')
  const [intraday, setIntraday] = useState<Intraday | null>(null)
  const [kline, setKline] = useState<KlineFull | null>(null)
  const [chartLoading, setChartLoading] = useState(false)
  const [manageOpen, setManageOpen] = useState(false)
  const [searchVal, setSearchVal] = useState('')
  const [searchOpts, setSearchOpts] = useState<{ value: string; label: string; code: string; name: string }[]>([])
  const [newGroupName, setNewGroupName] = useState('')

  const loadGroups = useCallback(async () => {
    try {
      const d = await api.watchGroups()
      setGroups(d.groups)
      setIndexes(d.indexes)
      setActiveGroupId(gid =>
        gid && d.groups.some(g => g.id === gid) ? gid : d.groups[0]?.id ?? null)
      setSelected(sel => {
        const all = d.groups.flatMap(g => g.items)
        if (sel) return all.find(it => it.id === sel.id) ?? all[0] ?? null
        return all[0] ?? null
      })
    } catch (e) { message.error((e as Error).message) }
  }, [])

  useEffect(() => { loadGroups() }, [loadGroups])

  const activeGroup = useMemo(
    () => groups.find(g => g.id === activeGroupId) ?? null,
    [groups, activeGroupId])
  const listCodes = useMemo(() => (activeGroup?.items ?? []).map(i => i.code), [activeGroup])

  const pollSpot = useCallback(() => {
    const codes = [...new Set([...listCodes, ...indexes.map(i => i.code)])]
    if (!codes.length) return
    api.quotesSpot(codes).then(d => setSpot(d.quotes)).catch(() => { })
  }, [listCodes, indexes])

  useEffect(() => {
    pollSpot()
    const t = setInterval(pollSpot, 10000)
    return () => clearInterval(t)
  }, [pollSpot])

  const refreshChart = useCallback(() => {
    if (!selected) return
    let cancel = false
    setChartLoading(true)
    const load = period === 'intraday'
      ? api.quotesIntraday(selected.code).then(d => { if (!cancel) setIntraday(d) })
      : api.quotesKline(selected.code, period, 260).then(d => { if (!cancel) setKline(d) })
    load.catch((e: Error) => message.error(e.message)).finally(() => { if (!cancel) setChartLoading(false) })
    return () => { cancel = true }
  }, [selected, period])

  useEffect(() => refreshChart(), [refreshChart])

  const searchStock = useCallback((kw: string) => {
    setSearchVal(kw)
    if (!kw.trim()) { setSearchOpts([]); return }
    api.searchStocks(kw.trim()).then(rs =>
      setSearchOpts(rs.results.map(r => ({
        value: r.code, label: `${r.name} ${r.code}`, code: r.code, name: r.name ?? r.code,
      })))).catch(() => { })
  }, [])

  const addItem = async (groupId: number, code: string, name: string) => {
    try {
      await api.addWatchItem(groupId, code, name)
      message.success(`已添加 ${name || code}`)
      setSearchVal(''); setSearchOpts([])
      loadGroups()
    } catch (e) { message.error((e as Error).message) }
  }

  const createGroup = () => {
    if (!newGroupName.trim()) return
    api.addWatchGroup(newGroupName.trim())
      .then(() => { setNewGroupName(''); loadGroups() })
      .catch(e => message.error((e as Error).message))
  }

  const detailSpot = selected ? spot[selected.code] : null

  return (
    <Row gutter={[16, 16]}>
      <Col span={24}>
        <Card size="small" styles={{ body: { padding: '8px 16px' } }}>
          <Space size={32} wrap>
            {indexes.map(ix => (
              <Space key={ix.code} size={8}>
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>{ix.name}</Typography.Text>
                <span style={{ fontSize: 17, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: pctColor(ix.pct) }}>
                  {ix.price?.toFixed(2)}
                </span>
                <span style={{ fontSize: 12, color: pctColor(ix.pct) }}>{pctText(ix.pct)}</span>
              </Space>
            ))}
            {indexes.length === 0 && <Spin size="small" />}
          </Space>
        </Card>
      </Col>

      <Col xs={24} md={8} xl={6}>
        <Card size="small" title={<Space><StarOutlined /><span>自选分组</span></Space>}
          extra={<Button size="small" icon={<PlusOutlined />} onClick={() => setManageOpen(true)}>管理</Button>}>
          <Select value={activeGroupId ?? undefined} style={{ width: '100%', marginBottom: 8 }}
            onChange={setActiveGroupId}
            options={groups.map(g => ({ value: g.id, label: `${g.name}（${g.items.length}）` }))}
            placeholder="选择分组" />
          <Space.Compact style={{ width: '100%', marginBottom: 8 }}>
            <AutoComplete value={searchVal} onChange={searchStock} options={searchOpts}
              style={{ width: '100%' }} placeholder="输入代码/名称添加到当前分组"
              onSelect={(_, opt) => {
                if (activeGroupId) addItem(activeGroupId, opt.code, opt.name)
              }} />
          </Space.Compact>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {(activeGroup?.items ?? []).map(it => {
              const s = spot[it.code]
              const pct = s?.pct ?? it.pct ?? null
              return (
                <div key={it.id}
                  onClick={() => setSelected(it)}
                  style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '7px 10px', borderRadius: 6, cursor: 'pointer',
                    background: selected?.id === it.id ? '#e6f0ff' : undefined,
                  }}>
                  <Space size={6}>
                    <span style={{ fontWeight: 600 }}>{it.name || it.code}</span>
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>{it.code}</Typography.Text>
                  </Space>
                  <Space size={10}>
                    <span style={{ fontVariantNumeric: 'tabular-nums' }}>{s?.price?.toFixed(2) ?? '—'}</span>
                    <Tag color={pct != null && pct >= 0 ? 'red' : 'green'}
                      style={{ marginRight: 0, minWidth: 64, textAlign: 'center' }}>
                      {pctText(pct)}
                    </Tag>
                    <Popconfirm title="从分组移除？" onConfirm={() =>
                      api.removeWatchItem(it.id).then(() => loadGroups())
                        .catch(e => message.error((e as Error).message))}>
                      <Button type="text" size="small" icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Space>
                </div>
              )
            })}
            {activeGroup && activeGroup.items.length === 0 && (
              <Empty description="分组为空，上方搜索添加" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 24 }} />
            )}
            {!activeGroup && <Empty description="先创建分组" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 24 }} />}
          </div>
        </Card>
      </Col>

      <Col xs={24} md={16} xl={18}>
        <Card size="small" title={
          selected ? (
            <Space size={16} wrap>
              <span style={{ fontSize: 17, fontWeight: 700 }}>{selected.name || detailSpot?.name}</span>
              <Typography.Text type="secondary">{selected.code}</Typography.Text>
              <span style={{ fontSize: 20, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: pctColor(detailSpot?.pct) }}>
                {detailSpot?.price?.toFixed(2) ?? '—'}
              </span>
              <span style={{ color: pctColor(detailSpot?.pct) }}>{pctText(detailSpot?.pct)}</span>
              <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                今开 {detailSpot?.open?.toFixed(2) ?? '—'} · 最高 {detailSpot?.high?.toFixed(2) ?? '—'} ·
                最低 {detailSpot?.low?.toFixed(2) ?? '—'} · 昨收 {detailSpot?.prev_close?.toFixed(2) ?? '—'} ·
                成交额 {detailSpot ? (detailSpot.amount / 1e8).toFixed(2) + '亿' : '—'}
              </Typography.Text>
            </Space>
          ) : '个股行情'
        } extra={
          selected && (
            <Space>
              <Button size="small" onClick={() => onGoPredict({ code: selected.code, name: selected.name })}>
                去预测
              </Button>
              <Button size="small" icon={<ReloadOutlined />} onClick={refreshChart} />
            </Space>
          )
        }>
          {!selected && <Empty description="从左侧自选列表选择股票" style={{ padding: 80 }} />}
          {selected && (
            <>
              <Space style={{ marginBottom: 8 }} wrap>
                <Segmented value={period}
                  onChange={v => setPeriod(v as Period)}
                  options={[
                    { value: 'intraday', label: '分时' },
                    { value: 'daily', label: '日K' },
                    { value: 'weekly', label: '周K' },
                    { value: 'monthly', label: '月K' },
                  ]} />
                {period !== 'intraday' && (
                  <Segmented size="small" value={sub}
                    onChange={v => setSub(v as SubIndicator)}
                    options={[
                      { value: 'macd', label: 'MACD' },
                      { value: 'kdj', label: 'KDJ' },
                      { value: 'rsi', label: 'RSI' },
                      { value: 'boll', label: 'BOLL' },
                      { value: 'vol', label: 'VOL' },
                    ]} />
                )}
              </Space>
              <PriceChart period={period} intraday={intraday} kline={kline}
                sub={sub} loading={chartLoading} />
            </>
          )}
        </Card>
      </Col>

      <Drawer title="自选分组管理" width={420} open={manageOpen} onClose={() => setManageOpen(false)}>
        <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
          <Input value={newGroupName} onChange={e => setNewGroupName(e.target.value)}
            placeholder="新分组名称" onPressEnter={createGroup} />
          <Button type="primary" icon={<PlusOutlined />} onClick={createGroup}>新建</Button>
        </Space.Compact>
        {groups.map(g => (
          <div key={g.id} style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '8px 4px', borderBottom: '1px solid #f0f0f0',
          }}>
            <span>{g.name} <Typography.Text type="secondary">（{g.items.length}）</Typography.Text></span>
            <Space size={0}>
              <Button type="text" size="small" icon={<EditOutlined />} onClick={() => {
                const name = window.prompt('新名称', g.name)
                if (name && name.trim())
                  api.renameWatchGroup(g.id, name.trim()).then(() => loadGroups())
                    .catch(e => message.error((e as Error).message))
              }} />
              <Popconfirm title="删除该分组及其全部自选？" onConfirm={() =>
                api.deleteWatchGroup(g.id).then(() => loadGroups())
                  .catch(e => message.error((e as Error).message))}>
                <Button type="text" size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            </Space>
          </div>
        ))}
      </Drawer>
    </Row>
  )
}

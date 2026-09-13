import { Button, Card, Col, Popconfirm, Row, Space, Statistic, Table, Tag, Typography, message } from 'antd'
import { DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { useCallback, useEffect, useState } from 'react'
import { api, type ForecastRecord } from '../api'
import ForecastChart from '../components/ForecastChart'

const MODE_COLOR: Record<string, string> = { remote: 'green', local: 'blue', mock: 'orange' }
const PERIOD_LABEL: Record<string, string> = { daily: '日线', weekly: '周线', monthly: '月线' }

export default function HistoryPage() {
  const [records, setRecords] = useState<ForecastRecord[]>([])
  const [stats, setStats] = useState({ total_forecasts: 0, unique_stocks: 0 })
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(() => {
    setLoading(true)
    api.history(100)
      .then(d => { setRecords(d.records); setStats(d.stats) })
      .catch(e => message.error((e as Error).message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(refresh, [refresh])

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title="累计预测" value={stats.total_forecasts} suffix="次" /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="覆盖标的" value={stats.unique_stocks} suffix="只" /></Card></Col>
      </Row>
      <Card size="small" title="预测历史" extra={
        <Typography.Link onClick={refresh}><Space><ReloadOutlined />刷新</Space></Typography.Link>
      }>
        <Table
          rowKey="id" loading={loading} size="small"
          dataSource={records}
          pagination={{ pageSize: 10 }}
          expandable={{
            expandedRowRender: rec => (
              <ForecastChart
                history={rec.historical}
                forecast={rec.forecast}
                band={rec.quantiles}
                height={320}
              />
            ),
          }}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 60 },
            { title: '股票', render: (_: unknown, r: ForecastRecord) => `${r.stock_name} (${r.stock_code})` },
            { title: '周期', dataIndex: 'period', width: 70, render: (p: string) => PERIOD_LABEL[p] ?? p },
            { title: '步长', dataIndex: 'horizon', width: 60, render: (v: number) => `${v}步` },
            { title: '因子数', width: 70, render: (_: unknown, r: ForecastRecord) => r.factor_names?.length ?? 0 },
            {
              title: '推理模式', dataIndex: 'inference_mode', width: 110,
              render: (m: string) => <Tag color={MODE_COLOR[m]}>{m}</Tag>,
            },
            {
              title: '预测涨跌', dataIndex: 'metrics', width: 90,
              render: (m: ForecastRecord['metrics']) => (
                <span style={{ color: m.predicted_change_pct >= 0 ? '#cf1322' : '#3f8600' }}>
                  {m.predicted_change_pct >= 0 ? '+' : ''}{m.predicted_change_pct}%
                </span>
              ),
            },
            { title: '时间', dataIndex: 'created_at', width: 170,
              render: (t: string) => t?.replace('T', ' ').slice(0, 19) },
            {
              title: '操作', width: 70,
              render: (_: unknown, r: ForecastRecord) => (
                <Popconfirm title="删除该记录？" onConfirm={async () => {
                  await api.deleteHistory(r.id!)
                  message.success('已删除')
                  refresh()
                }}>
                  <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}

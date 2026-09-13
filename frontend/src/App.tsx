import { ConfigProvider, Layout, Tag, Typography, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useEffect, useState } from 'react'
import { api, type Health, type StockRef } from './api'
import AboutPage from './pages/AboutPage'
import BacktestPage from './pages/BacktestPage'
import HistoryPage from './pages/HistoryPage'
import MarketPage from './pages/MarketPage'
import PredictPage from './pages/PredictPage'
import ScreenerPage from './pages/ScreenerPage'
import Tabs from 'antd/es/tabs'

const { Header, Content, Footer } = Layout

function useHealth() {
  const [health, setHealth] = useState<Health | null>(null)
  useEffect(() => {
    const load = () => api.health().then(setHealth).catch(() => setHealth(null))
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])
  return health
}

function InferenceBadge({ health }: { health: Health | null }) {
  if (!health) return <Tag color="default">推理状态未知</Tag>
  const { configured_mode, engines } = health.inference
  const remote = engines.remote
  const local = engines.local
  const mock = engines.mock
  if (configured_mode === 'remote')
    return remote?.available
      ? <Tag color="green">远程GPU推理{remote.host ? ` · ${remote.host}` : ''}</Tag>
      : <Tag color="red">远程推理服务不可达</Tag>
  if (configured_mode === 'local')
    return local?.available
      ? <Tag color="blue">本地推理</Tag>
      : <Tag color="red">本地推理未安装</Tag>
  if (configured_mode === 'mock') return <Tag color="orange">模拟模式（非真实推理）</Tag>
  // auto
  if (remote?.worker_ready || remote?.available)
    return <Tag color="green">远程GPU推理{remote.host ? ` · ${remote.host}` : ''}</Tag>
  if (local?.available) return <Tag color="blue">本地推理（远程GPU不可达）</Tag>
  if (mock?.available) return <Tag color="orange">模拟模式（推理服务不可达）</Tag>
  return <Tag color="red">推理引擎均不可用</Tag>
}

export default function App() {
  const health = useHealth()
  const [activeTab, setActiveTab] = useState('predict')
  // 选股 → 预测联动：选股页点"去预测"时记录目标，预测页自动带入
  const [presetStock, setPresetStock] = useState<StockRef | null>(null)

  const goPredict = (s: StockRef) => {
    setPresetStock(s)
    setActiveTab('predict')
  }

  return (
    <ConfigProvider locale={zhCN} theme={{ algorithm: theme.defaultAlgorithm }}>
      <Layout style={{ minHeight: '100vh' }}>
        <Header style={{
          background: 'linear-gradient(90deg,#1f3b8f 0%,#274690 60%,#3b5ba9 100%)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          paddingInline: 24, position: 'sticky', top: 0, zIndex: 100,
        }}>
          <Typography.Title level={4} style={{ color: '#fff', margin: 0 }}>
            📈 A股多因子智能预测
          </Typography.Title>
          <InferenceBadge health={health} />
        </Header>
        <Content style={{ padding: '16px 24px', maxWidth: 1440, margin: '0 auto', width: '100%' }}>
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={[
              { key: 'market', label: '行情', children: <MarketPage onGoPredict={goPredict} /> },
              { key: 'predict', label: '预测', children: <PredictPage presetStock={presetStock} /> },
              { key: 'screener', label: '智能选股', children: <ScreenerPage onGoPredict={goPredict} /> },
              { key: 'backtest', label: '策略组回测', children: <BacktestPage /> },
              { key: 'history', label: '历史记录', children: <HistoryPage /> },
              { key: 'about', label: '关于', children: <AboutPage /> },
            ]}
          />
        </Content>
        <Footer style={{ textAlign: 'center', fontSize: 12 }}>
          仅供学习研究，不构成投资建议
        </Footer>
      </Layout>
    </ConfigProvider>
  )
}

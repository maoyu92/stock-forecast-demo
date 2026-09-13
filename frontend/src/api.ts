// 与后端 API 对齐的类型定义

export interface StockRef { code: string; name?: string | null }

export interface Preset {
  name: string
  target: StockRef
  factors: StockRef[]
  note?: string
}

export interface FactorGroup {
  id: number
  name: string
  target_code: string
  target_name: string
  factors: StockRef[]
  created_at: string
}

export interface Kline {
  code: string
  period: string
  dates: string[]
  open: (number | null)[]
  high: (number | null)[]
  low: (number | null)[]
  close: (number | null)[]
  volume: (number | null)[]
}

export interface PredictRequest {
  code: string
  name?: string | null
  period: string
  horizon: number
  context_len: number
  factors: StockRef[]
  save?: boolean
}

export interface ForecastRecord {
  id?: number
  stock_code: string
  stock_name: string
  period: string
  horizon: number
  context_len: number
  factor_codes?: string[]
  factor_names?: string[]
  inference_mode: 'remote' | 'local' | 'mock'
  model_version?: string
  historical: { dates: string[]; values: number[] }
  forecast: { dates: string[]; values: number[] }
  quantiles: { lower: number[] | null; upper: number[] | null }
  metrics: {
    last_value: number
    forecast_mean: number
    forecast_min: number
    forecast_max: number
    predicted_change_pct: number
  }
  dropped_factors?: { code: string; name?: string; reason: string }[]
  inference_detail?: string
  engine_errors?: string[]
  created_at?: string
}

export interface EngineInfo {
  name: string
  available?: boolean
  detail?: string
  host?: string
  tcp_reachable?: boolean
  worker_ready?: boolean
}

export interface Health {
  status: string
  inference: {
    configured_mode: string
    engines: Record<string, EngineInfo>
  }
}

// ---------- 智能选股 ----------

export interface ScreenParamDef {
  key: string
  label: string
  type: 'number' | 'bool' | 'select'
  default: number | boolean | string
  minimum?: number | null
  maximum?: number | null
  step?: number | null
  unit?: string
  description?: string
  options?: { value: string; label: string }[]
}

export interface ScreenStrategy {
  id: string
  name: string
  description: string
  source: string
  kind: 'snapshot' | 'formula'
  category: string
  formula: string
  params: ScreenParamDef[]
}

export interface ScreenFactor {
  id: string
  name: string
  hit: boolean | null
  score: number
  max: number
  detail: string
}

export interface ScreenStock {
  rank: number
  code: string
  name: string
  price: number
  pct: number
  volume_ratio: number | null
  turnover: number | null
  amount: number
  score: number
  signal_date?: string
  detail?: string
  factors: ScreenFactor[]
}

export interface ScreenRunMeta {
  id: number
  strategy_id: string
  strategy_name: string
  params: Record<string, number | boolean | string>
  snapshot_time: string | null
  total_screened: number | null
  result_count: number
  elapsed_ms: number | null
  created_at: string
}

export interface ScreenRunResult {
  run_id?: number
  strategy_id: string
  strategy_name: string
  params: Record<string, number | boolean | string>
  snapshot_time: string
  total_screened: number
  candidates: number
  elapsed_ms: number
  result_count: number
  results: ScreenStock[]
  disclaimer: string
}

export interface ScreenRunDetail extends ScreenRunMeta {
  results: ScreenStock[]
}

// ---------- 组合策略组回测 ----------

export interface StrategyGroupDef {
  id: string
  name: string
  description: string
  entry_ids: string[]
  entry_combine: 'and' | 'or'
  risk_ids: string[]
  exit_kind: string
  max_positions: number
  max_weight: number
  risk_per_trade: number
  hard_stop_pct: number
  stop_atr_mult: number
  trail_drawdown_pct: number
  max_holding_days: number
  time_exit_min_return_pct: number
  min_amount: number
  requires_forecast: boolean
  enabled: boolean
}

export interface PortfolioBacktestRequest {
  months: number
  group_ids: string[]
  mode: 'individual' | 'combined' | 'both'
  initial_cash: number
  max_positions: number
  max_exposure: number
  fee_rate: number
  stamp_tax_rate: number
  slippage: number
  market_timing_enabled: boolean
  market_breadth_threshold: number
  board: string
  exclude_st: boolean
  limit?: number | null
  save?: boolean
}

export interface PortfolioState {
  running: boolean
  phase: string
  done: number
  total: number
  started_at: string | null
  finished_at: string | null
  error?: string | null
}

export interface PortfolioEquityPoint {
  date: string
  equity: number
  cash: number
  market_value: number
  exposure_pct: number
  positions: number
}

export interface PortfolioTrade {
  group_id: string
  code: string
  name: string
  signal_date: string
  entry_date: string
  exit_date: string
  entry_price: number
  exit_price: number
  shares: number
  buy_amount: number
  sell_amount: number
  fees: number
  pnl: number
  return_pct: number
  holding_days: number
  exit_reason: string
}

export interface PortfolioMetrics {
  start_date: string
  end_date: string
  days: number
  initial_cash: number
  final_equity: number
  total_return_pct: number
  annualized_return_pct: number
  max_drawdown_pct: number
  sharpe: number
  trades: number
  win_rate_pct: number
  avg_trade_return_pct: number
  median_trade_return_pct: number
  profit_factor: number
  avg_holding_days: number
  total_fees: number
  turnover_pct: number
  max_exposure_pct: number
  avg_exposure_pct: number
  group_summary?: {
    group_id: string
    trades: number
    win_rate_pct: number
    avg_return_pct: number
    realized_pnl: number
    profit_factor: number
  }[]
}

export interface PortfolioRun {
  mode: 'individual' | 'combined'
  group_id?: string
  group_name: string
  metrics: PortfolioMetrics
  equity_curve: PortfolioEquityPoint[]
  trades: PortfolioTrade[]
}

export interface PortfolioReport {
  generated_at: string
  data_as_of?: string | null
  universe_size: number
  start_date: string
  end_date: string
  params: Record<string, unknown>
  warnings: string[]
  runs: PortfolioRun[]
  elapsed_s: number
  disclaimer: string
}

export interface PortfolioRunSummary {
  id: number
  created_at: string
  months: number
  group_ids: string[]
  mode: string
  status: string
  elapsed_s: number
  params: Record<string, unknown>
  summary: Partial<PortfolioMetrics>
}

export interface PortfolioRunDetail extends PortfolioRunSummary {
  result: PortfolioReport | null
}

async function handle<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  return resp.json() as Promise<T>
}

export const api = {
  health: () => fetch('/api/health').then(r => handle<Health>(r)),

  searchStocks: (q: string) =>
    fetch(`/api/stocks/search?q=${encodeURIComponent(q)}`).then(r => handle<{ results: StockRef[] }>(r)),

  hotStocks: () => fetch('/api/stocks/hot').then(r => handle<{ results: StockRef[] }>(r)),

  kline: (code: string, period: string, days: number) =>
    fetch(`/api/stocks/kline?code=${code}&period=${period}&days=${days}`)
      .then(r => handle<Kline>(r)),

  presets: () =>
    fetch('/api/factors/presets').then(r => handle<{ presets: Preset[]; etf_quick_picks: StockRef[] }>(r)),

  autoFactors: (code: string) =>
    fetch(`/api/factors/auto?code=${encodeURIComponent(code)}`)
      .then(r => handle<{ industry: string | null; factors: StockRef[]; source: 'builtin' | 'auto' | 'index_only'; note: string }>(r)),

  listGroups: () => fetch('/api/factors/groups').then(r => handle<{ groups: FactorGroup[] }>(r)),

  saveGroup: (body: { name: string; target_code: string; target_name?: string | null; factors: StockRef[] }) =>
    fetch('/api/factors/groups', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(r => handle<{ id: number }>(r)),

  deleteGroup: (id: number) =>
    fetch(`/api/factors/groups/${id}`, { method: 'DELETE' }).then(r => handle<{ ok: boolean }>(r)),

  predict: (body: PredictRequest) =>
    fetch('/api/predict', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(r => handle<ForecastRecord>(r)),

  history: (limit = 50) =>
    fetch(`/api/history?limit=${limit}`).then(r => handle<{ records: ForecastRecord[]; stats: { total_forecasts: number; unique_stocks: number } }>(r)),

  deleteHistory: (id: number) =>
    fetch(`/api/history/${id}`, { method: 'DELETE' }).then(r => handle<{ ok: boolean }>(r)),

  // ---------- 智能选股 ----------

  screenerStrategies: () =>
    fetch('/api/screener/strategies').then(r => handle<{ strategies: ScreenStrategy[] }>(r)),

  runScreen: (body: { strategy_id: string; params?: Record<string, number | boolean | string>; save?: boolean }) =>
    fetch('/api/screener/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(r => handle<ScreenRunResult>(r)),

  runScreenMulti: (body: {
    strategy_ids: string[]
    combine: 'and' | 'or'
    exclude_ids?: string[]
    params?: Record<string, number | boolean | string>
    save?: boolean
  }) =>
    fetch('/api/screener/run-multi', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(r => handle<ScreenRunResult & { per_strategy?: Record<string, number>; excluded?: number }>(r)),

  screenRuns: (limit = 50) =>
    fetch(`/api/screener/runs?limit=${limit}`).then(r => handle<{ runs: ScreenRunMeta[] }>(r)),

  screenRun: (id: number) =>
    fetch(`/api/screener/runs/${id}`).then(r => handle<ScreenRunDetail>(r)),

  deleteScreenRun: (id: number) =>
    fetch(`/api/screener/runs/${id}`, { method: 'DELETE' }).then(r => handle<{ ok: boolean }>(r)),

  // ---------- 组合策略组回测 ----------

  portfolioGroups: () =>
    fetch('/api/portfolio/groups').then(r => handle<{ groups: StrategyGroupDef[] }>(r)),

  runPortfolioBacktest: (body: PortfolioBacktestRequest) =>
    fetch('/api/portfolio/backtest', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(r => handle<{ started: boolean; state: PortfolioState }>(r)),

  portfolioStatus: () =>
    fetch('/api/portfolio/status').then(r => handle<PortfolioState>(r)),

  portfolioReport: () =>
    fetch('/api/portfolio/report').then(r => handle<PortfolioReport>(r)),

  portfolioRuns: (limit = 30) =>
    fetch(`/api/portfolio/runs?limit=${limit}`).then(r => handle<{ runs: PortfolioRunSummary[] }>(r)),

  portfolioRun: (id: number) =>
    fetch(`/api/portfolio/runs/${id}`).then(r => handle<PortfolioRunDetail>(r)),

  // ---------- 历史数据仓库 ----------

  dataStatus: () =>
    fetch('/api/data/status').then(r => handle<DataStatus>(r)),

  dataSync: (body: { years?: number; mode?: 'update' | 'full'; codes?: string[] }) =>
    fetch('/api/data/sync', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(r => handle<SyncState>(r)),

  // ---------- 自选分组 + 行情 ----------

  watchGroups: () =>
    fetch('/api/watch/groups').then(r => handle<{ groups: WatchGroup[]; indexes: IndexQuote[] }>(r)),

  addWatchGroup: (name: string) =>
    fetch('/api/watch/groups', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
    }).then(r => handle<{ id: number }>(r)),

  renameWatchGroup: (id: number, name: string) =>
    fetch(`/api/watch/groups/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
    }).then(r => handle<{ ok: boolean }>(r)),

  deleteWatchGroup: (id: number) =>
    fetch(`/api/watch/groups/${id}`, { method: 'DELETE' }).then(r => handle<{ ok: boolean }>(r)),

  addWatchItem: (groupId: number, code: string, name?: string) =>
    fetch(`/api/watch/groups/${groupId}/items`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, name: name ?? '' }),
    }).then(r => handle<{ id: number; name: string }>(r)),

  removeWatchItem: (itemId: number) =>
    fetch(`/api/watch/items/${itemId}`, { method: 'DELETE' }).then(r => handle<{ ok: boolean }>(r)),

  quotesSpot: (codes: string[]) =>
    fetch(`/api/quotes/spot?codes=${codes.join(',')}`).then(r => handle<{ quotes: Record<string, Spot> }>(r)),

  quotesIntraday: (code: string) =>
    fetch(`/api/quotes/intraday?code=${code}`).then(r => handle<Intraday>(r)),

  quotesKline: (code: string, period: 'daily' | 'weekly' | 'monthly', bars = 250) =>
    fetch(`/api/quotes/kline?code=${code}&period=${period}&bars=${bars}`).then(r => handle<KlineFull>(r)),
}

export interface DataStatus {
  synced_stocks: number
  fresh_stocks: number
  total_stocks: number
  data_as_of: string | null
  kline_rows: number
  sync: SyncState
  tdx_vipdoc: boolean
}

export interface SyncState {
  running: boolean
  phase: string
  done: number
  total: number
  ok: number
  failed: number
  refetched?: number
  errors: string[]
  started_at: string | null
  finished_at: string | null
  mode?: string | null
  elapsed?: number
}

// ---------- 自选分组 + 行情 ----------

export interface WatchItem {
  id: number
  code: string
  name: string
  sort: number
  price?: number | null
  pct?: number | null
}

export interface WatchGroup {
  id: number
  name: string
  sort: number
  items: WatchItem[]
}

export interface IndexQuote {
  code: string
  name: string
  price: number
  pct: number
}

export interface Spot {
  name: string
  price: number
  prev_close: number | null
  open: number | null
  high: number | null
  low: number | null
  volume: number
  amount: number
  pct: number
  time: string
}

export interface Intraday {
  code: string
  date: string
  times: string[]
  prices: number[]
  avgs: number[]
  volumes: number[]
  prev_close: number
}

export interface KlineFull {
  code: string
  dates: string[]
  open: (number | null)[]
  high: (number | null)[]
  low: (number | null)[]
  close: (number | null)[]
  volume: (number | null)[]
  amount: (number | null)[]
  ma5: (number | null)[]
  ma10: (number | null)[]
  ma20: (number | null)[]
  ma60: (number | null)[]
  dif: (number | null)[]
  dea: (number | null)[]
  macd: (number | null)[]
  kdj_k: (number | null)[]
  kdj_d: (number | null)[]
  kdj_j: (number | null)[]
  rsi6: (number | null)[]
  boll_mid: (number | null)[]
  boll_up: (number | null)[]
  boll_low: (number | null)[]
}

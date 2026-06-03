declare global {
  interface Window {
    go?: {
      main?: {
        App?: {
          GetAppInfo: () => Promise<AppInfo>
          GetSettings: () => Promise<SettingsResponse>
          SaveSettings: (settings: Settings) => Promise<SettingsResponse>
          ApplyPortfolioCandidate: (request: ApplyPortfolioCandidateRequest) => Promise<SettingsResponse>
          CreateTask: (request: CreateTaskRequest) => Promise<TaskDTO>
          StartTask: (id: string) => Promise<TaskDTO>
          CancelTask: (id: string) => Promise<TaskDTO>
          ListTasks: (query: TaskQuery) => Promise<TaskDTO[]>
          GetTask: (id: string) => Promise<TaskDTO>
          RefreshTaskStatus: (id: string) => Promise<TaskDTO>
          GetTaskLog: (id: string, tailBytes: number) => Promise<string>
          GetTimeMachineDetail: (id: string) => Promise<TimeMachineDetail>
          DeleteTask: (id: string) => Promise<void>
          ScanMarketDataFiles: () => Promise<MarketDataFile[]>
          ListMarketDataFiles: () => Promise<MarketDataFile[]>
          ListStockBasic: (query: StockBasicQuery) => Promise<StockBasic[]>
          ListDailyBars: (query: DailyQuery) => Promise<DailyBar[]>
          ListFinancialIndicators: (query: FinancialQuery) => Promise<FinancialIndicator[]>
          GetStockValuation: (query: ValuationQuery) => Promise<StockValuation>
          ListLimitBreakoutCandidates: (query: BreakoutQuery) => Promise<LimitBreakoutCandidate[]>
          RefreshLimitBreakoutCandidates: (query: BreakoutQuery) => Promise<LimitBreakoutCandidate[]>
          ListLimitUpMomentumCandidates: (query: LimitUpMomentumQuery) => Promise<LimitUpMomentumCandidate[]>
          RefreshLimitUpMomentumCandidates: (query: LimitUpMomentumQuery) => Promise<LimitUpMomentumCandidate[]>
          GetPositionSummary: () => Promise<PositionSummary>
          GetPositionHistory: () => Promise<PositionHistoryPoint[]>
          GetPositionHoldings: () => Promise<PositionItem[]>
          GetPositionRecommendation: () => Promise<PositionRecommendation>
          GeneratePositionSignal: (req: GenerateSignalRequest) => Promise<GenerateSignalResponse>
          GetSignalRunStatus: () => Promise<RunStatus>
          ConfirmPositionTrades: (trades: TradeRequest[]) => Promise<PositionSummary>
          PreviewDataset: (query: DatasetPreviewQuery) => Promise<DatasetPreview>
          RunDataUpdate: (req: DataUpdateRequest) => Promise<void>
          GetDataUpdateStatus: () => Promise<RunStatus>
          ListDatasetUpdateStatus: () => Promise<DatasetUpdateStatus[]>
          ListDataFetchJobs: () => Promise<DataFetchJob[]>
        }
      }
    }
  }
}

export interface AppInfo {
  name: string
  version: string
}

export interface Settings {
  workspace_path: string
  data_path: string
  default_initial_cash: number
  default_rebalance_freq: number
  tushare_token: string
  strategies: Record<string, StrategySettings>
  portfolio_risk: Record<string, unknown>
  exit_rules: Record<string, unknown>
}

export interface StrategySettings {
  label: string
  enabled: boolean
  weight: number
  rebalance: string
  universe?: Record<string, unknown>
  filters?: Record<string, unknown>
  selection?: Record<string, unknown>
  position?: Record<string, unknown>
}

export interface ValidationIssue {
  field: string
  message: string
}

export interface SettingsResponse {
  settings: Settings
  issues: ValidationIssue[]
}

export interface ApplyPortfolioCandidateRequest {
  run_id: string
  candidate_id: string
}

export interface CreateTaskRequest {
  name: string
  task_type: string
  params: Record<string, unknown>
}

export interface TaskQuery {
  status?: string
  limit?: number
}

export interface TaskDTO {
  id: string
  name: string
  task_type: string
  status: string
  progress: number
  params: Record<string, unknown>
  summary: Record<string, unknown>
  result_path: string
  log_path: string
  worker_type: string
  worker_pid: number
  external_run_id: string
  error_message: string
  created_at: string
  queued_at: string
  started_at: string
  finished_at: string
  updated_at: string
}

export interface TimeMachineSnapshot {
  date: string
  cash: number
  market_value: number
  equity: number
  n_holdings: number
  unrealized_pnl: number
  realized_pnl: number
  cum_return: number
}

export interface TimeMachineTrade {
  date: string
  ts_code: string
  name: string
  action: string
  shares: number
  price: number
  amount: number
  hold_days: number
  realized_pnl: number
  exit_reason: string
  exec_date: string
  is_new: boolean
}

export interface TimeMachinePosition {
  date: string
  ts_code: string
  name: string
  shares: number
  avg_cost: number
  price: number
  market_value: number
  unrealized_pnl: number
  unrealized_pct: number
  today_pnl: number
  today_pct: number
  weight: number
  hold_days: number
}

export interface TimeMachineDetail {
  run_id: string
  summary: Record<string, unknown>
  snapshots: TimeMachineSnapshot[]
  trades: TimeMachineTrade[]
  positions: TimeMachinePosition[]
}

export interface MarketDataFile {
  id: string
  data_type: string
  partition_name: string
  file_path: string
  row_count: number
  file_size: number
  created_at: string
  updated_at: string
}

export interface StockBasicQuery {
  keyword?: string
  limit?: number
}

export interface StockBasic {
  ts_code: string
  symbol: string
  name: string
  area: string
  industry: string
  market: string
  list_date: string
  list_status: string
}

export interface DailyQuery {
  ts_code: string
  start_date?: string
  end_date?: string
  limit?: number
}

export interface DailyBar {
  ts_code: string
  trade_date: string
  open: number
  high: number
  low: number
  close: number
  pre_close: number
  change: number
  pct_chg: number
  vol: number
  amount: number
}

export interface DatasetPreviewQuery {
  dataset: string
  limit?: number
}

export interface DatasetPreview {
  dataset: string
  columns: string[]
  rows: Array<Record<string, string>>
}

export interface FinancialQuery {
  ts_code: string
  limit?: number
}

export interface FinancialIndicator {
  ts_code: string
  ann_date: string
  end_date: string
  eps: number
  roe: number
  gross_margin: number
  net_margin: number
  debt_to_assets: number
}

export interface ValuationQuery {
  ts_code: string
}

export interface StockValuation {
  ts_code: string
  name: string
  industry: string
  trade_date: string
  close: number
  total_mv: number
  circ_mv: number
  pe_ttm: number
  pb: number
  ps_ttm: number
  roe: number
  debt_to_assets: number
  peer_count: number
  valuation_percentile: number
  market_cap_percentile: number
  implied_mv: number
  mispricing_pct: number
  score: number
  verdict: string
  reason: string
  tags: string[]
}

export interface BreakoutQuery {
  limit?: number
  lookback?: number
  recent_days?: number
}

export interface BreakoutBar {
  trade_date: string
  open: number
  high: number
  low: number
  close: number
  pct_chg: number
  projected: boolean
}

export interface LimitBreakoutCandidate {
  ts_code: string
  name: string
  industry: string
  latest_date: string
  close: number
  score: number
  flat_score: number
  breakout_score: number
  quality_score: number
  base_low: number
  base_high: number
  base_ratio: number
  base_return: number
  recent_return: number
  limit_up_count: number
  volume_surge: number
  roe: number
  net_margin: number
  debt_to_assets: number
  reasons: string[]
  bars: BreakoutBar[]
  projected_bars: BreakoutBar[]
}

export interface LimitUpMomentumQuery {
  limit?: number
  lookback?: number
  history_days?: number
}

export interface LimitUpMomentumCandidate {
  ts_code: string
  name: string
  industry: string
  trade_date: string
  close: number
  stage: string
  recommendation: string
  score: number
  chain_potential: number
  end_risk: number
  liquidity_risk: number
  fund_confirmation: number
  limit_up_count: number
  consecutive_boards: number
  next_day_return: number
  return_3d: number
  return_5d: number
  return_10d: number
  max_drawdown_5d: number
  recent_20_return: number
  recent_60_return: number
  turnover_rate: number
  volume_ratio: number
  amount: number
  total_mv: number
  circ_mv: number
  dragon_tiger_net_buy: number
  institution_net_buy: number
  reasons: string[]
  risks: string[]
  bars?: BreakoutBar[]
  projected_bars?: BreakoutBar[]
}

export async function getAppInfo(): Promise<AppInfo> {
  if (window.go?.main?.App?.GetAppInfo) {
    return window.go.main.App.GetAppInfo()
  }

  return {
    name: 'Quant Stock Desktop',
    version: 'dev'
  }
}

export async function getSettings(): Promise<SettingsResponse> {
  if (window.go?.main?.App?.GetSettings) {
    return window.go.main.App.GetSettings()
  }

  return {
    settings: {
      workspace_path: '/Users/kitty/IdeaProjects/lh/quant_stock_desktop',
      data_path: '/Users/kitty/IdeaProjects/lh/quant_stock_desktop/data_store',
      default_initial_cash: 500000,
      default_rebalance_freq: 5,
      tushare_token: '',
      strategies: defaultStrategies(),
      portfolio_risk: {
        max_industry_weight: 0.3,
        max_single_weight: 0.05,
        max_holdings: 50,
        cash_buffer: 0,
        blacklist: [],
        market_regime: { enabled: false, trend_window: 60, breadth_window: 20, min_breadth: 0.45, normal_exposure: 1, weak_exposure: 0.5, bear_exposure: 0.3 }
      },
      exit_rules: { enabled: true, stop_loss: -0.12, trailing_stop: -0.08, trailing_exec: 'next_open', slippage: 0.003 }
    },
    issues: []
  }
}

function defaultStrategies(): Record<string, StrategySettings> {
  return {
    small_cap_quality: { label: '小盘质量', enabled: true, weight: 0.3, rebalance: 'monthly', filters: {}, universe: {}, position: {} },
    reversal: { label: '业绩反转', enabled: true, weight: 0.25, rebalance: 'quarterly', filters: {}, position: {} },
    insider_buy: { label: '高管增持', enabled: true, weight: 0.2, rebalance: 'event', filters: {}, position: {} },
    lhb_follow: { label: '龙虎榜', enabled: true, weight: 0.1, rebalance: 'event', filters: {}, position: {} },
    industry_rotation: { label: '行业轮动', enabled: true, weight: 0.15, rebalance: 'monthly', selection: {}, universe: {}, position: {} },
    trend_quality: { label: '趋势质量', enabled: false, weight: 0.12, rebalance: 'monthly', filters: {}, universe: {}, position: {} },
    dividend_low_vol: { label: '低波红利', enabled: false, weight: 0.1, rebalance: 'monthly', filters: {}, universe: {}, position: {} },
    forecast_revision: { label: '业绩预告', enabled: false, weight: 0.1, rebalance: 'event', filters: {}, position: {} },
    garp_quality: { label: '质量成长', enabled: false, weight: 0.12, rebalance: 'monthly', filters: {}, universe: {}, position: {} },
    moneyflow_pullback: { label: '资金低吸', enabled: false, weight: 0.08, rebalance: 'event', filters: {}, position: {} },
    beijing_se: { label: '北交所', enabled: false, weight: 0.15, rebalance: 'monthly', filters: {}, universe: {}, position: {} }
  }
}

export async function saveSettings(settings: Settings): Promise<SettingsResponse> {
  if (window.go?.main?.App?.SaveSettings) {
    return window.go.main.App.SaveSettings(settings)
  }

  return {
    settings,
    issues: []
  }
}

export async function applyPortfolioCandidate(request: ApplyPortfolioCandidateRequest): Promise<SettingsResponse> {
  if (window.go?.main?.App?.ApplyPortfolioCandidate) {
    return window.go.main.App.ApplyPortfolioCandidate(request)
  }
  return getSettings()
}

export async function createTask(request: CreateTaskRequest): Promise<TaskDTO> {
  if (window.go?.main?.App?.CreateTask) {
    return window.go.main.App.CreateTask(request)
  }

  return mockTask(request)
}

export async function startTask(id: string): Promise<TaskDTO> {
  if (window.go?.main?.App?.StartTask) {
    return window.go.main.App.StartTask(id)
  }
  const now = new Date().toISOString()
  return { ...mockTask({ name: id, task_type: 'evaluation_time_machine', params: {} }), id, status: 'running', started_at: now, updated_at: now }
}

export async function cancelTask(id: string): Promise<TaskDTO> {
  if (window.go?.main?.App?.CancelTask) {
    return window.go.main.App.CancelTask(id)
  }
  const now = new Date().toISOString()
  return { ...mockTask({ name: id, task_type: 'evaluation_time_machine', params: {} }), id, status: 'cancelled', finished_at: now, updated_at: now }
}

export async function listTasks(query: TaskQuery = {}): Promise<TaskDTO[]> {
  if (window.go?.main?.App?.ListTasks) {
    return window.go.main.App.ListTasks(query)
  }

  return []
}

export async function refreshTaskStatus(id: string): Promise<TaskDTO> {
  if (window.go?.main?.App?.RefreshTaskStatus) {
    return window.go.main.App.RefreshTaskStatus(id)
  }
  return mockTask({ name: id, task_type: 'evaluation_time_machine', params: {} })
}

export async function getTaskLog(id: string, tailBytes = 20000): Promise<string> {
  if (window.go?.main?.App?.GetTaskLog) {
    return window.go.main.App.GetTaskLog(id, tailBytes)
  }
  return `暂无日志: ${id}`
}

export async function getTimeMachineDetail(id: string): Promise<TimeMachineDetail> {
  if (window.go?.main?.App?.GetTimeMachineDetail) {
    return window.go.main.App.GetTimeMachineDetail(id)
  }
  return { run_id: id, summary: {}, snapshots: [], trades: [], positions: [] }
}

export async function deleteTask(id: string): Promise<void> {
  if (window.go?.main?.App?.DeleteTask) {
    return window.go.main.App.DeleteTask(id)
  }
}

export async function scanMarketDataFiles(): Promise<MarketDataFile[]> {
  if (window.go?.main?.App?.ScanMarketDataFiles) {
    return window.go.main.App.ScanMarketDataFiles()
  }
  return []
}

export async function listMarketDataFiles(): Promise<MarketDataFile[]> {
  if (window.go?.main?.App?.ListMarketDataFiles) {
    return window.go.main.App.ListMarketDataFiles()
  }
  return []
}

export async function listStockBasic(query: StockBasicQuery = {}): Promise<StockBasic[]> {
  if (window.go?.main?.App?.ListStockBasic) {
    return window.go.main.App.ListStockBasic(query)
  }
  return []
}

export async function listDailyBars(query: DailyQuery): Promise<DailyBar[]> {
  if (window.go?.main?.App?.ListDailyBars) {
    return window.go.main.App.ListDailyBars(query)
  }
  return []
}

export async function listFinancialIndicators(query: FinancialQuery): Promise<FinancialIndicator[]> {
  if (window.go?.main?.App?.ListFinancialIndicators) {
    return window.go.main.App.ListFinancialIndicators(query)
  }
  return []
}

export async function getStockValuation(query: ValuationQuery): Promise<StockValuation | null> {
  if (window.go?.main?.App?.GetStockValuation) {
    return window.go.main.App.GetStockValuation(query)
  }
  return null
}

export async function listLimitBreakoutCandidates(query: BreakoutQuery = {}): Promise<LimitBreakoutCandidate[]> {
  if (window.go?.main?.App?.ListLimitBreakoutCandidates) {
    return (await window.go.main.App.ListLimitBreakoutCandidates(query)) || []
  }
  return []
}

export async function refreshLimitBreakoutCandidates(query: BreakoutQuery = {}): Promise<LimitBreakoutCandidate[]> {
  if (window.go?.main?.App?.RefreshLimitBreakoutCandidates) {
    return (await window.go.main.App.RefreshLimitBreakoutCandidates(query)) || []
  }
  return listLimitBreakoutCandidates(query)
}

export async function listLimitUpMomentumCandidates(query: LimitUpMomentumQuery = {}): Promise<LimitUpMomentumCandidate[]> {
  if (window.go?.main?.App?.ListLimitUpMomentumCandidates) {
    return (await window.go.main.App.ListLimitUpMomentumCandidates(query)) || []
  }
  return []
}

export async function refreshLimitUpMomentumCandidates(query: LimitUpMomentumQuery = {}): Promise<LimitUpMomentumCandidate[]> {
  if (window.go?.main?.App?.RefreshLimitUpMomentumCandidates) {
    return (await window.go.main.App.RefreshLimitUpMomentumCandidates(query)) || []
  }
  return listLimitUpMomentumCandidates(query)
}

export interface PositionItem {
  ts_code: string
  name: string
  industry: string
  shares: number
  avg_cost: number
  peak_price: number
  first_entry_date: string
  last_action_date: string
  holder_account: string
  note: string
  sources?: Array<{ strategy: string; weight: number }>
  trades?: Array<Record<string, unknown>>
  price: number
  cost: number
  market_value: number
  unrealized_pnl: number
  unrealized_pct: number
  prev_close: number
  today_pnl: number
  today_pct: number
  weight: number
  hold_days: number
}

export interface TradeRequest {
  ts_code: string
  action: 'BUY' | 'ADD' | 'TRIM' | 'SELL'
  shares: number
  price: number
  date?: string
  exit_reason?: string
  exit_pct?: number
  sources?: Array<{ strategy: string; weight: number }>
}

export interface PositionSummary {
  initial_cash: number
  cash: number
  market_value: number
  total_assets: number
  total_cost: number
  total_pnl: number
  today_pnl: number
  today_pct: number
  unrealized_pnl: number
  unrealized_pct: number
  realized_pnl: number
  cum_return: number
  n_holdings: number
  n_closed: number
  updated_at: string
  positions: PositionItem[]
}

export interface PositionHistoryPoint {
  date: string
  cash: number
  market_value: number
  equity: number
  n_holdings: number
  unrealized_pnl: number
  realized_pnl: number
  cum_return: number
  daily_return: number
}

export interface PositionRecommendationItem {
  action: string
  ts_code: string
  name: string
  industry: string
  from_weight: number
  to_weight: number
  delta_weight: number
  price: number
  pct_chg: number
  target_shares: number
  target_amount: number
  sources?: Array<{ strategy: string; weight: number }>
}

export interface PositionRecommendation {
  date: string
  generated_at: string
  total_weight: number
  n_holdings: number
  n_buy: number
  n_sell: number
  rebalanced: boolean
  rebalance_trades: number
  rows: PositionRecommendationItem[]
}

export interface GenerateSignalRequest {
  date?: string
  initial_cash?: number
  rebalance_freq?: number
}

export interface GenerateSignalResponse {
  date: string
  output: string
  success: boolean
}

export interface RunStatus {
  task: string
  state: string
  idx: number
  total: number
  stage: string
  name: string
  message: string
  started_at: string
  updated_at: string
  finished_at: string
}

export async function getPositionSummary(): Promise<PositionSummary> {
  if (window.go?.main?.App?.GetPositionSummary) {
    return window.go.main.App.GetPositionSummary()
  }
  return {
    initial_cash: 500000,
    cash: 500000,
    market_value: 0,
    total_assets: 500000,
    total_cost: 0,
    total_pnl: 0,
    today_pnl: 0,
    today_pct: 0,
    unrealized_pnl: 0,
    unrealized_pct: 0,
    realized_pnl: 0,
    cum_return: 0,
    n_holdings: 0,
    n_closed: 0,
    updated_at: '',
    positions: []
  }
}

export async function getPositionHistory(): Promise<PositionHistoryPoint[]> {
  if (window.go?.main?.App?.GetPositionHistory) {
    return (await window.go.main.App.GetPositionHistory()) || []
  }
  return []
}

export async function getPositionHoldings(): Promise<PositionItem[]> {
  if (window.go?.main?.App?.GetPositionHoldings) {
    return (await window.go.main.App.GetPositionHoldings()) || []
  }
  return []
}

export async function confirmPositionTrades(trades: TradeRequest[]): Promise<PositionSummary> {
  if (window.go?.main?.App?.ConfirmPositionTrades) {
    return window.go.main.App.ConfirmPositionTrades(trades)
  }
  return getPositionSummary()
}

export async function getPositionRecommendation(): Promise<PositionRecommendation> {
  if (window.go?.main?.App?.GetPositionRecommendation) {
    return window.go.main.App.GetPositionRecommendation()
  }
  return { date: '', generated_at: '', total_weight: 0, n_holdings: 0, n_buy: 0, n_sell: 0, rebalanced: false, rebalance_trades: 0, rows: [] }
}

export async function generatePositionSignal(req: GenerateSignalRequest = {}): Promise<GenerateSignalResponse> {
  if (window.go?.main?.App?.GeneratePositionSignal) {
    return window.go.main.App.GeneratePositionSignal(req)
  }
  return { date: '', output: '', success: false }
}

export async function getSignalRunStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetSignalRunStatus) {
    return window.go.main.App.GetSignalRunStatus()
  }
  return { task: 'daily_signal', state: 'idle', idx: 0, total: 0, stage: '', name: '', message: '', started_at: '', updated_at: '', finished_at: '' }
}

export async function previewDataset(query: DatasetPreviewQuery): Promise<DatasetPreview> {
  if (window.go?.main?.App?.PreviewDataset) {
    return window.go.main.App.PreviewDataset(query)
  }
  return { dataset: query.dataset, columns: [], rows: [] }
}

export interface DataUpdateRequest {
  phase: string
  start_date: string
  dataset?: string
}

export async function runDataUpdate(req: DataUpdateRequest): Promise<void> {
  if (window.go?.main?.App?.RunDataUpdate) {
    return window.go.main.App.RunDataUpdate(req)
  }
}

export async function getDataUpdateStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetDataUpdateStatus) {
    return window.go.main.App.GetDataUpdateStatus()
  }
  return { task: 'data_update', state: 'idle', idx: 0, total: 0, stage: '', name: '', message: '', started_at: '', updated_at: '', finished_at: '' }
}

export interface DatasetUpdateStatus {
  dataset: string
  category: string
  state: string
  progress_done: number
  progress_total: number
  message: string
  rows_written: number
  error_message: string
  started_at: string
  finished_at: string
  updated_at: string
}

export interface DataFetchJob {
  name: string
  category: string
}

export async function listDatasetUpdateStatus(): Promise<DatasetUpdateStatus[]> {
  if (window.go?.main?.App?.ListDatasetUpdateStatus) {
    return (await window.go.main.App.ListDatasetUpdateStatus()) || []
  }
  return []
}

export async function listDataFetchJobs(): Promise<DataFetchJob[]> {
  if (window.go?.main?.App?.ListDataFetchJobs) {
    return (await window.go.main.App.ListDataFetchJobs()) || []
  }
  return []
}

function mockTask(request: CreateTaskRequest): TaskDTO {
  const now = new Date().toISOString()
  return {
    id: `task_${Date.now()}`,
    name: request.name,
    task_type: request.task_type,
    status: 'created',
    progress: 0,
    params: request.params,
    summary: {},
    result_path: '',
    log_path: '',
    worker_type: 'python',
    worker_pid: 0,
    external_run_id: `tm_mock_${Date.now()}`,
    error_message: '',
    created_at: now,
    queued_at: '',
    started_at: '',
    finished_at: '',
    updated_at: now
  }
}

declare global {
  interface Window {
    go?: {
      main?: {
        App?: {
          GetAppInfo: () => Promise<AppInfo>
          GetArenaStrategyDefinitions: () => Promise<ArenaStrategyDefinition[]>
          GetProductionDiagnostics: () => Promise<Record<string, unknown>>
          GetSettings: () => Promise<SettingsResponse>
          SaveSettings: (settings: Settings) => Promise<SettingsResponse>
          RunStrategyScheduleNow: () => Promise<StrategyScheduleReport>
          TestStrategyScheduleWechat: () => Promise<StrategyScheduleReport>
          ListStrategyScheduleReports: () => Promise<StrategyScheduleReport[]>
          ApplyPortfolioCandidate: (request: ApplyPortfolioCandidateRequest) => Promise<SettingsResponse>
          RunProfitArenaLatestInference: () => Promise<TaskDTO>
          GetProfitArenaMarketDate: () => Promise<string>
          GetFactorStoreGovernance: (factorStoreID: string) => Promise<FactorStoreGovernance>
          CreateTask: (request: CreateTaskRequest) => Promise<TaskDTO>
          StartTask: (id: string) => Promise<TaskDTO>
          RetryTask: (id: string) => Promise<TaskDTO>
          CancelTask: (id: string) => Promise<TaskDTO>
          ListTasks: (query: TaskQuery) => Promise<TaskDTO[]>
          GetTask: (id: string) => Promise<TaskDTO>
          RefreshTaskStatus: (id: string) => Promise<TaskDTO>
          ScanMarketDataFiles: () => Promise<MarketDataFile[]>
          ListMarketDataFiles: () => Promise<MarketDataFile[]>
          ListStockBasic: (query: StockBasicQuery) => Promise<StockBasic[]>
          ListDailyBars: (query: DailyQuery) => Promise<DailyBar[]>
          ListFinancialIndicators: (query: FinancialQuery) => Promise<FinancialIndicator[]>
          GetStockValuation: (query: ValuationQuery) => Promise<StockValuation>
          ListFactorResearchRuns: (limit: number) => Promise<FactorResearchRunSummary[]>
          ListFactorICResults: (runID: string, limit: number) => Promise<FactorICResult[]>
          ListFactorStateICResults: (runID: string, limit: number) => Promise<FactorStateICResult[]>
          GetFactorModelRun: (runID: string) => Promise<FactorModelRun>
          ListFactorModelFeatures: (runID: string, limit: number) => Promise<FactorModelFeature[]>
          ListFactorModelPredictions: (runID: string, limit: number) => Promise<FactorModelPrediction[]>
          ListFactorCorrelationResults: (runID: string, limit: number) => Promise<FactorCorrelationResult[]>
          ListFactorStressResults: (runID: string, limit: number) => Promise<FactorStressResult[]>
          ListFactorLatestPredictions: (runID: string, limit: number) => Promise<FactorLatestPrediction[]>
          ListFactorObservationEvents: (limit: number) => Promise<FactorObservationEvent[]>
          ListFactorAdmissionComparisons: (limit: number) => Promise<FactorAdmissionComparison[]>
          RunProfitArenaTraining: () => Promise<void>
          GetProfitArenaRunStatus: () => Promise<RunStatus>
          GetFactorSnapshotStatus: () => Promise<RunStatus>
          ListProfitArenaRuns: (limit: number) => Promise<ProfitArenaRunSummary[]>
          ListProfitArenaEvaluations: (runID: string, limit: number) => Promise<ProfitArenaEvaluation[]>
          ListProfitArenaPredictions: (runID: string, limit: number) => Promise<ProfitArenaPrediction[]>
          ListProfitArenaFeatures: (runID: string, limit: number) => Promise<ProfitArenaFeature[]>
          GetPositionSummary: () => Promise<PositionSummary>
          GetPositionHistory: () => Promise<PositionHistoryPoint[]>
          GetPositionHoldings: () => Promise<PositionItem[]>
          GetPositionRecommendation: () => Promise<PositionRecommendation>
          GetProfitArenaRebalanceStatus: () => Promise<RunStatus>
          ConfirmPositionTrades: (trades: TradeRequest[]) => Promise<PositionSummary>
          RefreshPositionRealtimeQuotes: () => Promise<PositionSummary>
          ClearPositionPool: () => Promise<PositionSummary>
          RunDataUpdate: (req: DataUpdateRequest) => Promise<void>
          GetDataUpdateStatus: () => Promise<RunStatus>
          ListDatasetUpdateStatus: () => Promise<DatasetUpdateStatus[]>
          CheckExternalDependencies: () => Promise<ExternalDependencyStatus[]>
        }
      }
    }
  }
}

export interface AppInfo {
  name: string
  version: string
}

export interface ArenaStrategyDefinition {
  strategy_id: string
  display_name: string
  default_arena_name: string
  artifact_dir_name: string
  task_label: string
  tables: Record<string, unknown>
  metadata: Record<string, unknown>
  updated_at: string
}

export interface Settings {
  data_path: string
  database_backend: string
  mysql_dsn: string
  default_initial_cash: number
  default_rebalance_freq: number
  task_concurrency: number
  tushare_token: string
  llm_provider: string
  openai_token: string
  openai_model: string
  deepseek_token: string
  deepseek_model: string
  strategies: Record<string, StrategySettings>
  portfolio_risk: Record<string, unknown>
  exit_rules: Record<string, unknown>
  governance_rules: Record<string, unknown>
  strategy_schedule: StrategyScheduleSettings
}

export interface StrategyScheduleSettings {
  enabled: boolean
  time_of_day: string
  weekdays: number[]
  targets: Record<string, boolean>
  wechat_webhook: string
  wechat_users: string[]
}

export interface StrategyScheduleReport {
  started_at: string
  finished_at: string
  success: boolean
  message: string
  wechat_content?: string
  rows: StrategyScheduleReportRow[]
  recommendation?: PositionRecommendation
}

export interface StrategyScheduleReportRow {
  target: string
  label: string
  status: string
  message: string
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

export interface ResearchReport {
  id: string
  subject_type: string
  subject_id: string
  report_type: string
  title: string
  model: string
  content_md: string
  payload: Record<string, unknown>
  created_at: string
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

export interface ActivePortfolioCandidate {
  run_id: string
  candidate_id: string
  name: string
  status: string
  score: number
  weights: Record<string, number>
  validation_status: string
  applied_at: string
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
  parent_id: string
  group_run_id: string
  subtask_key: string
  subtask_name: string
  sequence: number
  total: number
  attempt: number
  max_attempts: number
  created_at: string
  queued_at: string
  started_at: string
  finished_at: string
  updated_at: string
}

export interface FactorResearchRunSummary {
  run_id: string
  start_date: string
  end_date: string
  freq: string
  label: string
  status: string
  factor_count: number
  sample_dates: number
  sample_rows: number
  panel_path: string
  updated_at: string
  model_status: string
  rank_ic: number
}

export interface FactorICResult {
  run_id: string
  factor: string
  family: string
  variant: string
  horizon: string
  ic_mean: number
  rank_ic_mean: number
  ic_win_rate: number
  icir: number
  status: string
  long_short_return: number
  monotonic_score: number
}

export interface FactorStateICResult {
  run_id: string
  factor: string
  family: string
  variant: string
  horizon: string
  market_state: string
  rank_ic_mean: number
  ic_win_rate: number
  icir: number
  n_periods: number
  n_obs: number
  status: string
  summary_json: string
}

export interface FactorModelRun {
  run_id: string
  model_type: string
  label: string
  feature_count: number
  status: string
  model_path: string
  rank_ic: number
  top_bottom_spread: number
  summary_json: string
  updated_at: string
}

export interface FactorModelFeature {
  run_id: string
  feature: string
  importance: number
  rank_no: number
  summary_json: string
}

export interface FactorModelPrediction {
  run_id: string
  trade_date: string
  ts_code: string
  pred_score: number
  realized_return: number
  pred_rank: number
  test_year: number
}

export interface FactorCorrelationResult {
  run_id: string
  feature_a: string
  feature_b: string
  correlation: number
  abs_correlation: number
  family_a: string
  family_b: string
  keep_feature: string
  drop_feature: string
  reason: string
}

export interface FactorStressResult {
  run_id: string
  bucket_type: string
  bucket_key: string
  bucket_label: string
  start_date: string
  end_date: string
  n_days: number
  total_return: number
  annual_return: number
  max_drawdown: number
  sharpe: number
  win_rate: number
  avg_daily_return: number
  volatility: number
  summary_json: string
}

export interface FactorLatestPrediction {
  run_id: string
  trade_date: string
  ts_code: string
  name: string
  industry: string
  price: number
  pct_chg: number
  pred_score: number
  pred_rank: number
  is_top20: boolean
  model_path: string
  first_seen_date: string
  last_seen_date: string
  seen_count: number
  observation_days: number
  observation_status: string
  observation_reason: string
  observation_result: string
}

export interface FactorObservationEvent {
  strategy: string
  run_id: string
  trade_date: string
  ts_code: string
  name: string
  industry: string
  event_type: string
  rank_no: number
  score: number
  rank_pct: number
  reason: string
  first_seen_date: string
  last_seen_date: string
  seen_count: number
  observation_status: string
  created_at: string
}

export interface FactorAdmissionComparison {
  run_id: string
  strategy: string
  admission: string
  admission_score: number
  reason: string
  annual_return: number
  total_return: number
  max_drawdown: number
  sharpe: number
  avg_turnover: number
  effective_start: string
  effective_end: string
  stress_penalty: number
  stress_bad_event_count: number
  stress_crash_state_failed: boolean
  stress_weak_drawdown_failed: boolean
  generated_at: string
}

export interface ProfitArenaRunSummary {
  run_id: string
  start_date: string
  end_date: string
  train_mode: string
  model_type: string
  feature_count: number
  status: string
  best_scope: string
  best_horizon: number
  best_top_n: number
  best_compound_return: number
  summary_json: string
  model_path: string
  updated_at: string
}

export interface ProfitArenaEvaluation {
  run_id: string
  scope: string
  horizon: number
  top_n: number
  min_pred_return: number
  min_market_up_ratio: number
  min_market_ret5: number
  min_market_amount_chg5: number
  min_industry_up_ratio: number
  segment: string
  trade_count: number
  trade_days: number
  avg_return: number
  win_rate: number
  compound_return: number
  annual_return: number
  max_drawdown: number
  sharpe: number
  capital_compound_return: number
  capital_annual_return: number
  capital_max_drawdown: number
  capital_sharpe: number
  capital_final_equity: number
  summary_json: string
  updated_at: string
}

export interface ProfitArenaPrediction {
  run_id: string
  scope: string
  horizon: number
  trade_date: string
  ts_code: string
  name: string
  industry: string
  size_bucket: string
  price: number
  amount: number
  pred_return: number
  model_score: number
  realized_return: number
  future_return: number
  future_max_return: number
  future_drawdown: number
  crash_prob: number
  exit_date: string
  is_latest: boolean
  summary_json: string
  updated_at: string
}

export interface ProfitArenaFeature {
  run_id: string
  scope: string
  horizon: number
  feature: string
  importance: number
  rank_no: number
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

export async function getAppInfo(): Promise<AppInfo> {
  if (window.go?.main?.App?.GetAppInfo) {
    return window.go.main.App.GetAppInfo()
  }

  return {
    name: 'Quant Stock 生产工作台',
    version: 'runtime-offline'
  }
}

export async function getProductionDiagnostics(): Promise<Record<string, unknown>> {
  if (window.go?.main?.App?.GetProductionDiagnostics) {
    return (await window.go.main.App.GetProductionDiagnostics()) || {}
  }
  return { status: 'offline', message: '桌面后端未连接' }
}

export async function getArenaStrategyDefinitions(): Promise<ArenaStrategyDefinition[]> {
  if (window.go?.main?.App?.GetArenaStrategyDefinitions) {
    return (await window.go.main.App.GetArenaStrategyDefinitions()) || []
  }
  return []
}

export async function getSettings(): Promise<SettingsResponse> {
  if (window.go?.main?.App?.GetSettings) {
    return window.go.main.App.GetSettings()
  }

  return {
    settings: defaultSettings(),
    issues: [{ field: 'backend', message: '桌面后端未连接，当前配置为只读安全视图，不能保存或触发生产任务' }]
  }
}

function defaultSettings(): Settings {
  return {
    data_path: '',
    database_backend: 'mysql',
    mysql_dsn: '',
    default_initial_cash: 500000,
    default_rebalance_freq: 5,
    task_concurrency: 2,
    tushare_token: '',
    llm_provider: 'openai',
    openai_token: '',
    openai_model: 'gpt-5.5',
    deepseek_token: '',
    deepseek_model: 'deepseek-v4-pro',
    strategies: defaultStrategies(),
    portfolio_risk: {
      max_industry_weight: 0.3,
      max_single_weight: 0.05,
      max_holdings: 50,
      cash_buffer: 0,
      blacklist: [],
      market_regime: { enabled: false, trend_window: 60, breadth_window: 20, min_breadth: 0.45, normal_exposure: 1, weak_exposure: 0.5, bear_exposure: 0.3 }
    },
    exit_rules: { enabled: true, stop_loss: -0.12, trailing_stop: -0.08, trailing_exec: 'next_open', slippage: 0.003 },
    governance_rules: defaultGovernanceRules(),
    strategy_schedule: defaultStrategySchedule()
  }
}

function defaultStrategySchedule(): StrategyScheduleSettings {
  return {
    enabled: false,
    time_of_day: '22:00',
    weekdays: [1, 2, 3, 4, 5],
    targets: { arena: true },
    wechat_webhook: '',
    wechat_users: []
  }
}

function defaultGovernanceRules(): Record<string, unknown> {
  return {
    profit_arena_factor_store_id: 'stock_factor_base_v1',
    min_arena_score: 85,
    min_rank_ic: 0.08,
    min_capital_annual_return: 0.12,
    max_capital_drawdown: 0.22,
    min_capital_sharpe: 0.3,
    max_single_weight: 0.1,
    max_industry_weight: 0.3,
    max_target_participation_rate: 0.02,
    max_allowed_participation_rate: 0.05,
    require_fresh_factor_snapshot: true,
    require_profit_arena_spec_pass: true,
    require_positive_capital_return: true,
    block_untradeable_boards: true,
    auto_refresh_after_factor_snapshot: true
  }
}

function defaultStrategies(): Record<string, StrategySettings> {
  return {
    profit_arena_model: { label: '通用策略', enabled: true, weight: 1, rebalance: 'daily', filters: {}, universe: {}, position: { n_holdings: 10, max_single_weight: 0.1 } }
  }
}

export async function saveSettings(settings: Settings): Promise<SettingsResponse> {
  if (window.go?.main?.App?.SaveSettings) {
    return window.go.main.App.SaveSettings(settings)
  }

  void settings
  throw backendUnavailable('保存桌面设置')
}

export async function runStrategyScheduleNow(): Promise<StrategyScheduleReport> {
  if (window.go?.main?.App?.RunStrategyScheduleNow) {
    return window.go.main.App.RunStrategyScheduleNow()
  }
  throw backendUnavailable('手动执行通用策略生产链路')
}

export async function testStrategyScheduleWechat(): Promise<StrategyScheduleReport> {
  if (window.go?.main?.App?.TestStrategyScheduleWechat) {
    return window.go.main.App.TestStrategyScheduleWechat()
  }
  throw backendUnavailable('企业微信连通检查')
}

export async function listStrategyScheduleReports(): Promise<StrategyScheduleReport[]> {
  if (window.go?.main?.App?.ListStrategyScheduleReports) {
    return (await window.go.main.App.ListStrategyScheduleReports()) || []
  }
  return []
}

export async function applyPortfolioCandidate(request: ApplyPortfolioCandidateRequest): Promise<SettingsResponse> {
  if (window.go?.main?.App?.ApplyPortfolioCandidate) {
    return window.go.main.App.ApplyPortfolioCandidate(request)
  }
  void request
  throw backendUnavailable('应用组合候选配置')
}

export async function runProfitArenaLatestInference(): Promise<TaskDTO> {
  if (window.go?.main?.App?.RunProfitArenaLatestInference) {
    return window.go.main.App.RunProfitArenaLatestInference()
  }
  throw backendUnavailable('通用策略最新截面推理')
}

export async function getProfitArenaMarketDate(): Promise<string> {
  if (window.go?.main?.App?.GetProfitArenaMarketDate) {
    return window.go.main.App.GetProfitArenaMarketDate()
  }
  return ''
}

export async function createTask(request: CreateTaskRequest): Promise<TaskDTO> {
  const normalizedRequest = normalizeDesktopCreateTaskRequest(request)
  if (window.go?.main?.App?.CreateTask) {
    return window.go.main.App.CreateTask(normalizedRequest)
  }

  throw backendUnavailable(`${normalizedRequest.name || normalizedRequest.task_type} 任务创建`)
}

function normalizeDesktopCreateTaskRequest(request: CreateTaskRequest): CreateTaskRequest {
  const params = { ...(request.params || {}) }
  if (!request.task_type) {
    throw new Error('桌面任务必须指定生产任务类型；请使用通用策略训练、数据更新或因子快照入口')
  }
  const taskType = request.task_type
  const normalized = { ...request, task_type: taskType, params }
  if (taskType === 'factor_research') return normalized
  if (taskType === 'model_training') {
    const strategy = String(params.strategy || params.task || '').trim()
    if (strategy === 'profit_arena_model' || strategy === 'profit_arena') {
      params.strategy = 'profit_arena_model'
      return normalized
    }
    throw new Error('桌面生产入口只允许新建通用策略训练/推理任务')
  }
  throw new Error(`桌面生产入口不允许新建 ${taskType}；请使用通用策略、因子研究留档或数据更新入口`)
}

export async function startTask(id: string): Promise<TaskDTO> {
  if (window.go?.main?.App?.StartTask) {
    return window.go.main.App.StartTask(id)
  }
  throw backendUnavailable(`启动任务 ${id}`)
}

export async function retryTask(id: string): Promise<TaskDTO> {
  if (window.go?.main?.App?.RetryTask) {
    return window.go.main.App.RetryTask(id)
  }
  throw backendUnavailable(`重试任务 ${id}`)
}

export async function cancelTask(id: string): Promise<TaskDTO> {
  if (window.go?.main?.App?.CancelTask) {
    return window.go.main.App.CancelTask(id)
  }
  throw backendUnavailable(`取消任务 ${id}`)
}

export async function listTasks(query: TaskQuery = {}): Promise<TaskDTO[]> {
  if (window.go?.main?.App?.ListTasks) {
    return window.go.main.App.ListTasks(query)
  }

  return []
}

export async function listFactorResearchRuns(limit = 20): Promise<FactorResearchRunSummary[]> {
  if (window.go?.main?.App?.ListFactorResearchRuns) {
    return (await window.go.main.App.ListFactorResearchRuns(limit)) || []
  }
  return []
}

export async function listFactorICResults(runID = '', limit = 80): Promise<FactorICResult[]> {
  if (window.go?.main?.App?.ListFactorICResults) {
    return (await window.go.main.App.ListFactorICResults(runID, limit)) || []
  }
  return []
}

export async function listFactorStateICResults(runID = '', limit = 120): Promise<FactorStateICResult[]> {
  if (window.go?.main?.App?.ListFactorStateICResults) {
    return (await window.go.main.App.ListFactorStateICResults(runID, limit)) || []
  }
  return []
}

export async function getFactorModelRun(runID = ''): Promise<FactorModelRun | null> {
  if (window.go?.main?.App?.GetFactorModelRun) {
    const model = await window.go.main.App.GetFactorModelRun(runID)
    return model?.run_id ? model : null
  }
  return null
}

export async function listFactorModelFeatures(runID = '', limit = 80): Promise<FactorModelFeature[]> {
  if (window.go?.main?.App?.ListFactorModelFeatures) {
    return (await window.go.main.App.ListFactorModelFeatures(runID, limit)) || []
  }
  return []
}

export async function listFactorModelPredictions(runID = '', limit = 120): Promise<FactorModelPrediction[]> {
  if (window.go?.main?.App?.ListFactorModelPredictions) {
    return (await window.go.main.App.ListFactorModelPredictions(runID, limit)) || []
  }
  return []
}

export async function listFactorCorrelationResults(runID = '', limit = 120): Promise<FactorCorrelationResult[]> {
  if (window.go?.main?.App?.ListFactorCorrelationResults) {
    return (await window.go.main.App.ListFactorCorrelationResults(runID, limit)) || []
  }
  return []
}

export async function listFactorStressResults(runID = '', limit = 160): Promise<FactorStressResult[]> {
  if (window.go?.main?.App?.ListFactorStressResults) {
    return (await window.go.main.App.ListFactorStressResults(runID, limit)) || []
  }
  return []
}

export async function listFactorLatestPredictions(runID = '', limit = 120): Promise<FactorLatestPrediction[]> {
  if (window.go?.main?.App?.ListFactorLatestPredictions) {
    return (await window.go.main.App.ListFactorLatestPredictions(runID, limit)) || []
  }
  return []
}

export async function listFactorObservationEvents(limit = 80): Promise<FactorObservationEvent[]> {
  if (window.go?.main?.App?.ListFactorObservationEvents) {
    return (await window.go.main.App.ListFactorObservationEvents(limit)) || []
  }
  return []
}

export async function listFactorAdmissionComparisons(limit = 30): Promise<FactorAdmissionComparison[]> {
  if (window.go?.main?.App?.ListFactorAdmissionComparisons) {
    return (await window.go.main.App.ListFactorAdmissionComparisons(limit)) || []
  }
  return []
}

export async function runProfitArenaTraining(): Promise<void> {
  if (window.go?.main?.App?.RunProfitArenaTraining) {
    return window.go.main.App.RunProfitArenaTraining()
  }
  throw backendUnavailable('通用策略训练')
}

export async function getProfitArenaRunStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetProfitArenaRunStatus) {
    return window.go.main.App.GetProfitArenaRunStatus()
  }
  return emptyRunStatus('profit_arena_model')
}

export async function listProfitArenaRuns(limit = 20): Promise<ProfitArenaRunSummary[]> {
  if (window.go?.main?.App?.ListProfitArenaRuns) {
    return (await window.go.main.App.ListProfitArenaRuns(limit)) || []
  }
  return []
}

export async function listProfitArenaEvaluations(runID = '', limit = 100): Promise<ProfitArenaEvaluation[]> {
  if (window.go?.main?.App?.ListProfitArenaEvaluations) {
    return (await window.go.main.App.ListProfitArenaEvaluations(runID, limit)) || []
  }
  return []
}

export async function listProfitArenaPredictions(runID = '', limit = 100): Promise<ProfitArenaPrediction[]> {
  if (window.go?.main?.App?.ListProfitArenaPredictions) {
    return (await window.go.main.App.ListProfitArenaPredictions(runID, limit)) || []
  }
  return []
}

export async function listProfitArenaFeatures(runID = '', limit = 50): Promise<ProfitArenaFeature[]> {
  if (window.go?.main?.App?.ListProfitArenaFeatures) {
    return (await window.go.main.App.ListProfitArenaFeatures(runID, limit)) || []
  }
  return []
}

























export async function refreshTaskStatus(id: string): Promise<TaskDTO> {
  if (window.go?.main?.App?.RefreshTaskStatus) {
    return window.go.main.App.RefreshTaskStatus(id)
  }
  throw backendUnavailable(`刷新任务 ${id}`)
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


export interface PositionTradeRecord {
  id: number
  date: string
  action: string
  ts_code: string
  name: string
  shares: number
  price: number
  amount: number
  fee: number
  net_amount: number
  cash_after: number
  position_pnl: number
  realized_pnl: number
  exit_reason: string
  exit_pct: number
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
  trigger_type?: string
  trigger_price?: number
  sources?: Array<{ strategy: string; weight: number }>
}

export interface PositionSummary {
  initial_cash: number
  cash: number
  market_value: number
  total_assets: number
  total_cost: number
  total_fee: number
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
  quote_status?: string
  quote_message?: string
  quote_source?: string
  quote_updated_at?: string
  positions: PositionItem[]
  trades: PositionTradeRecord[]
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
  buy_trigger_price: number
  sell_target_price: number
  stop_price: number
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
  active_strategy_versions?: Array<{ strategy: string; label: string; version: number; mode: string; weight: number }>
  metadata?: Record<string, unknown>
  rows: PositionRecommendationItem[]
}

export interface RunStatus {
  task: string
  task_type: string
  state: string
  idx: number
  total: number
  stage: string
  name: string
  message: string
  worker_pid: number
  started_at: string
  updated_at: string
  finished_at: string
}

export function emptyRunStatus(task: string, patch: Partial<RunStatus> = {}): RunStatus {
  return { task, task_type: inferRunStatusTaskType(task), state: 'idle', idx: 0, total: 0, stage: '', name: '', message: '', worker_pid: 0, started_at: '', updated_at: '', finished_at: '', ...patch }
}

function inferRunStatusTaskType(task: string): string {
  if (task === 'data_update') return 'data_update'
  if (task === 'profit_arena_model') return 'model_training'
  if (task === 'factor_snapshot') return 'factor_snapshot'
  return 'python'
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
    total_fee: 0,
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
    positions: [],
    trades: []
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
  void trades
  throw backendUnavailable('确认持仓交易')
}

export async function refreshPositionRealtimeQuotes(): Promise<PositionSummary> {
  if (window.go?.main?.App?.RefreshPositionRealtimeQuotes) {
    return window.go.main.App.RefreshPositionRealtimeQuotes()
  }
  throw backendUnavailable('刷新持仓实时价格')
}

export async function clearPositionPool(): Promise<PositionSummary> {
  if (window.go?.main?.App?.ClearPositionPool) {
    return window.go.main.App.ClearPositionPool()
  }
  throw backendUnavailable('清空持仓池')
}

export async function getPositionRecommendation(): Promise<PositionRecommendation> {
  if (window.go?.main?.App?.GetPositionRecommendation) {
    return window.go.main.App.GetPositionRecommendation()
  }
  return { date: '', generated_at: '', total_weight: 0, n_holdings: 0, n_buy: 0, n_sell: 0, rebalanced: false, rebalance_trades: 0, rows: [] }
}



















export async function getProfitArenaRebalanceStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetProfitArenaRebalanceStatus) {
    return window.go.main.App.GetProfitArenaRebalanceStatus()
  }
  return emptyRunStatus('profit_arena_rebalance', { task_type: 'profit_arena_rebalance' })
}









export interface DataUpdateRequest {
  phase: string
  start_date: string
  dataset?: string
  exclude_datasets?: string[]
}

export async function runDataUpdate(req: DataUpdateRequest): Promise<void> {
  if (window.go?.main?.App?.RunDataUpdate) {
    return window.go.main.App.RunDataUpdate(req)
  }
  void req
  throw backendUnavailable('数据更新')
}

export async function getDataUpdateStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetDataUpdateStatus) {
    return window.go.main.App.GetDataUpdateStatus()
  }
  return emptyRunStatus('data_update')
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

export interface ExternalDependencyStatus {
  key: string
  name: string
  category: string
  state: string
  latency_ms: number
  message: string
  checked_at: string
}

export type FactorStoreGovernance = Record<string, unknown>

export async function getFactorStoreGovernance(factorStoreID = 'stock_factor_base_v1'): Promise<FactorStoreGovernance> {
  if (window.go?.main?.App?.GetFactorStoreGovernance) {
    return (await window.go.main.App.GetFactorStoreGovernance(factorStoreID)) || {}
  }
  return { factor_store_id: factorStoreID, status: 'missing', message: '桌面后端未连接，无法读取因子快照治理信息' }
}

export async function getFactorSnapshotStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetFactorSnapshotStatus) {
    return window.go.main.App.GetFactorSnapshotStatus()
  }
  return emptyRunStatus('factor_snapshot')
}

export async function listDatasetUpdateStatus(): Promise<DatasetUpdateStatus[]> {
  if (window.go?.main?.App?.ListDatasetUpdateStatus) {
    return (await window.go.main.App.ListDatasetUpdateStatus()) || []
  }
  return []
}

export async function checkExternalDependencies(): Promise<ExternalDependencyStatus[]> {
  if (window.go?.main?.App?.CheckExternalDependencies) {
    return (await window.go.main.App.CheckExternalDependencies()) || []
  }
  const checkedAt = new Date().toISOString()
  return [
    { key: 'mysql', name: 'MySQL 数据库', category: '基础设施', state: 'missing', latency_ms: 0, message: '桌面后端未连接，无法确认', checked_at: checkedAt },
    { key: 'tushare', name: 'Tushare 数据接口', category: '行情/财务数据', state: 'missing', latency_ms: 0, message: '桌面后端未连接，无法确认', checked_at: checkedAt },
    { key: 'llm', name: 'ChatGPT/OpenAI 模型接口', category: 'AI 复盘/报告', state: 'missing', latency_ms: 0, message: '桌面后端未连接，无法确认', checked_at: checkedAt },
    { key: 'realtime_quote', name: '实时行情接口', category: '实时价格', state: 'missing', latency_ms: 0, message: '桌面后端未连接，无法确认', checked_at: checkedAt },
    { key: 'wechat', name: '企业微信机器人', category: '通知', state: 'missing', latency_ms: 0, message: '桌面后端未连接，无法确认', checked_at: checkedAt },
  ]
}

function backendUnavailable(action: string) {
  return new Error(`${action}需要桌面后端连接；当前未连接运行时服务，已阻止本地替代执行`)
}

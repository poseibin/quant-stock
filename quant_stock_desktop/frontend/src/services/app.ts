declare global {
  interface Window {
    go?: {
      main?: {
        App?: {
          GetAppInfo: () => Promise<AppInfo>
          GetSettings: () => Promise<SettingsResponse>
          SaveSettings: (settings: Settings) => Promise<SettingsResponse>
          RunStrategyScheduleNow: () => Promise<StrategyScheduleReport>
          TestStrategyScheduleWechat: () => Promise<StrategyScheduleReport>
          ListStrategyScheduleReports: () => Promise<StrategyScheduleReport[]>
          ApplyPortfolioCandidate: (request: ApplyPortfolioCandidateRequest) => Promise<SettingsResponse>
          GetSignalPortfolioContext: () => Promise<SignalPortfolioContext>
          ListStrategyVersions: (strategy: string) => Promise<StrategyVersion[]>
          ActivateStrategyVersion: (request: StrategyVersionActivateRequest) => Promise<SettingsResponse>
          SetStrategyVersionStatus: (request: StrategyVersionStatusRequest) => Promise<StrategyVersion[]>
          GetActiveStrategyModelRun: (strategy: string) => Promise<ActiveStrategyModelRun>
          ActivateStrategyModelRun: (request: StrategyModelRunRequest) => Promise<ActiveStrategyModelRun>
          ReviewStrategyVersion: (request: StrategyVersionActivateRequest) => Promise<ValidationReview>
          ListValidationEvidence: (query: ValidationEvidenceQuery) => Promise<ValidationEvidence>
          RefreshRecommendationHindsight: () => Promise<RecommendationHindsight[]>
          ListRecommendationHindsight: () => Promise<RecommendationHindsight[]>
          RefreshGovernanceAudit: () => Promise<GovernanceDashboard>
          ListGovernanceDashboard: () => Promise<GovernanceDashboard>
          AnalyzePortfolioTask: (id: string) => Promise<TaskDTO>
          RunFactorLatestInference: () => Promise<TaskDTO>
          RunFactorAutoTune: (maxRounds: number, trialsPerRound: number, useDeepSeek: boolean) => Promise<TaskDTO>
          RunProfitArenaLatestInference: () => Promise<TaskDTO>
          GetProfitArenaMarketDate: () => Promise<string>
          CreateTask: (request: CreateTaskRequest) => Promise<TaskDTO>
          StartTask: (id: string) => Promise<TaskDTO>
          RetryTask: (id: string) => Promise<TaskDTO>
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
          GetLatestPolicySupportSignal: () => Promise<PolicySupportSignal>
          ListPolicySupportCandidates: (limit: number) => Promise<PolicySupportCandidate[]>
          RunPolicySupportAnalysis: () => Promise<void>
          GetPolicySupportAnalysisStatus: () => Promise<RunStatus>
          ListLimitBreakoutCandidates: (query: BreakoutQuery) => Promise<LimitBreakoutCandidate[]>
          RefreshLimitBreakoutCandidates: (query: BreakoutQuery) => Promise<LimitBreakoutCandidate[]>
          GetLimitBreakoutRunStatus: () => Promise<RunStatus>
          ClearLimitBreakoutCandidates: () => Promise<void>
          ListLimitUpMomentumCandidates: (query: LimitUpMomentumQuery) => Promise<LimitUpMomentumCandidate[]>
          RefreshLimitUpMomentumCandidates: (query: LimitUpMomentumQuery) => Promise<LimitUpMomentumCandidate[]>
          GetLimitUpMomentumRunStatus: () => Promise<RunStatus>
          ClearLimitUpMomentumCandidates: () => Promise<void>
          RunLimitSignalEvaluation: () => Promise<void>
          GetLimitSignalEvaluationRunStatus: () => Promise<RunStatus>
          ListLimitSignalEvaluationSummary: () => Promise<LimitSignalEvaluationSummary[]>
          ListLimitSignalTimeMachineSlices: (limit: number) => Promise<LimitSignalTimeMachineSlice[]>
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
          ListFactorAutoTuneRuns: (limit: number) => Promise<FactorAutoTuneRun[]>
          ListFactorAutoTuneTrials: (runID: string, limit: number) => Promise<FactorAutoTuneTrial[]>
          ListCrashWarningRuns: (limit: number) => Promise<CrashWarningRunSummary[]>
          ListCrashWarningFeatures: (runID: string, limit: number) => Promise<CrashWarningFeature[]>
          RunProfitArenaTraining: () => Promise<void>
          GetProfitArenaRunStatus: () => Promise<RunStatus>
          ListProfitArenaRuns: (limit: number) => Promise<ProfitArenaRunSummary[]>
          ListProfitArenaEvaluations: (runID: string, limit: number) => Promise<ProfitArenaEvaluation[]>
          ListProfitArenaPredictions: (runID: string, limit: number) => Promise<ProfitArenaPrediction[]>
          ListProfitArenaFeatures: (runID: string, limit: number) => Promise<ProfitArenaFeature[]>
          RunLimitUpModelTraining: () => Promise<void>
          GetLimitUpModelRunStatus: () => Promise<RunStatus>
          ListLimitUpModelRuns: (limit: number) => Promise<LimitUpModelRunSummary[]>
          ListLimitUpModelFeatures: (runID: string, limit: number) => Promise<LimitUpModelFeature[]>
          ListLimitUpModelPredictions: (runID: string, limit: number) => Promise<LimitUpModelPrediction[]>
          ListLimitUpModelTimeMachineSlices: (runID: string, limit: number) => Promise<LimitUpModelTimeMachineSlice[]>
          RunLimitBreakoutModelTraining: () => Promise<void>
          GetLimitBreakoutModelRunStatus: () => Promise<RunStatus>
          ListLimitBreakoutModelRuns: (limit: number) => Promise<LimitUpModelRunSummary[]>
          ListLimitBreakoutModelFeatures: (runID: string, limit: number) => Promise<LimitUpModelFeature[]>
          ListLimitBreakoutModelPredictions: (runID: string, limit: number) => Promise<LimitUpModelPrediction[]>
          ListLimitBreakoutModelTimeMachineSlices: (runID: string, limit: number) => Promise<LimitUpModelTimeMachineSlice[]>
          GetPositionSummary: () => Promise<PositionSummary>
          ListT0Recommendations: (limit: number) => Promise<T0Recommendation[]>
          ListT0DataPullCandidates: (limit: number) => Promise<T0DataPullCandidate[]>
          ListT0DailyRuns: (limit: number) => Promise<T0DailyRunSummary[]>
          ListT0DailyBacktests: (limit: number) => Promise<T0DailyBacktest[]>
          ListT0TimeMachineResults: (limit: number) => Promise<T0TimeMachineResult[]>
          RunT0DailyResearch: () => Promise<void>
          RunT0TimeMachine: () => Promise<void>
          GetT0DailyResearchStatus: () => Promise<RunStatus>
          GetT0TimeMachineStatus: () => Promise<RunStatus>
          GetPositionHistory: () => Promise<PositionHistoryPoint[]>
          GetPositionHoldings: () => Promise<PositionItem[]>
          GetPositionRecommendation: () => Promise<PositionRecommendation>
          GeneratePositionSignal: (req: GenerateSignalRequest) => Promise<GenerateSignalResponse>
          CancelPositionSignal: () => Promise<RunStatus>
          GetSignalRunStatus: () => Promise<RunStatus>
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

const fallbackSettingsKey = 'quant-stock.settings.preview'

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

export interface StrategyVersion {
  strategy: string
  version: number
  label: string
  config: Record<string, unknown>
  is_active: boolean
  promotion_status: string
  validation: Record<string, unknown>
  source: string
  note: string
  created_at: string
  activated_at: string
}

export interface StrategyVersionActivateRequest {
  strategy: string
  version: number
}

export interface StrategyVersionStatusRequest extends StrategyVersionActivateRequest {
  status: string
}

export interface StrategyModelRunRequest {
  strategy: string
  run_id: string
}

export interface ActiveStrategyModelRun {
  strategy: string
  run_id: string
  updated_at: string
}

export interface ValidationReview {
  id: string
  subject_type: string
  subject_id: string
  strategy: string
  strategy_version: number
  source_run_id: string
  status: string
  score: number
  gates: Record<string, unknown>
  metrics: Record<string, unknown>
  recommendation: string
  created_at: string
  updated_at: string
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

export interface DataSnapshot {
  id: string
  subject_type: string
  subject_id: string
  snapshot: Record<string, unknown>
  created_at: string
}

export interface ValidationEvidenceQuery {
  subject_type?: string
  subject_id?: string
  source_run_id?: string
  limit?: number
}

export interface ValidationEvidence {
  reviews: ValidationReview[]
  reports: ResearchReport[]
  snapshots: DataSnapshot[]
}

export interface RecommendationHindsight {
  id: string
  recommendation_date: string
  horizon_days: number
  next_date: string
  n_holdings: number
  n_eval: number
  weighted_return?: number | null
  equal_weight_return?: number | null
  hit_rate?: number | null
  payload: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface RiskExposure {
  id: string
  subject_type: string
  subject_id: string
  as_of_date: string
  n_holdings: number
  total_weight: number
  max_single_weight: number
  top5_weight: number
  industry: Record<string, number>
  strategy: Record<string, number>
  payload: Record<string, unknown>
  created_at: string
}

export interface PaperTradingLog {
  id: string
  signal_date: string
  ts_code: string
  name: string
  action: string
  target_weight: number
  actual_weight?: number | null
  status: string
  reason: string
  payload: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface PromotionDecision {
  id: string
  strategy: string
  strategy_version: number
  current_status: string
  recommended_status: string
  score: number
  reason: string
  payload: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface WalkForwardWindow {
  id: string
  subject_type: string
  subject_id: string
  window_name: string
  start_date: string
  end_date: string
  status: string
  score: number
  metrics: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ParameterExperiment {
  id: string
  strategy: string
  strategy_version: number
  param_set: string
  status: string
  score: number
  params: Record<string, unknown>
  metrics: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface GovernanceDashboard {
  hindsight: RecommendationHindsight[]
  risk: RiskExposure[]
  paper: PaperTradingLog[]
  promotion: PromotionDecision[]
  walk: WalkForwardWindow[]
  params: ParameterExperiment[]
  data_quality: Record<string, unknown>
  parameter_recommendations: Array<Record<string, unknown>>
  retirement: Array<Record<string, unknown>>
  portfolio_attribution: Array<Record<string, unknown>>
  recovery: Record<string, unknown>
  reports: ResearchReport[]
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

export interface SignalPortfolioCandidate {
  run_id: string
  candidate_id: string
  rank: number
  name: string
  objective: string
  status: string
  score: number
  strategies: string
  weights: Record<string, number>
  annual_return: number | null
  max_drawdown: number | null
  sharpe: number | null
  calmar: number | null
  avg_turnover: number | null
  avg_holdings: number | null
  rebalance_freq: number
  validation_status: string
  reason: string
  updated_at: string
  is_active: boolean
}

export interface SignalPortfolioContext {
  active: ActivePortfolioCandidate | null
  candidates: SignalPortfolioCandidate[]
  can_generate: boolean
  blocked_reason: string
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

export interface FactorAutoTuneRun {
  run_id: string
  base_model_run_id: string
  start_date: string
  end_date: string
  status: string
  best_trial_id: string
  best_model_run_id: string
  best_admission: string
  best_score: number
  summary_json: string
  created_at: string
  updated_at: string
}

export interface FactorAutoTuneTrial {
  run_id: string
  trial_id: string
  round_no: number
  source: string
  model_run_id: string
  eval_run_id: string
  params_json: string
  llm_direction_json: string
  admission: string
  admission_score: number
  reason: string
  annual_return: number
  total_return: number
  max_drawdown: number
  sharpe: number
  stress_bad_event_count: number
  stress_crash_state_failed: boolean
  stress_weak_drawdown_failed: boolean
  passed: boolean
  created_at: string
  updated_at: string
}

export interface CrashWarningRunSummary {
  run_id: string
  model_type: string
  start_date: string
  end_date: string
  horizon: number
  feature_count: number
  status: string
  model_path: string
  rows: number
  positive_rate: number
  roc_auc: number
  avg_precision: number
  top10_precision: number
  top10_capture: number
  p90_precision: number
  p90_recall: number
  summary_json: string
  updated_at: string
}

export interface CrashWarningFeature {
  run_id: string
  feature: string
  importance: number
  rank_no: number
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

export interface LimitUpModelRunSummary {
  run_id: string
  start_date: string
  end_date: string
  horizon: number
  model_type: string
  feature_count: number
  status: string
  model_path: string
  rows: number
  candidate_rows: number
  latest_date: string
  latest_count: number
  positive_rate: number
  baseline_return: number
  top_return: number
  top_excess_return: number
  top_hit_rate: number
  top_limit_up_rate: number
  top_drawdown: number
  rank_ic: number
  summary_json: string
  updated_at: string
}

export interface LimitUpModelFeature {
  run_id: string
  feature: string
  importance: number
  rank_no: number
}

export interface LimitUpModelPrediction {
  run_id: string
  trade_date: string
  ts_code: string
  name: string
  industry: string
  price: number
  high: number
  low: number
  today_pct: number
  prob: number
  model_score: number
  label: number
  fwd5_return: number
  fwd5_max_return: number
  max_drawdown_5d: number
  hit_limit_up_5d: number
  is_latest: boolean
  summary_json: string
  updated_at: string
  first_seen_date: string
  last_seen_date: string
  seen_count: number
  observation_days: number
  observation_status: string
  observation_reason: string
  observation_result: string
}

export interface LimitUpModelTimeMachineSlice {
  run_id: string
  trade_date: string
  candidate_count: number
  top_count: number
  avg_return: number
  avg_max_return: number
  hit_rate: number
  limit_up_hit_rate: number
  avg_drawdown: number
  rank_ic: number
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
  first_seen_date: string
  last_seen_date: string
  seen_count: number
  observation_days: number
  observation_status: string
  observation_reason: string
  observation_result: string
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
  first_seen_date: string
  last_seen_date: string
  seen_count: number
  observation_days: number
  observation_status: string
  observation_reason: string
  observation_result: string
}

export interface LimitSignalEvaluationSummary {
  signal_type: string
  strategy_version: string
  parameter_key: string
  sample_count: number
  pending_count: number
  hit_rate: number
  avg_return_1d: number
  avg_return_3d: number
  avg_return_5d: number
  avg_return_10d: number
  avg_max_drawdown_5d: number
  avg_score: number
  recommendation: string
  parameter_hint: string
  updated_at: string
}

export interface LimitSignalTimeMachineSlice {
  signal_type: string
  strategy_version: string
  parameter_key: string
  signal_date: string
  candidate_count: number
  evaluated_count: number
  hit_rate: number
  limit_up_hit_rate: number
  avg_return_1d: number
  avg_return_3d: number
  avg_return_5d: number
  avg_return_10d: number
  avg_target_return: number
  avg_max_drawdown_5d: number
  avg_score: number
  slice_score: number
  market_heat_score: number
  limit_up_count: number
  limit_up_ratio: number
  up_ratio: number
  hot_tags_json: string
  top_industries_json: string
  recommendation: string
  summary_json: string
  updated_at: string
}

export interface T0Recommendation {
  ts_code: string
  name: string
  industry: string
  trade_date: string
  action: string
  recommendation: string
  score: number
  state: string
  setup: string
  first_action: string
  shares: number
  max_t0_shares: number
  price: number
  avg_cost: number
  position_weight: number
  today_pct: number
  return_5d: number
  return_20d: number
  avg_range_20d: number
  drawdown_20d: number
  amount: number
  buy_back_price: number
  reduce_price: number
  stop_price: number
  t_ratio: number
  expected_edge: number
  plan_json: string
  reasons: string[]
  risks: string[]
  generated_at: string
  first_seen_date: string
  last_seen_date: string
  seen_count: number
  observation_days: number
  observation_status: string
  observation_reason: string
  observation_result: string
}

export interface T0DataPullCandidate {
  ts_code: string
  name: string
  industry: string
  trade_date: string
  action: string
  score: number
  state: string
  setup: string
  first_action: string
  price: number
  reduce_price: number
  buy_price: number
  stop_price: number
  t_ratio: number
  today_pct: number
  return_5d: number
  return_20d: number
  avg_range_20d: number
  drawdown_20d: number
  amount: number
  avg_amount_20d: number
  expected_edge: number
  target_freq: string
  lookback_days: number
  plan_json: string
  reasons: string[]
  risks: string[]
  generated_at: string
  first_seen_date: string
  last_seen_date: string
  seen_count: number
  observation_days: number
  observation_status: string
  observation_reason: string
  observation_result: string
}

export interface T0DailyBacktest {
  run_id: string
  ts_code: string
  name: string
  industry: string
  n_days: number
  n_candidates: number
  two_sided_rate: number
  one_sided_rate: number
  avg_edge: number
  total_edge: number
  avg_next_range: number
  score: number
  summary_json: string
  updated_at: string
}

export interface T0DailyRunSummary {
  run_id: string
  trade_date: string
  status: string
  candidate_count: number
  backtest_count: number
  summary_json: string
  created_at: string
  updated_at: string
}

export interface T0TimeMachineResult {
  run_id: string
  ts_code: string
  name: string
  industry: string
  as_of_date: string
  eval_start_date: string
  eval_end_date: string
  score: number
  n_eval_days: number
  two_sided_count: number
  one_sided_count: number
  t0_edge: number
  avg_t0_edge: number
  underlying_return: number
  combined_return: number
  max_drawdown: number
  summary_json: string
  updated_at: string
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

  const settings = readFallbackSettings()
  return {
    settings,
    issues: []
  }
}

function defaultSettings(): Settings {
  return {
    data_path: '/Users/kitty/Library/Application Support/QuantStockDesktop/data_store',
    database_backend: 'mysql',
    mysql_dsn: 'quant_stock:quant_stock@tcp(127.0.0.1:3306)/quant_stock?parseTime=true&charset=utf8mb4&loc=Local',
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

function readFallbackSettings(): Settings {
  const defaults = defaultSettings()
  try {
    const stored = window.localStorage.getItem(fallbackSettingsKey)
    if (!stored) {
      return defaults
    }
    const saved = JSON.parse(stored) as Partial<Settings>
    return {
      ...defaults,
      ...saved,
      strategies: { ...defaults.strategies, ...(saved.strategies || {}) },
      portfolio_risk: { ...defaults.portfolio_risk, ...(saved.portfolio_risk || {}) },
      exit_rules: { ...defaults.exit_rules, ...(saved.exit_rules || {}) },
      governance_rules: { ...defaults.governance_rules, ...(saved.governance_rules || {}) },
      strategy_schedule: {
        ...defaults.strategy_schedule,
        ...(saved.strategy_schedule || {}),
        targets: { ...defaults.strategy_schedule.targets, ...(saved.strategy_schedule?.targets || {}) }
      }
    }
  } catch {
    return defaults
  }
}

function writeFallbackSettings(settings: Settings) {
  try {
    window.localStorage.setItem(fallbackSettingsKey, JSON.stringify(settings))
  } catch {
    // Ignore browser storage failures in preview mode.
  }
}

function defaultGovernanceRules(): Record<string, unknown> {
  return {
    min_promotable_score: 0.85,
    min_research_score: 0.55,
    min_paper_score: 0.85,
    min_active_candidate_score: 0.85,
    max_drawdown: 0.22,
    min_sharpe: 0.3,
    min_calmar: 0.25,
    max_turnover: 0.45,
    min_stability_rate: 0.45,
    min_walk_forward_pass_rate: 0.5,
    min_eval_walk_forward_windows: 1,
    min_parameter_stable_rate: 0.5,
    require_positive_return: true,
    allow_missing_parameter_tests: true
  }
}

function defaultStrategies(): Record<string, StrategySettings> {
  return {
    market_regime_timing: { label: '市场状态择时', enabled: true, weight: 0.1, rebalance: 'weekly', filters: { market_regime: { trend_window: 60, breadth_window: 20, min_breadth: 0.45, normal_exposure: 1, weak_exposure: 0.5, bear_exposure: 0.25 } }, position: { n_holdings: 25, max_single_weight: 0.05 } },
    multi_factor_composite: { label: '多因子综合', enabled: true, weight: 0.18, rebalance: 'monthly', selection: { component_weights: { small_cap_quality: 0.3, trend_pullback: 0.25, dividend_quality: 0.2, earnings_revision: 0.15, industry_prosperity: 0.1 } }, position: { n_holdings: 30, max_single_weight: 0.05 } },
    small_cap_quality: { label: '小盘质量', enabled: true, weight: 0.3, rebalance: 'monthly', filters: {}, universe: {}, position: {} },
    trend_pullback: { label: '趋势回撤', enabled: true, weight: 0.12, rebalance: 'weekly', filters: {}, universe: {}, position: {} },
    turtle_breakout: { label: '海龟突破', enabled: true, weight: 0.08, rebalance: 'daily', filters: {}, universe: {}, position: {} },
    dividend_quality: { label: '红利质量', enabled: true, weight: 0.1, rebalance: 'monthly', filters: {}, universe: {}, position: {} },
    earnings_revision: { label: '盈利预期修正', enabled: true, weight: 0.1, rebalance: 'event', filters: {}, position: {} },
    industry_prosperity: { label: '行业景气', enabled: true, weight: 0.1, rebalance: 'monthly', selection: {}, universe: {}, position: {} },
    low_crowding_reversal: { label: '低拥挤反转', enabled: true, weight: 0.1, rebalance: 'quarterly', filters: {}, position: {} },
    event_enhanced: { label: '事件增强', enabled: false, weight: 0.06, rebalance: 'event', filters: {}, position: {} },
    beijing_satellite: { label: '北交所卫星', enabled: false, weight: 0.04, rebalance: 'monthly', filters: {}, universe: {}, position: {} },
    insider_buy: { label: '高管增持', enabled: true, weight: 0.2, rebalance: 'event', filters: {}, position: {} },
    lhb_follow: { label: '龙虎榜', enabled: true, weight: 0.1, rebalance: 'event', filters: {}, position: {} },
    trend_quality: { label: '趋势质量', enabled: false, weight: 0.12, rebalance: 'monthly', filters: {}, universe: {}, position: {} },
    garp_quality: { label: '质量成长', enabled: false, weight: 0.12, rebalance: 'monthly', filters: {}, universe: {}, position: {} },
    moneyflow_pullback: { label: '资金低吸', enabled: false, weight: 0.08, rebalance: 'event', filters: {}, position: {} }
  }
}

export async function saveSettings(settings: Settings): Promise<SettingsResponse> {
  if (window.go?.main?.App?.SaveSettings) {
    return window.go.main.App.SaveSettings(settings)
  }

  writeFallbackSettings(settings)
  return {
    settings,
    issues: []
  }
}

export async function runStrategyScheduleNow(): Promise<StrategyScheduleReport> {
  if (window.go?.main?.App?.RunStrategyScheduleNow) {
    return window.go.main.App.RunStrategyScheduleNow()
  }
  return {
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    success: true,
    message: '预览模式未连接后端',
    rows: []
  }
}

export async function testStrategyScheduleWechat(): Promise<StrategyScheduleReport> {
  if (window.go?.main?.App?.TestStrategyScheduleWechat) {
    return window.go.main.App.TestStrategyScheduleWechat()
  }
  return {
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    success: true,
    message: '预览模式未连接后端',
    rows: []
  }
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
  return getSettings()
}

export async function getSignalPortfolioContext(): Promise<SignalPortfolioContext> {
  if (window.go?.main?.App?.GetSignalPortfolioContext) {
    return window.go.main.App.GetSignalPortfolioContext()
  }
  return { active: null, candidates: [], can_generate: false, blocked_reason: '请先在评估中心完成组合评估并选择候选组合' }
}

export async function listStrategyVersions(strategy: string): Promise<StrategyVersion[]> {
  if (window.go?.main?.App?.ListStrategyVersions) {
    return (await window.go.main.App.ListStrategyVersions(strategy)) || []
  }
  return []
}

export async function activateStrategyVersion(request: StrategyVersionActivateRequest): Promise<SettingsResponse> {
  if (window.go?.main?.App?.ActivateStrategyVersion) {
    return window.go.main.App.ActivateStrategyVersion(request)
  }
  return getSettings()
}

export async function setStrategyVersionStatus(request: StrategyVersionStatusRequest): Promise<StrategyVersion[]> {
  if (window.go?.main?.App?.SetStrategyVersionStatus) {
    return (await window.go.main.App.SetStrategyVersionStatus(request)) || []
  }
  return []
}

export async function getActiveStrategyModelRun(strategy: string): Promise<ActiveStrategyModelRun> {
  if (window.go?.main?.App?.GetActiveStrategyModelRun) {
    return window.go.main.App.GetActiveStrategyModelRun(strategy)
  }
  return { strategy, run_id: '', updated_at: '' }
}

export async function activateStrategyModelRun(request: StrategyModelRunRequest): Promise<ActiveStrategyModelRun> {
  if (window.go?.main?.App?.ActivateStrategyModelRun) {
    return window.go.main.App.ActivateStrategyModelRun(request)
  }
  return { strategy: request.strategy, run_id: request.run_id, updated_at: new Date().toISOString() }
}

export async function reviewStrategyVersion(request: StrategyVersionActivateRequest): Promise<ValidationReview> {
  if (window.go?.main?.App?.ReviewStrategyVersion) {
    return window.go.main.App.ReviewStrategyVersion(request)
  }
  return { id: '', subject_type: 'strategy_version', subject_id: `${request.strategy}@${request.version}`, strategy: request.strategy, strategy_version: request.version, source_run_id: '', status: 'research', score: 0, gates: {}, metrics: {}, recommendation: '开发模式占位', created_at: '', updated_at: '' }
}

export async function listValidationEvidence(query: ValidationEvidenceQuery): Promise<ValidationEvidence> {
  if (window.go?.main?.App?.ListValidationEvidence) {
    return window.go.main.App.ListValidationEvidence(query)
  }
  return { reviews: [], reports: [], snapshots: [] }
}

export async function refreshRecommendationHindsight(): Promise<RecommendationHindsight[]> {
  if (window.go?.main?.App?.RefreshRecommendationHindsight) {
    return (await window.go.main.App.RefreshRecommendationHindsight()) || []
  }
  return []
}

export async function listRecommendationHindsight(): Promise<RecommendationHindsight[]> {
  if (window.go?.main?.App?.ListRecommendationHindsight) {
    return (await window.go.main.App.ListRecommendationHindsight()) || []
  }
  return []
}

export async function refreshGovernanceAudit(): Promise<GovernanceDashboard> {
  if (window.go?.main?.App?.RefreshGovernanceAudit) {
    return window.go.main.App.RefreshGovernanceAudit()
  }
  return emptyGovernanceDashboard()
}

export async function listGovernanceDashboard(): Promise<GovernanceDashboard> {
  if (window.go?.main?.App?.ListGovernanceDashboard) {
    return window.go.main.App.ListGovernanceDashboard()
  }
  return emptyGovernanceDashboard()
}

function emptyGovernanceDashboard(): GovernanceDashboard {
  return {
    hindsight: [],
    risk: [],
    paper: [],
    promotion: [],
    walk: [],
    params: [],
    data_quality: {},
    parameter_recommendations: [],
    retirement: [],
    portfolio_attribution: [],
    recovery: {},
    reports: []
  }
}

export async function analyzePortfolioTask(id: string): Promise<TaskDTO> {
  if (window.go?.main?.App?.AnalyzePortfolioTask) {
    return window.go.main.App.AnalyzePortfolioTask(id)
  }
  const task = mockTask({ name: id, task_type: 'portfolio_optimization', params: {} })
  return { ...task, summary: { ai_analysis: '开发模式占位：连接桌面应用后可运行量化优化分析。' } }
}

export async function runFactorLatestInference(): Promise<TaskDTO> {
  if (window.go?.main?.App?.RunFactorLatestInference) {
    return window.go.main.App.RunFactorLatestInference()
  }
  const now = new Date().toISOString()
  return { ...mockTask({ name: '通用策略重新推理', task_type: 'factor_research', params: { profile: 'inference' } }), status: 'running', started_at: now, updated_at: now }
}

export async function runProfitArenaLatestInference(): Promise<TaskDTO> {
  if (window.go?.main?.App?.RunProfitArenaLatestInference) {
    return window.go.main.App.RunProfitArenaLatestInference()
  }
  const now = new Date().toISOString()
  return { ...mockTask({ name: '收益擂台重新推理', task_type: 'model_training', params: { strategy: 'profit_arena_model', profile: 'inference' } }), status: 'running', started_at: now, updated_at: now }
}

export async function getProfitArenaMarketDate(): Promise<string> {
  if (window.go?.main?.App?.GetProfitArenaMarketDate) {
    return window.go.main.App.GetProfitArenaMarketDate()
  }
  return ''
}

export async function runFactorAutoTune(maxRounds = 12, trialsPerRound = 6, useDeepSeek = true): Promise<TaskDTO> {
  if (window.go?.main?.App?.RunFactorAutoTune) {
    return window.go.main.App.RunFactorAutoTune(maxRounds, trialsPerRound, useDeepSeek)
  }
  const now = new Date().toISOString()
  return { ...mockTask({ name: '通用策略自动调参', task_type: 'factor_autotune', params: { max_rounds: maxRounds, trials_per_round: trialsPerRound, use_deepseek: useDeepSeek } }), status: 'running', started_at: now, updated_at: now }
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

export async function retryTask(id: string): Promise<TaskDTO> {
  if (window.go?.main?.App?.RetryTask) {
    return window.go.main.App.RetryTask(id)
  }
  const now = new Date().toISOString()
  return { ...mockTask({ name: id, task_type: 'eval_strategy_admission', params: {} }), id, status: 'running', started_at: now, updated_at: now }
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

export async function listFactorAutoTuneRuns(limit = 20): Promise<FactorAutoTuneRun[]> {
  if (window.go?.main?.App?.ListFactorAutoTuneRuns) {
    return (await window.go.main.App.ListFactorAutoTuneRuns(limit)) || []
  }
  return []
}

export async function listFactorAutoTuneTrials(runID = '', limit = 80): Promise<FactorAutoTuneTrial[]> {
  if (window.go?.main?.App?.ListFactorAutoTuneTrials) {
    return (await window.go.main.App.ListFactorAutoTuneTrials(runID, limit)) || []
  }
  return []
}

export async function listCrashWarningRuns(limit = 20): Promise<CrashWarningRunSummary[]> {
  if (window.go?.main?.App?.ListCrashWarningRuns) {
    return (await window.go.main.App.ListCrashWarningRuns(limit)) || []
  }
  return []
}

export async function listCrashWarningFeatures(runID = '', limit = 20): Promise<CrashWarningFeature[]> {
  if (window.go?.main?.App?.ListCrashWarningFeatures) {
    return (await window.go.main.App.ListCrashWarningFeatures(runID, limit)) || []
  }
  return []
}

export async function runProfitArenaTraining(): Promise<void> {
  if (window.go?.main?.App?.RunProfitArenaTraining) {
    return window.go.main.App.RunProfitArenaTraining()
  }
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

export async function runLimitUpModelTraining(): Promise<void> {
  if (window.go?.main?.App?.RunLimitUpModelTraining) {
    return window.go.main.App.RunLimitUpModelTraining()
  }
}

export async function getLimitUpModelRunStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetLimitUpModelRunStatus) {
    return window.go.main.App.GetLimitUpModelRunStatus()
  }
  return emptyRunStatus('limit_up_model')
}

export async function listLimitUpModelRuns(limit = 20): Promise<LimitUpModelRunSummary[]> {
  if (window.go?.main?.App?.ListLimitUpModelRuns) {
    return (await window.go.main.App.ListLimitUpModelRuns(limit)) || []
  }
  return []
}

export async function listLimitUpModelFeatures(runID = '', limit = 20): Promise<LimitUpModelFeature[]> {
  if (window.go?.main?.App?.ListLimitUpModelFeatures) {
    return (await window.go.main.App.ListLimitUpModelFeatures(runID, limit)) || []
  }
  return []
}

export async function listLimitUpModelPredictions(runID = '', limit = 20): Promise<LimitUpModelPrediction[]> {
  if (window.go?.main?.App?.ListLimitUpModelPredictions) {
    return (await window.go.main.App.ListLimitUpModelPredictions(runID, limit)) || []
  }
  return []
}

export async function listLimitUpModelTimeMachineSlices(runID = '', limit = 80): Promise<LimitUpModelTimeMachineSlice[]> {
  if (window.go?.main?.App?.ListLimitUpModelTimeMachineSlices) {
    return (await window.go.main.App.ListLimitUpModelTimeMachineSlices(runID, limit)) || []
  }
  return []
}

export async function runLimitBreakoutModelTraining(): Promise<void> {
  if (window.go?.main?.App?.RunLimitBreakoutModelTraining) {
    return window.go.main.App.RunLimitBreakoutModelTraining()
  }
}

export async function getLimitBreakoutModelRunStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetLimitBreakoutModelRunStatus) {
    return window.go.main.App.GetLimitBreakoutModelRunStatus()
  }
  return emptyRunStatus('limit_breakout_model')
}

export async function listLimitBreakoutModelRuns(limit = 20): Promise<LimitUpModelRunSummary[]> {
  if (window.go?.main?.App?.ListLimitBreakoutModelRuns) {
    return (await window.go.main.App.ListLimitBreakoutModelRuns(limit)) || []
  }
  return []
}

export async function listLimitBreakoutModelFeatures(runID = '', limit = 20): Promise<LimitUpModelFeature[]> {
  if (window.go?.main?.App?.ListLimitBreakoutModelFeatures) {
    return (await window.go.main.App.ListLimitBreakoutModelFeatures(runID, limit)) || []
  }
  return []
}

export async function listLimitBreakoutModelPredictions(runID = '', limit = 20): Promise<LimitUpModelPrediction[]> {
  if (window.go?.main?.App?.ListLimitBreakoutModelPredictions) {
    return (await window.go.main.App.ListLimitBreakoutModelPredictions(runID, limit)) || []
  }
  return []
}

export async function listLimitBreakoutModelTimeMachineSlices(runID = '', limit = 80): Promise<LimitUpModelTimeMachineSlice[]> {
  if (window.go?.main?.App?.ListLimitBreakoutModelTimeMachineSlices) {
    return (await window.go.main.App.ListLimitBreakoutModelTimeMachineSlices(runID, limit)) || []
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

export interface PolicySupportSignal {
  trade_date: string
  signal_level: string
  total_score: number
  market_stress_score: number
  support_score: number
  institution_score: number
  weight_support_score: number
  direction: string
  reason: string
  evidence_json: string
  updated_at: string
}

export interface PolicySupportCandidate {
  trade_date: string
  ts_code: string
  name: string
  industry: string
  candidate_type: string
  score: number
  pct_chg: number
  amount_ratio: number
  turnover_rate: number
  institution_net_buy: number
  reason: string
  updated_at: string
}

export async function getLatestPolicySupportSignal(): Promise<PolicySupportSignal | null> {
  if (window.go?.main?.App?.GetLatestPolicySupportSignal) {
    const signal = await window.go.main.App.GetLatestPolicySupportSignal()
    return signal?.trade_date ? signal : null
  }
  return null
}

export async function listPolicySupportCandidates(limit = 80): Promise<PolicySupportCandidate[]> {
  if (window.go?.main?.App?.ListPolicySupportCandidates) {
    return (await window.go.main.App.ListPolicySupportCandidates(limit)) || []
  }
  return []
}

export async function runPolicySupportAnalysis(): Promise<void> {
  if (window.go?.main?.App?.RunPolicySupportAnalysis) {
    await window.go.main.App.RunPolicySupportAnalysis()
  }
}

export async function getPolicySupportAnalysisStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetPolicySupportAnalysisStatus) {
    return window.go.main.App.GetPolicySupportAnalysisStatus()
  }
  return emptyRunStatus('policy_support_analysis')
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
  rows: PositionRecommendationItem[]
}

export interface GenerateSignalRequest {
  date?: string
  initial_cash?: number
  rebalance_freq?: number
  portfolio_run_id?: string
  portfolio_candidate_id?: string
}

export interface GenerateSignalResponse {
  date: string
  output: string
  success: boolean
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
  if (task === 'daily_signal') return 'signal'
  if (task === 'limit_signal_evaluation') return 'evaluation'
  if (task === 'limit_breakout' || task === 'limit_up_momentum' || task === 't0_daily_research' || task === 't0_daily_timemachine') return 'market_scan'
  if (task === 'policy_support_analysis') return 'analysis'
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

export async function refreshPositionRealtimeQuotes(): Promise<PositionSummary> {
  if (window.go?.main?.App?.RefreshPositionRealtimeQuotes) {
    return window.go.main.App.RefreshPositionRealtimeQuotes()
  }
  return getPositionSummary()
}

export async function clearPositionPool(): Promise<PositionSummary> {
  if (window.go?.main?.App?.ClearPositionPool) {
    return window.go.main.App.ClearPositionPool()
  }
  return getPositionSummary()
}

export async function getPositionRecommendation(): Promise<PositionRecommendation> {
  if (window.go?.main?.App?.GetPositionRecommendation) {
    return window.go.main.App.GetPositionRecommendation()
  }
  return { date: '', generated_at: '', total_weight: 0, n_holdings: 0, n_buy: 0, n_sell: 0, rebalanced: false, rebalance_trades: 0, rows: [] }
}

export async function listT0Recommendations(limit = 50): Promise<T0Recommendation[]> {
  if (window.go?.main?.App?.ListT0Recommendations) {
    return (await window.go.main.App.ListT0Recommendations(limit)) || []
  }
  return []
}

export async function listT0DataPullCandidates(limit = 100): Promise<T0DataPullCandidate[]> {
  if (window.go?.main?.App?.ListT0DataPullCandidates) {
    return (await window.go.main.App.ListT0DataPullCandidates(limit)) || []
  }
  return []
}

export async function listT0DailyRuns(limit = 10): Promise<T0DailyRunSummary[]> {
  if (window.go?.main?.App?.ListT0DailyRuns) {
    return (await window.go.main.App.ListT0DailyRuns(limit)) || []
  }
  return []
}

export async function listT0DailyBacktests(limit = 100): Promise<T0DailyBacktest[]> {
  if (window.go?.main?.App?.ListT0DailyBacktests) {
    return (await window.go.main.App.ListT0DailyBacktests(limit)) || []
  }
  return []
}

export async function listT0TimeMachineResults(limit = 100): Promise<T0TimeMachineResult[]> {
  if (window.go?.main?.App?.ListT0TimeMachineResults) {
    return (await window.go.main.App.ListT0TimeMachineResults(limit)) || []
  }
  return []
}

export async function runT0DailyResearch(): Promise<void> {
  const task = await createTask({
    name: '做T模型训练',
    task_type: 'model_training',
    params: { strategy: 't0_daily' }
  })
  await startTask(task.id)
}

export async function runT0TimeMachine(mode: 'quick' | 'deep' = 'quick'): Promise<void> {
  const task = await createTask({
    name: mode === 'quick' ? '做T快速时光机' : '做T深度时光机',
    task_type: 't0_daily_timemachine',
    params: { mode }
  })
  await startTask(task.id)
}

export async function getT0DailyResearchStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetT0DailyResearchStatus) {
    return window.go.main.App.GetT0DailyResearchStatus()
  }
  return emptyRunStatus('t0_daily_research')
}

export async function getT0TimeMachineStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetT0TimeMachineStatus) {
    return window.go.main.App.GetT0TimeMachineStatus()
  }
  return emptyRunStatus('t0_daily_timemachine')
}

export async function generatePositionSignal(req: GenerateSignalRequest = {}): Promise<GenerateSignalResponse> {
  if (window.go?.main?.App?.GeneratePositionSignal) {
    return window.go.main.App.GeneratePositionSignal(req)
  }
  return { date: '', output: '', success: false }
}

export async function cancelPositionSignal(): Promise<RunStatus> {
  if (window.go?.main?.App?.CancelPositionSignal) {
    return window.go.main.App.CancelPositionSignal()
  }
  return emptyRunStatus('daily_signal', { state: 'cancelled', stage: 'cancelled', message: '已取消当日信号生成' })
}

export async function getSignalRunStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetSignalRunStatus) {
    return window.go.main.App.GetSignalRunStatus()
  }
  return emptyRunStatus('daily_signal')
}

export async function getLimitBreakoutRunStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetLimitBreakoutRunStatus) {
    return window.go.main.App.GetLimitBreakoutRunStatus()
  }
  return emptyRunStatus('limit_breakout')
}

export async function clearLimitBreakoutCandidates(): Promise<void> {
  if (window.go?.main?.App?.ClearLimitBreakoutCandidates) {
    return window.go.main.App.ClearLimitBreakoutCandidates()
  }
}

export async function getLimitUpMomentumRunStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetLimitUpMomentumRunStatus) {
    return window.go.main.App.GetLimitUpMomentumRunStatus()
  }
  return emptyRunStatus('limit_up_momentum')
}

export async function clearLimitUpMomentumCandidates(): Promise<void> {
  if (window.go?.main?.App?.ClearLimitUpMomentumCandidates) {
    return window.go.main.App.ClearLimitUpMomentumCandidates()
  }
}

export async function runLimitSignalEvaluation(): Promise<void> {
  const runtimeApp = window.go?.main?.App as any
  const legacyRun = runtimeApp?.RunLimitSignalEvaluation as (() => Promise<void>) | undefined
  if (runtimeApp?.CreateTask && runtimeApp?.StartTask) {
    try {
      const task = await createTask({
        name: '涨停预警历史切面评估',
        task_type: 'limit_signal_evaluation',
        params: {}
      })
      await startTask(task.id)
      return
    } catch (err) {
      if (!legacyRun) throw err
    }
  }
  if (legacyRun) {
    await legacyRun()
    return
  }
  throw new Error('当前桌面运行时缺少涨停评估接口，请重启应用后再试')
}

export async function getLimitSignalEvaluationRunStatus(): Promise<RunStatus> {
  if (window.go?.main?.App?.GetLimitSignalEvaluationRunStatus) {
    return window.go.main.App.GetLimitSignalEvaluationRunStatus()
  }
  return emptyRunStatus('limit_signal_evaluation')
}

export async function listLimitSignalEvaluationSummary(): Promise<LimitSignalEvaluationSummary[]> {
  if (window.go?.main?.App?.ListLimitSignalEvaluationSummary) {
    return (await window.go.main.App.ListLimitSignalEvaluationSummary()) || []
  }
  return []
}

export async function listLimitSignalTimeMachineSlices(limit = 80): Promise<LimitSignalTimeMachineSlice[]> {
  if (window.go?.main?.App?.ListLimitSignalTimeMachineSlices) {
    return (await window.go.main.App.ListLimitSignalTimeMachineSlices(limit)) || []
  }
  return []
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
    { key: 'mysql', name: 'MySQL 数据库', category: '基础设施', state: 'ready', latency_ms: 2, message: '开发模式占位', checked_at: checkedAt },
    { key: 'tushare', name: 'Tushare 数据接口', category: '行情/财务数据', state: 'missing', latency_ms: 0, message: '桌面端连接后检测', checked_at: checkedAt },
    { key: 'llm', name: 'ChatGPT/OpenAI 模型接口', category: 'AI 调参/复盘', state: 'missing', latency_ms: 0, message: '桌面端连接后检测', checked_at: checkedAt },
    { key: 'realtime_quote', name: '实时行情接口', category: '实时价格', state: 'ready', latency_ms: 180, message: '开发模式占位', checked_at: checkedAt },
    { key: 'wechat', name: '企业微信机器人', category: '通知', state: 'missing', latency_ms: 0, message: '桌面端连接后检测', checked_at: checkedAt },
  ]
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
    parent_id: '',
    group_run_id: '',
    subtask_key: '',
    subtask_name: '',
    sequence: 0,
    total: 0,
    attempt: 0,
    max_attempts: 1,
    created_at: now,
    queued_at: '',
    started_at: '',
    finished_at: '',
    updated_at: now
  }
}

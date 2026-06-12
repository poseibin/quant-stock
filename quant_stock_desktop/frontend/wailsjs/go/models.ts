export namespace config {
	
	export class StrategyScheduleSettings {
	    enabled: boolean;
	    time_of_day: string;
	    weekdays: number[];
	    targets: Record<string, boolean>;
	    wechat_webhook: string;
	    wechat_users: string[];
	
	    static createFrom(source: any = {}) {
	        return new StrategyScheduleSettings(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.enabled = source["enabled"];
	        this.time_of_day = source["time_of_day"];
	        this.weekdays = source["weekdays"];
	        this.targets = source["targets"];
	        this.wechat_webhook = source["wechat_webhook"];
	        this.wechat_users = source["wechat_users"];
	    }
	}
	export class StrategySettings {
	    label: string;
	    enabled: boolean;
	    weight: number;
	    rebalance: string;
	    universe: Record<string, any>;
	    filters: Record<string, any>;
	    selection: Record<string, any>;
	    position: Record<string, any>;
	
	    static createFrom(source: any = {}) {
	        return new StrategySettings(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.label = source["label"];
	        this.enabled = source["enabled"];
	        this.weight = source["weight"];
	        this.rebalance = source["rebalance"];
	        this.universe = source["universe"];
	        this.filters = source["filters"];
	        this.selection = source["selection"];
	        this.position = source["position"];
	    }
	}
	export class Settings {
	    data_path: string;
	    database_backend: string;
	    mysql_dsn: string;
	    default_initial_cash: number;
	    default_rebalance_freq: number;
	    task_concurrency: number;
	    tushare_token: string;
	    deepseek_token: string;
	    deepseek_model: string;
	    strategies: Record<string, StrategySettings>;
	    portfolio_risk: Record<string, any>;
	    exit_rules: Record<string, any>;
	    governance_rules: Record<string, any>;
	    strategy_schedule: StrategyScheduleSettings;
	
	    static createFrom(source: any = {}) {
	        return new Settings(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.data_path = source["data_path"];
	        this.database_backend = source["database_backend"];
	        this.mysql_dsn = source["mysql_dsn"];
	        this.default_initial_cash = source["default_initial_cash"];
	        this.default_rebalance_freq = source["default_rebalance_freq"];
	        this.task_concurrency = source["task_concurrency"];
	        this.tushare_token = source["tushare_token"];
	        this.deepseek_token = source["deepseek_token"];
	        this.deepseek_model = source["deepseek_model"];
	        this.strategies = this.convertValues(source["strategies"], StrategySettings, true);
	        this.portfolio_risk = source["portfolio_risk"];
	        this.exit_rules = source["exit_rules"];
	        this.governance_rules = source["governance_rules"];
	        this.strategy_schedule = this.convertValues(source["strategy_schedule"], StrategyScheduleSettings);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	
	export class ValidationIssue {
	    field: string;
	    message: string;
	
	    static createFrom(source: any = {}) {
	        return new ValidationIssue(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.field = source["field"];
	        this.message = source["message"];
	    }
	}

}

export namespace datafetch {
	
	export class DatasetStatus {
	    dataset: string;
	    category: string;
	    state: string;
	    progress_done: number;
	    progress_total: number;
	    message: string;
	    rows_written: number;
	    error_message: string;
	    started_at: string;
	    finished_at: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new DatasetStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.dataset = source["dataset"];
	        this.category = source["category"];
	        this.state = source["state"];
	        this.progress_done = source["progress_done"];
	        this.progress_total = source["progress_total"];
	        this.message = source["message"];
	        this.rows_written = source["rows_written"];
	        this.error_message = source["error_message"];
	        this.started_at = source["started_at"];
	        this.finished_at = source["finished_at"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class RunStatus {
	    task: string;
	    task_type: string;
	    state: string;
	    idx: number;
	    total: number;
	    stage: string;
	    name: string;
	    message: string;
	    worker_pid: number;
	    started_at: string;
	    updated_at: string;
	    finished_at: string;
	
	    static createFrom(source: any = {}) {
	        return new RunStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.task = source["task"];
	        this.task_type = source["task_type"];
	        this.state = source["state"];
	        this.idx = source["idx"];
	        this.total = source["total"];
	        this.stage = source["stage"];
	        this.name = source["name"];
	        this.message = source["message"];
	        this.worker_pid = source["worker_pid"];
	        this.started_at = source["started_at"];
	        this.updated_at = source["updated_at"];
	        this.finished_at = source["finished_at"];
	    }
	}
	export class UpdateRequest {
	    phase: string;
	    start_date: string;
	    dataset: string;
	    exclude_datasets: string[];
	
	    static createFrom(source: any = {}) {
	        return new UpdateRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.phase = source["phase"];
	        this.start_date = source["start_date"];
	        this.dataset = source["dataset"];
	        this.exclude_datasets = source["exclude_datasets"];
	    }
	}

}

export namespace main {
	
	export class ActiveStrategyModelRun {
	    strategy: string;
	    run_id: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new ActiveStrategyModelRun(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.strategy = source["strategy"];
	        this.run_id = source["run_id"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class AppInfo {
	    name: string;
	    version: string;
	
	    static createFrom(source: any = {}) {
	        return new AppInfo(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.version = source["version"];
	    }
	}
	export class ApplyPortfolioCandidateRequest {
	    run_id: string;
	    candidate_id: string;
	
	    static createFrom(source: any = {}) {
	        return new ApplyPortfolioCandidateRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.candidate_id = source["candidate_id"];
	    }
	}
	export class CrashWarningFeature {
	    run_id: string;
	    feature: string;
	    importance: number;
	    rank_no: number;
	
	    static createFrom(source: any = {}) {
	        return new CrashWarningFeature(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.feature = source["feature"];
	        this.importance = source["importance"];
	        this.rank_no = source["rank_no"];
	    }
	}
	export class CrashWarningRunSummary {
	    run_id: string;
	    model_type: string;
	    start_date: string;
	    end_date: string;
	    horizon: number;
	    feature_count: number;
	    status: string;
	    model_path: string;
	    rows: number;
	    positive_rate: number;
	    roc_auc: number;
	    avg_precision: number;
	    top10_precision: number;
	    top10_capture: number;
	    p90_precision: number;
	    p90_recall: number;
	    summary_json: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new CrashWarningRunSummary(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.model_type = source["model_type"];
	        this.start_date = source["start_date"];
	        this.end_date = source["end_date"];
	        this.horizon = source["horizon"];
	        this.feature_count = source["feature_count"];
	        this.status = source["status"];
	        this.model_path = source["model_path"];
	        this.rows = source["rows"];
	        this.positive_rate = source["positive_rate"];
	        this.roc_auc = source["roc_auc"];
	        this.avg_precision = source["avg_precision"];
	        this.top10_precision = source["top10_precision"];
	        this.top10_capture = source["top10_capture"];
	        this.p90_precision = source["p90_precision"];
	        this.p90_recall = source["p90_recall"];
	        this.summary_json = source["summary_json"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class DataSnapshotDTO {
	    id: string;
	    subject_type: string;
	    subject_id: string;
	    snapshot: Record<string, any>;
	    created_at: string;
	
	    static createFrom(source: any = {}) {
	        return new DataSnapshotDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.subject_type = source["subject_type"];
	        this.subject_id = source["subject_id"];
	        this.snapshot = source["snapshot"];
	        this.created_at = source["created_at"];
	    }
	}
	export class ExternalDependencyStatus {
	    key: string;
	    name: string;
	    category: string;
	    state: string;
	    latency_ms: number;
	    message: string;
	    checked_at: string;
	
	    static createFrom(source: any = {}) {
	        return new ExternalDependencyStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.key = source["key"];
	        this.name = source["name"];
	        this.category = source["category"];
	        this.state = source["state"];
	        this.latency_ms = source["latency_ms"];
	        this.message = source["message"];
	        this.checked_at = source["checked_at"];
	    }
	}
	export class FactorAdmissionComparison {
	    run_id: string;
	    strategy: string;
	    admission: string;
	    admission_score: number;
	    reason: string;
	    annual_return: number;
	    total_return: number;
	    max_drawdown: number;
	    sharpe: number;
	    avg_turnover: number;
	    effective_start: string;
	    effective_end: string;
	    stress_penalty: number;
	    stress_bad_event_count: number;
	    stress_crash_state_failed: boolean;
	    stress_weak_drawdown_failed: boolean;
	    generated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new FactorAdmissionComparison(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.strategy = source["strategy"];
	        this.admission = source["admission"];
	        this.admission_score = source["admission_score"];
	        this.reason = source["reason"];
	        this.annual_return = source["annual_return"];
	        this.total_return = source["total_return"];
	        this.max_drawdown = source["max_drawdown"];
	        this.sharpe = source["sharpe"];
	        this.avg_turnover = source["avg_turnover"];
	        this.effective_start = source["effective_start"];
	        this.effective_end = source["effective_end"];
	        this.stress_penalty = source["stress_penalty"];
	        this.stress_bad_event_count = source["stress_bad_event_count"];
	        this.stress_crash_state_failed = source["stress_crash_state_failed"];
	        this.stress_weak_drawdown_failed = source["stress_weak_drawdown_failed"];
	        this.generated_at = source["generated_at"];
	    }
	}
	export class FactorAutoTuneRun {
	    run_id: string;
	    base_model_run_id: string;
	    start_date: string;
	    end_date: string;
	    status: string;
	    best_trial_id: string;
	    best_model_run_id: string;
	    best_admission: string;
	    best_score: number;
	    summary_json: string;
	    created_at: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new FactorAutoTuneRun(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.base_model_run_id = source["base_model_run_id"];
	        this.start_date = source["start_date"];
	        this.end_date = source["end_date"];
	        this.status = source["status"];
	        this.best_trial_id = source["best_trial_id"];
	        this.best_model_run_id = source["best_model_run_id"];
	        this.best_admission = source["best_admission"];
	        this.best_score = source["best_score"];
	        this.summary_json = source["summary_json"];
	        this.created_at = source["created_at"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class FactorAutoTuneTrial {
	    run_id: string;
	    trial_id: string;
	    round_no: number;
	    source: string;
	    model_run_id: string;
	    eval_run_id: string;
	    params_json: string;
	    llm_direction_json: string;
	    admission: string;
	    admission_score: number;
	    reason: string;
	    annual_return: number;
	    total_return: number;
	    max_drawdown: number;
	    sharpe: number;
	    stress_bad_event_count: number;
	    stress_crash_state_failed: boolean;
	    stress_weak_drawdown_failed: boolean;
	    passed: boolean;
	    created_at: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new FactorAutoTuneTrial(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.trial_id = source["trial_id"];
	        this.round_no = source["round_no"];
	        this.source = source["source"];
	        this.model_run_id = source["model_run_id"];
	        this.eval_run_id = source["eval_run_id"];
	        this.params_json = source["params_json"];
	        this.llm_direction_json = source["llm_direction_json"];
	        this.admission = source["admission"];
	        this.admission_score = source["admission_score"];
	        this.reason = source["reason"];
	        this.annual_return = source["annual_return"];
	        this.total_return = source["total_return"];
	        this.max_drawdown = source["max_drawdown"];
	        this.sharpe = source["sharpe"];
	        this.stress_bad_event_count = source["stress_bad_event_count"];
	        this.stress_crash_state_failed = source["stress_crash_state_failed"];
	        this.stress_weak_drawdown_failed = source["stress_weak_drawdown_failed"];
	        this.passed = source["passed"];
	        this.created_at = source["created_at"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class FactorCorrelationResult {
	    run_id: string;
	    feature_a: string;
	    feature_b: string;
	    correlation: number;
	    abs_correlation: number;
	    family_a: string;
	    family_b: string;
	    keep_feature: string;
	    drop_feature: string;
	    reason: string;
	
	    static createFrom(source: any = {}) {
	        return new FactorCorrelationResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.feature_a = source["feature_a"];
	        this.feature_b = source["feature_b"];
	        this.correlation = source["correlation"];
	        this.abs_correlation = source["abs_correlation"];
	        this.family_a = source["family_a"];
	        this.family_b = source["family_b"];
	        this.keep_feature = source["keep_feature"];
	        this.drop_feature = source["drop_feature"];
	        this.reason = source["reason"];
	    }
	}
	export class FactorICResult {
	    run_id: string;
	    factor: string;
	    family: string;
	    variant: string;
	    horizon: string;
	    ic_mean: number;
	    rank_ic_mean: number;
	    ic_win_rate: number;
	    icir: number;
	    status: string;
	    long_short_return: number;
	    monotonic_score: number;
	
	    static createFrom(source: any = {}) {
	        return new FactorICResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.factor = source["factor"];
	        this.family = source["family"];
	        this.variant = source["variant"];
	        this.horizon = source["horizon"];
	        this.ic_mean = source["ic_mean"];
	        this.rank_ic_mean = source["rank_ic_mean"];
	        this.ic_win_rate = source["ic_win_rate"];
	        this.icir = source["icir"];
	        this.status = source["status"];
	        this.long_short_return = source["long_short_return"];
	        this.monotonic_score = source["monotonic_score"];
	    }
	}
	export class FactorLatestPrediction {
	    run_id: string;
	    trade_date: string;
	    ts_code: string;
	    name: string;
	    industry: string;
	    price: number;
	    pct_chg: number;
	    pred_score: number;
	    pred_rank: number;
	    is_top20: boolean;
	    model_path: string;
	    first_seen_date: string;
	    last_seen_date: string;
	    seen_count: number;
	    observation_days: number;
	    observation_status: string;
	    observation_reason: string;
	    observation_result: string;
	
	    static createFrom(source: any = {}) {
	        return new FactorLatestPrediction(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.trade_date = source["trade_date"];
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.price = source["price"];
	        this.pct_chg = source["pct_chg"];
	        this.pred_score = source["pred_score"];
	        this.pred_rank = source["pred_rank"];
	        this.is_top20 = source["is_top20"];
	        this.model_path = source["model_path"];
	        this.first_seen_date = source["first_seen_date"];
	        this.last_seen_date = source["last_seen_date"];
	        this.seen_count = source["seen_count"];
	        this.observation_days = source["observation_days"];
	        this.observation_status = source["observation_status"];
	        this.observation_reason = source["observation_reason"];
	        this.observation_result = source["observation_result"];
	    }
	}
	export class FactorModelFeature {
	    run_id: string;
	    feature: string;
	    importance: number;
	    rank_no: number;
	    summary_json: string;
	
	    static createFrom(source: any = {}) {
	        return new FactorModelFeature(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.feature = source["feature"];
	        this.importance = source["importance"];
	        this.rank_no = source["rank_no"];
	        this.summary_json = source["summary_json"];
	    }
	}
	export class FactorModelPrediction {
	    run_id: string;
	    trade_date: string;
	    ts_code: string;
	    pred_score: number;
	    realized_return: number;
	    pred_rank: number;
	    test_year: number;
	
	    static createFrom(source: any = {}) {
	        return new FactorModelPrediction(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.trade_date = source["trade_date"];
	        this.ts_code = source["ts_code"];
	        this.pred_score = source["pred_score"];
	        this.realized_return = source["realized_return"];
	        this.pred_rank = source["pred_rank"];
	        this.test_year = source["test_year"];
	    }
	}
	export class FactorModelRun {
	    run_id: string;
	    model_type: string;
	    label: string;
	    feature_count: number;
	    status: string;
	    model_path: string;
	    rank_ic: number;
	    top_bottom_spread: number;
	    summary_json: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new FactorModelRun(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.model_type = source["model_type"];
	        this.label = source["label"];
	        this.feature_count = source["feature_count"];
	        this.status = source["status"];
	        this.model_path = source["model_path"];
	        this.rank_ic = source["rank_ic"];
	        this.top_bottom_spread = source["top_bottom_spread"];
	        this.summary_json = source["summary_json"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class FactorObservationEvent {
	    strategy: string;
	    run_id: string;
	    trade_date: string;
	    ts_code: string;
	    name: string;
	    industry: string;
	    event_type: string;
	    rank_no: number;
	    score: number;
	    rank_pct: number;
	    reason: string;
	    first_seen_date: string;
	    last_seen_date: string;
	    seen_count: number;
	    observation_status: string;
	    created_at: string;
	
	    static createFrom(source: any = {}) {
	        return new FactorObservationEvent(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.strategy = source["strategy"];
	        this.run_id = source["run_id"];
	        this.trade_date = source["trade_date"];
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.event_type = source["event_type"];
	        this.rank_no = source["rank_no"];
	        this.score = source["score"];
	        this.rank_pct = source["rank_pct"];
	        this.reason = source["reason"];
	        this.first_seen_date = source["first_seen_date"];
	        this.last_seen_date = source["last_seen_date"];
	        this.seen_count = source["seen_count"];
	        this.observation_status = source["observation_status"];
	        this.created_at = source["created_at"];
	    }
	}
	export class FactorResearchRunSummary {
	    run_id: string;
	    start_date: string;
	    end_date: string;
	    freq: string;
	    label: string;
	    status: string;
	    factor_count: number;
	    sample_dates: number;
	    sample_rows: number;
	    panel_path: string;
	    updated_at: string;
	    model_status: string;
	    rank_ic: number;
	
	    static createFrom(source: any = {}) {
	        return new FactorResearchRunSummary(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.start_date = source["start_date"];
	        this.end_date = source["end_date"];
	        this.freq = source["freq"];
	        this.label = source["label"];
	        this.status = source["status"];
	        this.factor_count = source["factor_count"];
	        this.sample_dates = source["sample_dates"];
	        this.sample_rows = source["sample_rows"];
	        this.panel_path = source["panel_path"];
	        this.updated_at = source["updated_at"];
	        this.model_status = source["model_status"];
	        this.rank_ic = source["rank_ic"];
	    }
	}
	export class FactorStateICResult {
	    run_id: string;
	    factor: string;
	    family: string;
	    variant: string;
	    horizon: string;
	    market_state: string;
	    rank_ic_mean: number;
	    ic_win_rate: number;
	    icir: number;
	    n_periods: number;
	    n_obs: number;
	    status: string;
	    summary_json: string;
	
	    static createFrom(source: any = {}) {
	        return new FactorStateICResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.factor = source["factor"];
	        this.family = source["family"];
	        this.variant = source["variant"];
	        this.horizon = source["horizon"];
	        this.market_state = source["market_state"];
	        this.rank_ic_mean = source["rank_ic_mean"];
	        this.ic_win_rate = source["ic_win_rate"];
	        this.icir = source["icir"];
	        this.n_periods = source["n_periods"];
	        this.n_obs = source["n_obs"];
	        this.status = source["status"];
	        this.summary_json = source["summary_json"];
	    }
	}
	export class FactorStressResult {
	    run_id: string;
	    bucket_type: string;
	    bucket_key: string;
	    bucket_label: string;
	    start_date: string;
	    end_date: string;
	    n_days: number;
	    total_return: number;
	    annual_return: number;
	    max_drawdown: number;
	    sharpe: number;
	    win_rate: number;
	    avg_daily_return: number;
	    volatility: number;
	    summary_json: string;
	
	    static createFrom(source: any = {}) {
	        return new FactorStressResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.bucket_type = source["bucket_type"];
	        this.bucket_key = source["bucket_key"];
	        this.bucket_label = source["bucket_label"];
	        this.start_date = source["start_date"];
	        this.end_date = source["end_date"];
	        this.n_days = source["n_days"];
	        this.total_return = source["total_return"];
	        this.annual_return = source["annual_return"];
	        this.max_drawdown = source["max_drawdown"];
	        this.sharpe = source["sharpe"];
	        this.win_rate = source["win_rate"];
	        this.avg_daily_return = source["avg_daily_return"];
	        this.volatility = source["volatility"];
	        this.summary_json = source["summary_json"];
	    }
	}
	export class ResearchReportDTO {
	    id: string;
	    subject_type: string;
	    subject_id: string;
	    report_type: string;
	    title: string;
	    model: string;
	    content_md: string;
	    payload: Record<string, any>;
	    created_at: string;
	
	    static createFrom(source: any = {}) {
	        return new ResearchReportDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.subject_type = source["subject_type"];
	        this.subject_id = source["subject_id"];
	        this.report_type = source["report_type"];
	        this.title = source["title"];
	        this.model = source["model"];
	        this.content_md = source["content_md"];
	        this.payload = source["payload"];
	        this.created_at = source["created_at"];
	    }
	}
	export class ParameterExperimentDTO {
	    id: string;
	    strategy: string;
	    strategy_version: number;
	    param_set: string;
	    status: string;
	    score: number;
	    params: Record<string, any>;
	    metrics: Record<string, any>;
	    created_at: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new ParameterExperimentDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.strategy = source["strategy"];
	        this.strategy_version = source["strategy_version"];
	        this.param_set = source["param_set"];
	        this.status = source["status"];
	        this.score = source["score"];
	        this.params = source["params"];
	        this.metrics = source["metrics"];
	        this.created_at = source["created_at"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class WalkForwardWindowDTO {
	    id: string;
	    subject_type: string;
	    subject_id: string;
	    window_name: string;
	    start_date: string;
	    end_date: string;
	    status: string;
	    score: number;
	    metrics: Record<string, any>;
	    created_at: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new WalkForwardWindowDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.subject_type = source["subject_type"];
	        this.subject_id = source["subject_id"];
	        this.window_name = source["window_name"];
	        this.start_date = source["start_date"];
	        this.end_date = source["end_date"];
	        this.status = source["status"];
	        this.score = source["score"];
	        this.metrics = source["metrics"];
	        this.created_at = source["created_at"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class PromotionDecisionDTO {
	    id: string;
	    strategy: string;
	    strategy_version: number;
	    current_status: string;
	    recommended_status: string;
	    score: number;
	    reason: string;
	    payload: Record<string, any>;
	    created_at: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new PromotionDecisionDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.strategy = source["strategy"];
	        this.strategy_version = source["strategy_version"];
	        this.current_status = source["current_status"];
	        this.recommended_status = source["recommended_status"];
	        this.score = source["score"];
	        this.reason = source["reason"];
	        this.payload = source["payload"];
	        this.created_at = source["created_at"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class PaperTradingLogDTO {
	    id: string;
	    signal_date: string;
	    ts_code: string;
	    name: string;
	    action: string;
	    target_weight: number;
	    actual_weight?: number;
	    status: string;
	    reason: string;
	    payload: Record<string, any>;
	    created_at: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new PaperTradingLogDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.signal_date = source["signal_date"];
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.action = source["action"];
	        this.target_weight = source["target_weight"];
	        this.actual_weight = source["actual_weight"];
	        this.status = source["status"];
	        this.reason = source["reason"];
	        this.payload = source["payload"];
	        this.created_at = source["created_at"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class RiskExposureDTO {
	    id: string;
	    subject_type: string;
	    subject_id: string;
	    as_of_date: string;
	    n_holdings: number;
	    total_weight: number;
	    max_single_weight: number;
	    top5_weight: number;
	    industry: Record<string, any>;
	    strategy: Record<string, any>;
	    payload: Record<string, any>;
	    created_at: string;
	
	    static createFrom(source: any = {}) {
	        return new RiskExposureDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.subject_type = source["subject_type"];
	        this.subject_id = source["subject_id"];
	        this.as_of_date = source["as_of_date"];
	        this.n_holdings = source["n_holdings"];
	        this.total_weight = source["total_weight"];
	        this.max_single_weight = source["max_single_weight"];
	        this.top5_weight = source["top5_weight"];
	        this.industry = source["industry"];
	        this.strategy = source["strategy"];
	        this.payload = source["payload"];
	        this.created_at = source["created_at"];
	    }
	}
	export class RecommendationHindsightDTO {
	    id: string;
	    recommendation_date: string;
	    horizon_days: number;
	    next_date: string;
	    n_holdings: number;
	    n_eval: number;
	    weighted_return?: number;
	    equal_weight_return?: number;
	    hit_rate?: number;
	    payload: Record<string, any>;
	    created_at: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new RecommendationHindsightDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.recommendation_date = source["recommendation_date"];
	        this.horizon_days = source["horizon_days"];
	        this.next_date = source["next_date"];
	        this.n_holdings = source["n_holdings"];
	        this.n_eval = source["n_eval"];
	        this.weighted_return = source["weighted_return"];
	        this.equal_weight_return = source["equal_weight_return"];
	        this.hit_rate = source["hit_rate"];
	        this.payload = source["payload"];
	        this.created_at = source["created_at"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class GovernanceDashboardDTO {
	    hindsight: RecommendationHindsightDTO[];
	    risk: RiskExposureDTO[];
	    paper: PaperTradingLogDTO[];
	    promotion: PromotionDecisionDTO[];
	    walk: WalkForwardWindowDTO[];
	    params: ParameterExperimentDTO[];
	    data_quality: Record<string, any>;
	    parameter_recommendations: any[];
	    retirement: any[];
	    portfolio_attribution: any[];
	    recovery: Record<string, any>;
	    reports: ResearchReportDTO[];
	
	    static createFrom(source: any = {}) {
	        return new GovernanceDashboardDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.hindsight = this.convertValues(source["hindsight"], RecommendationHindsightDTO);
	        this.risk = this.convertValues(source["risk"], RiskExposureDTO);
	        this.paper = this.convertValues(source["paper"], PaperTradingLogDTO);
	        this.promotion = this.convertValues(source["promotion"], PromotionDecisionDTO);
	        this.walk = this.convertValues(source["walk"], WalkForwardWindowDTO);
	        this.params = this.convertValues(source["params"], ParameterExperimentDTO);
	        this.data_quality = source["data_quality"];
	        this.parameter_recommendations = source["parameter_recommendations"];
	        this.retirement = source["retirement"];
	        this.portfolio_attribution = source["portfolio_attribution"];
	        this.recovery = source["recovery"];
	        this.reports = this.convertValues(source["reports"], ResearchReportDTO);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class LimitUpModelFeature {
	    run_id: string;
	    feature: string;
	    importance: number;
	    rank_no: number;
	
	    static createFrom(source: any = {}) {
	        return new LimitUpModelFeature(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.feature = source["feature"];
	        this.importance = source["importance"];
	        this.rank_no = source["rank_no"];
	    }
	}
	export class LimitUpModelPrediction {
	    run_id: string;
	    trade_date: string;
	    ts_code: string;
	    name: string;
	    industry: string;
	    price: number;
	    high: number;
	    low: number;
	    today_pct: number;
	    prob: number;
	    model_score: number;
	    label: number;
	    fwd5_return: number;
	    fwd5_max_return: number;
	    max_drawdown_5d: number;
	    hit_limit_up_5d: number;
	    is_latest: boolean;
	    summary_json: string;
	    updated_at: string;
	    first_seen_date: string;
	    last_seen_date: string;
	    seen_count: number;
	    observation_days: number;
	    observation_status: string;
	    observation_reason: string;
	    observation_result: string;
	
	    static createFrom(source: any = {}) {
	        return new LimitUpModelPrediction(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.trade_date = source["trade_date"];
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.price = source["price"];
	        this.high = source["high"];
	        this.low = source["low"];
	        this.today_pct = source["today_pct"];
	        this.prob = source["prob"];
	        this.model_score = source["model_score"];
	        this.label = source["label"];
	        this.fwd5_return = source["fwd5_return"];
	        this.fwd5_max_return = source["fwd5_max_return"];
	        this.max_drawdown_5d = source["max_drawdown_5d"];
	        this.hit_limit_up_5d = source["hit_limit_up_5d"];
	        this.is_latest = source["is_latest"];
	        this.summary_json = source["summary_json"];
	        this.updated_at = source["updated_at"];
	        this.first_seen_date = source["first_seen_date"];
	        this.last_seen_date = source["last_seen_date"];
	        this.seen_count = source["seen_count"];
	        this.observation_days = source["observation_days"];
	        this.observation_status = source["observation_status"];
	        this.observation_reason = source["observation_reason"];
	        this.observation_result = source["observation_result"];
	    }
	}
	export class LimitUpModelRunSummary {
	    run_id: string;
	    start_date: string;
	    end_date: string;
	    horizon: number;
	    model_type: string;
	    feature_count: number;
	    status: string;
	    model_path: string;
	    rows: number;
	    candidate_rows: number;
	    latest_date: string;
	    latest_count: number;
	    positive_rate: number;
	    baseline_return: number;
	    top_return: number;
	    top_excess_return: number;
	    top_hit_rate: number;
	    top_limit_up_rate: number;
	    top_drawdown: number;
	    rank_ic: number;
	    summary_json: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new LimitUpModelRunSummary(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.start_date = source["start_date"];
	        this.end_date = source["end_date"];
	        this.horizon = source["horizon"];
	        this.model_type = source["model_type"];
	        this.feature_count = source["feature_count"];
	        this.status = source["status"];
	        this.model_path = source["model_path"];
	        this.rows = source["rows"];
	        this.candidate_rows = source["candidate_rows"];
	        this.latest_date = source["latest_date"];
	        this.latest_count = source["latest_count"];
	        this.positive_rate = source["positive_rate"];
	        this.baseline_return = source["baseline_return"];
	        this.top_return = source["top_return"];
	        this.top_excess_return = source["top_excess_return"];
	        this.top_hit_rate = source["top_hit_rate"];
	        this.top_limit_up_rate = source["top_limit_up_rate"];
	        this.top_drawdown = source["top_drawdown"];
	        this.rank_ic = source["rank_ic"];
	        this.summary_json = source["summary_json"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class LimitUpModelTimeMachineSlice {
	    run_id: string;
	    trade_date: string;
	    candidate_count: number;
	    top_count: number;
	    avg_return: number;
	    avg_max_return: number;
	    hit_rate: number;
	    limit_up_hit_rate: number;
	    avg_drawdown: number;
	    rank_ic: number;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new LimitUpModelTimeMachineSlice(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.trade_date = source["trade_date"];
	        this.candidate_count = source["candidate_count"];
	        this.top_count = source["top_count"];
	        this.avg_return = source["avg_return"];
	        this.avg_max_return = source["avg_max_return"];
	        this.hit_rate = source["hit_rate"];
	        this.limit_up_hit_rate = source["limit_up_hit_rate"];
	        this.avg_drawdown = source["avg_drawdown"];
	        this.rank_ic = source["rank_ic"];
	        this.updated_at = source["updated_at"];
	    }
	}
	
	
	export class PolicySupportCandidateDTO {
	    trade_date: string;
	    ts_code: string;
	    name: string;
	    industry: string;
	    candidate_type: string;
	    score: number;
	    pct_chg: number;
	    amount_ratio: number;
	    turnover_rate: number;
	    institution_net_buy: number;
	    reason: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new PolicySupportCandidateDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.trade_date = source["trade_date"];
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.candidate_type = source["candidate_type"];
	        this.score = source["score"];
	        this.pct_chg = source["pct_chg"];
	        this.amount_ratio = source["amount_ratio"];
	        this.turnover_rate = source["turnover_rate"];
	        this.institution_net_buy = source["institution_net_buy"];
	        this.reason = source["reason"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class PolicySupportSignalDTO {
	    trade_date: string;
	    signal_level: string;
	    total_score: number;
	    market_stress_score: number;
	    support_score: number;
	    institution_score: number;
	    weight_support_score: number;
	    direction: string;
	    reason: string;
	    evidence_json: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new PolicySupportSignalDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.trade_date = source["trade_date"];
	        this.signal_level = source["signal_level"];
	        this.total_score = source["total_score"];
	        this.market_stress_score = source["market_stress_score"];
	        this.support_score = source["support_score"];
	        this.institution_score = source["institution_score"];
	        this.weight_support_score = source["weight_support_score"];
	        this.direction = source["direction"];
	        this.reason = source["reason"];
	        this.evidence_json = source["evidence_json"];
	        this.updated_at = source["updated_at"];
	    }
	}
	
	
	
	
	export class SettingsResponse {
	    settings: config.Settings;
	    issues: config.ValidationIssue[];
	
	    static createFrom(source: any = {}) {
	        return new SettingsResponse(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.settings = this.convertValues(source["settings"], config.Settings);
	        this.issues = this.convertValues(source["issues"], config.ValidationIssue);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class SignalPortfolioCandidateDTO {
	    run_id: string;
	    candidate_id: string;
	    rank: number;
	    name: string;
	    objective: string;
	    status: string;
	    score: number;
	    strategies: string;
	    weights: Record<string, number>;
	    annual_return?: number;
	    max_drawdown?: number;
	    sharpe?: number;
	    calmar?: number;
	    avg_turnover?: number;
	    avg_holdings?: number;
	    rebalance_freq: number;
	    validation_status: string;
	    reason: string;
	    updated_at: string;
	    is_active: boolean;
	
	    static createFrom(source: any = {}) {
	        return new SignalPortfolioCandidateDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.candidate_id = source["candidate_id"];
	        this.rank = source["rank"];
	        this.name = source["name"];
	        this.objective = source["objective"];
	        this.status = source["status"];
	        this.score = source["score"];
	        this.strategies = source["strategies"];
	        this.weights = source["weights"];
	        this.annual_return = source["annual_return"];
	        this.max_drawdown = source["max_drawdown"];
	        this.sharpe = source["sharpe"];
	        this.calmar = source["calmar"];
	        this.avg_turnover = source["avg_turnover"];
	        this.avg_holdings = source["avg_holdings"];
	        this.rebalance_freq = source["rebalance_freq"];
	        this.validation_status = source["validation_status"];
	        this.reason = source["reason"];
	        this.updated_at = source["updated_at"];
	        this.is_active = source["is_active"];
	    }
	}
	export class activePortfolioCandidateRecord {
	    run_id: string;
	    candidate_id: string;
	    name: string;
	    status: string;
	    score: number;
	    weights: Record<string, number>;
	    validation_status: string;
	    applied_at: string;
	
	    static createFrom(source: any = {}) {
	        return new activePortfolioCandidateRecord(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.candidate_id = source["candidate_id"];
	        this.name = source["name"];
	        this.status = source["status"];
	        this.score = source["score"];
	        this.weights = source["weights"];
	        this.validation_status = source["validation_status"];
	        this.applied_at = source["applied_at"];
	    }
	}
	export class SignalPortfolioContextDTO {
	    active?: activePortfolioCandidateRecord;
	    candidates: SignalPortfolioCandidateDTO[];
	    can_generate: boolean;
	    blocked_reason: string;
	
	    static createFrom(source: any = {}) {
	        return new SignalPortfolioContextDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.active = this.convertValues(source["active"], activePortfolioCandidateRecord);
	        this.candidates = this.convertValues(source["candidates"], SignalPortfolioCandidateDTO);
	        this.can_generate = source["can_generate"];
	        this.blocked_reason = source["blocked_reason"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class StrategyModelRunRequest {
	    strategy: string;
	    run_id: string;
	
	    static createFrom(source: any = {}) {
	        return new StrategyModelRunRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.strategy = source["strategy"];
	        this.run_id = source["run_id"];
	    }
	}
	export class StrategyScheduleReportRow {
	    target: string;
	    label: string;
	    status: string;
	    message: string;
	
	    static createFrom(source: any = {}) {
	        return new StrategyScheduleReportRow(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.target = source["target"];
	        this.label = source["label"];
	        this.status = source["status"];
	        this.message = source["message"];
	    }
	}
	export class StrategyScheduleReport {
	    started_at: string;
	    finished_at: string;
	    success: boolean;
	    message: string;
	    wechat_content: string;
	    rows: StrategyScheduleReportRow[];
	    recommendation: position.Recommendation;
	
	    static createFrom(source: any = {}) {
	        return new StrategyScheduleReport(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.started_at = source["started_at"];
	        this.finished_at = source["finished_at"];
	        this.success = source["success"];
	        this.message = source["message"];
	        this.wechat_content = source["wechat_content"];
	        this.rows = this.convertValues(source["rows"], StrategyScheduleReportRow);
	        this.recommendation = this.convertValues(source["recommendation"], position.Recommendation);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	export class StrategyVersionActivateRequest {
	    strategy: string;
	    version: number;
	
	    static createFrom(source: any = {}) {
	        return new StrategyVersionActivateRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.strategy = source["strategy"];
	        this.version = source["version"];
	    }
	}
	export class StrategyVersionDTO {
	    strategy: string;
	    version: number;
	    label: string;
	    config: Record<string, any>;
	    is_active: boolean;
	    promotion_status: string;
	    validation: Record<string, any>;
	    source: string;
	    note: string;
	    created_at: string;
	    activated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new StrategyVersionDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.strategy = source["strategy"];
	        this.version = source["version"];
	        this.label = source["label"];
	        this.config = source["config"];
	        this.is_active = source["is_active"];
	        this.promotion_status = source["promotion_status"];
	        this.validation = source["validation"];
	        this.source = source["source"];
	        this.note = source["note"];
	        this.created_at = source["created_at"];
	        this.activated_at = source["activated_at"];
	    }
	}
	export class StrategyVersionStatusRequest {
	    strategy: string;
	    version: number;
	    status: string;
	
	    static createFrom(source: any = {}) {
	        return new StrategyVersionStatusRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.strategy = source["strategy"];
	        this.version = source["version"];
	        this.status = source["status"];
	    }
	}
	export class T0DailyBacktest {
	    run_id: string;
	    ts_code: string;
	    name: string;
	    industry: string;
	    n_days: number;
	    n_candidates: number;
	    two_sided_rate: number;
	    one_sided_rate: number;
	    avg_edge: number;
	    total_edge: number;
	    avg_next_range: number;
	    score: number;
	    summary_json: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new T0DailyBacktest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.n_days = source["n_days"];
	        this.n_candidates = source["n_candidates"];
	        this.two_sided_rate = source["two_sided_rate"];
	        this.one_sided_rate = source["one_sided_rate"];
	        this.avg_edge = source["avg_edge"];
	        this.total_edge = source["total_edge"];
	        this.avg_next_range = source["avg_next_range"];
	        this.score = source["score"];
	        this.summary_json = source["summary_json"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class T0DailyRunSummary {
	    run_id: string;
	    trade_date: string;
	    status: string;
	    candidate_count: number;
	    backtest_count: number;
	    summary_json: string;
	    created_at: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new T0DailyRunSummary(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.trade_date = source["trade_date"];
	        this.status = source["status"];
	        this.candidate_count = source["candidate_count"];
	        this.backtest_count = source["backtest_count"];
	        this.summary_json = source["summary_json"];
	        this.created_at = source["created_at"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class T0DataPullCandidate {
	    ts_code: string;
	    name: string;
	    industry: string;
	    trade_date: string;
	    action: string;
	    score: number;
	    state: string;
	    setup: string;
	    first_action: string;
	    price: number;
	    reduce_price: number;
	    buy_price: number;
	    stop_price: number;
	    t_ratio: number;
	    today_pct: number;
	    return_5d: number;
	    return_20d: number;
	    avg_range_20d: number;
	    drawdown_20d: number;
	    amount: number;
	    avg_amount_20d: number;
	    expected_edge: number;
	    target_freq: string;
	    lookback_days: number;
	    plan_json: string;
	    reasons: string[];
	    risks: string[];
	    generated_at: string;
	    first_seen_date: string;
	    last_seen_date: string;
	    seen_count: number;
	    observation_days: number;
	    observation_status: string;
	    observation_reason: string;
	    observation_result: string;
	
	    static createFrom(source: any = {}) {
	        return new T0DataPullCandidate(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.trade_date = source["trade_date"];
	        this.action = source["action"];
	        this.score = source["score"];
	        this.state = source["state"];
	        this.setup = source["setup"];
	        this.first_action = source["first_action"];
	        this.price = source["price"];
	        this.reduce_price = source["reduce_price"];
	        this.buy_price = source["buy_price"];
	        this.stop_price = source["stop_price"];
	        this.t_ratio = source["t_ratio"];
	        this.today_pct = source["today_pct"];
	        this.return_5d = source["return_5d"];
	        this.return_20d = source["return_20d"];
	        this.avg_range_20d = source["avg_range_20d"];
	        this.drawdown_20d = source["drawdown_20d"];
	        this.amount = source["amount"];
	        this.avg_amount_20d = source["avg_amount_20d"];
	        this.expected_edge = source["expected_edge"];
	        this.target_freq = source["target_freq"];
	        this.lookback_days = source["lookback_days"];
	        this.plan_json = source["plan_json"];
	        this.reasons = source["reasons"];
	        this.risks = source["risks"];
	        this.generated_at = source["generated_at"];
	        this.first_seen_date = source["first_seen_date"];
	        this.last_seen_date = source["last_seen_date"];
	        this.seen_count = source["seen_count"];
	        this.observation_days = source["observation_days"];
	        this.observation_status = source["observation_status"];
	        this.observation_reason = source["observation_reason"];
	        this.observation_result = source["observation_result"];
	    }
	}
	export class T0Recommendation {
	    ts_code: string;
	    name: string;
	    industry: string;
	    trade_date: string;
	    action: string;
	    recommendation: string;
	    score: number;
	    state: string;
	    setup: string;
	    first_action: string;
	    shares: number;
	    max_t0_shares: number;
	    price: number;
	    avg_cost: number;
	    position_weight: number;
	    today_pct: number;
	    return_5d: number;
	    return_20d: number;
	    avg_range_20d: number;
	    drawdown_20d: number;
	    amount: number;
	    buy_back_price: number;
	    reduce_price: number;
	    stop_price: number;
	    t_ratio: number;
	    expected_edge: number;
	    plan_json: string;
	    reasons: string[];
	    risks: string[];
	    generated_at: string;
	    first_seen_date: string;
	    last_seen_date: string;
	    seen_count: number;
	    observation_days: number;
	    observation_status: string;
	    observation_reason: string;
	    observation_result: string;
	
	    static createFrom(source: any = {}) {
	        return new T0Recommendation(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.trade_date = source["trade_date"];
	        this.action = source["action"];
	        this.recommendation = source["recommendation"];
	        this.score = source["score"];
	        this.state = source["state"];
	        this.setup = source["setup"];
	        this.first_action = source["first_action"];
	        this.shares = source["shares"];
	        this.max_t0_shares = source["max_t0_shares"];
	        this.price = source["price"];
	        this.avg_cost = source["avg_cost"];
	        this.position_weight = source["position_weight"];
	        this.today_pct = source["today_pct"];
	        this.return_5d = source["return_5d"];
	        this.return_20d = source["return_20d"];
	        this.avg_range_20d = source["avg_range_20d"];
	        this.drawdown_20d = source["drawdown_20d"];
	        this.amount = source["amount"];
	        this.buy_back_price = source["buy_back_price"];
	        this.reduce_price = source["reduce_price"];
	        this.stop_price = source["stop_price"];
	        this.t_ratio = source["t_ratio"];
	        this.expected_edge = source["expected_edge"];
	        this.plan_json = source["plan_json"];
	        this.reasons = source["reasons"];
	        this.risks = source["risks"];
	        this.generated_at = source["generated_at"];
	        this.first_seen_date = source["first_seen_date"];
	        this.last_seen_date = source["last_seen_date"];
	        this.seen_count = source["seen_count"];
	        this.observation_days = source["observation_days"];
	        this.observation_status = source["observation_status"];
	        this.observation_reason = source["observation_reason"];
	        this.observation_result = source["observation_result"];
	    }
	}
	export class T0TimeMachineResult {
	    run_id: string;
	    ts_code: string;
	    name: string;
	    industry: string;
	    as_of_date: string;
	    eval_start_date: string;
	    eval_end_date: string;
	    score: number;
	    n_eval_days: number;
	    two_sided_count: number;
	    one_sided_count: number;
	    t0_edge: number;
	    avg_t0_edge: number;
	    underlying_return: number;
	    combined_return: number;
	    max_drawdown: number;
	    summary_json: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new T0TimeMachineResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.as_of_date = source["as_of_date"];
	        this.eval_start_date = source["eval_start_date"];
	        this.eval_end_date = source["eval_end_date"];
	        this.score = source["score"];
	        this.n_eval_days = source["n_eval_days"];
	        this.two_sided_count = source["two_sided_count"];
	        this.one_sided_count = source["one_sided_count"];
	        this.t0_edge = source["t0_edge"];
	        this.avg_t0_edge = source["avg_t0_edge"];
	        this.underlying_return = source["underlying_return"];
	        this.combined_return = source["combined_return"];
	        this.max_drawdown = source["max_drawdown"];
	        this.summary_json = source["summary_json"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class ValidationReviewDTO {
	    id: string;
	    subject_type: string;
	    subject_id: string;
	    strategy: string;
	    strategy_version: number;
	    source_run_id: string;
	    status: string;
	    score: number;
	    gates: Record<string, any>;
	    metrics: Record<string, any>;
	    recommendation: string;
	    created_at: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new ValidationReviewDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.subject_type = source["subject_type"];
	        this.subject_id = source["subject_id"];
	        this.strategy = source["strategy"];
	        this.strategy_version = source["strategy_version"];
	        this.source_run_id = source["source_run_id"];
	        this.status = source["status"];
	        this.score = source["score"];
	        this.gates = source["gates"];
	        this.metrics = source["metrics"];
	        this.recommendation = source["recommendation"];
	        this.created_at = source["created_at"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class ValidationEvidenceDTO {
	    reviews: ValidationReviewDTO[];
	    reports: ResearchReportDTO[];
	    snapshots: DataSnapshotDTO[];
	
	    static createFrom(source: any = {}) {
	        return new ValidationEvidenceDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.reviews = this.convertValues(source["reviews"], ValidationReviewDTO);
	        this.reports = this.convertValues(source["reports"], ResearchReportDTO);
	        this.snapshots = this.convertValues(source["snapshots"], DataSnapshotDTO);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class ValidationEvidenceQuery {
	    subject_type: string;
	    subject_id: string;
	    source_run_id: string;
	    limit: number;
	
	    static createFrom(source: any = {}) {
	        return new ValidationEvidenceQuery(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.subject_type = source["subject_type"];
	        this.subject_id = source["subject_id"];
	        this.source_run_id = source["source_run_id"];
	        this.limit = source["limit"];
	    }
	}
	
	

}

export namespace market {
	
	export class BreakoutBar {
	    trade_date: string;
	    open: number;
	    high: number;
	    low: number;
	    close: number;
	    pct_chg: number;
	    projected: boolean;
	
	    static createFrom(source: any = {}) {
	        return new BreakoutBar(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.trade_date = source["trade_date"];
	        this.open = source["open"];
	        this.high = source["high"];
	        this.low = source["low"];
	        this.close = source["close"];
	        this.pct_chg = source["pct_chg"];
	        this.projected = source["projected"];
	    }
	}
	export class BreakoutQuery {
	    limit: number;
	    lookback: number;
	    recent_days: number;
	
	    static createFrom(source: any = {}) {
	        return new BreakoutQuery(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.limit = source["limit"];
	        this.lookback = source["lookback"];
	        this.recent_days = source["recent_days"];
	    }
	}
	export class DailyBar {
	    ts_code: string;
	    trade_date: string;
	    open: number;
	    high: number;
	    low: number;
	    close: number;
	    pre_close: number;
	    change: number;
	    pct_chg: number;
	    vol: number;
	    amount: number;
	
	    static createFrom(source: any = {}) {
	        return new DailyBar(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	        this.trade_date = source["trade_date"];
	        this.open = source["open"];
	        this.high = source["high"];
	        this.low = source["low"];
	        this.close = source["close"];
	        this.pre_close = source["pre_close"];
	        this.change = source["change"];
	        this.pct_chg = source["pct_chg"];
	        this.vol = source["vol"];
	        this.amount = source["amount"];
	    }
	}
	export class DailyQuery {
	    ts_code: string;
	    start_date: string;
	    end_date: string;
	    limit: number;
	
	    static createFrom(source: any = {}) {
	        return new DailyQuery(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	        this.start_date = source["start_date"];
	        this.end_date = source["end_date"];
	        this.limit = source["limit"];
	    }
	}
	export class DataFileDTO {
	    id: string;
	    data_type: string;
	    partition_name: string;
	    file_path: string;
	    row_count: number;
	    file_size: number;
	    created_at: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new DataFileDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.data_type = source["data_type"];
	        this.partition_name = source["partition_name"];
	        this.file_path = source["file_path"];
	        this.row_count = source["row_count"];
	        this.file_size = source["file_size"];
	        this.created_at = source["created_at"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class FinancialIndicator {
	    ts_code: string;
	    ann_date: string;
	    end_date: string;
	    eps: number;
	    roe: number;
	    gross_margin: number;
	    net_margin: number;
	    debt_to_assets: number;
	
	    static createFrom(source: any = {}) {
	        return new FinancialIndicator(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	        this.ann_date = source["ann_date"];
	        this.end_date = source["end_date"];
	        this.eps = source["eps"];
	        this.roe = source["roe"];
	        this.gross_margin = source["gross_margin"];
	        this.net_margin = source["net_margin"];
	        this.debt_to_assets = source["debt_to_assets"];
	    }
	}
	export class FinancialQuery {
	    ts_code: string;
	    limit: number;
	
	    static createFrom(source: any = {}) {
	        return new FinancialQuery(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	        this.limit = source["limit"];
	    }
	}
	export class LimitBreakoutCandidate {
	    ts_code: string;
	    name: string;
	    industry: string;
	    latest_date: string;
	    close: number;
	    score: number;
	    flat_score: number;
	    breakout_score: number;
	    quality_score: number;
	    base_low: number;
	    base_high: number;
	    base_ratio: number;
	    base_return: number;
	    recent_return: number;
	    limit_up_count: number;
	    volume_surge: number;
	    roe: number;
	    net_margin: number;
	    debt_to_assets: number;
	    reasons: string[];
	    bars: BreakoutBar[];
	    projected_bars: BreakoutBar[];
	    first_seen_date: string;
	    last_seen_date: string;
	    seen_count: number;
	    observation_days: number;
	    observation_status: string;
	    observation_reason: string;
	    observation_result: string;
	
	    static createFrom(source: any = {}) {
	        return new LimitBreakoutCandidate(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.latest_date = source["latest_date"];
	        this.close = source["close"];
	        this.score = source["score"];
	        this.flat_score = source["flat_score"];
	        this.breakout_score = source["breakout_score"];
	        this.quality_score = source["quality_score"];
	        this.base_low = source["base_low"];
	        this.base_high = source["base_high"];
	        this.base_ratio = source["base_ratio"];
	        this.base_return = source["base_return"];
	        this.recent_return = source["recent_return"];
	        this.limit_up_count = source["limit_up_count"];
	        this.volume_surge = source["volume_surge"];
	        this.roe = source["roe"];
	        this.net_margin = source["net_margin"];
	        this.debt_to_assets = source["debt_to_assets"];
	        this.reasons = source["reasons"];
	        this.bars = this.convertValues(source["bars"], BreakoutBar);
	        this.projected_bars = this.convertValues(source["projected_bars"], BreakoutBar);
	        this.first_seen_date = source["first_seen_date"];
	        this.last_seen_date = source["last_seen_date"];
	        this.seen_count = source["seen_count"];
	        this.observation_days = source["observation_days"];
	        this.observation_status = source["observation_status"];
	        this.observation_reason = source["observation_reason"];
	        this.observation_result = source["observation_result"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class LimitSignalEvaluationSummary {
	    signal_type: string;
	    strategy_version: string;
	    parameter_key: string;
	    sample_count: number;
	    pending_count: number;
	    hit_rate: number;
	    avg_return_1d: number;
	    avg_return_3d: number;
	    avg_return_5d: number;
	    avg_return_10d: number;
	    avg_max_drawdown_5d: number;
	    avg_score: number;
	    recommendation: string;
	    parameter_hint: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new LimitSignalEvaluationSummary(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.signal_type = source["signal_type"];
	        this.strategy_version = source["strategy_version"];
	        this.parameter_key = source["parameter_key"];
	        this.sample_count = source["sample_count"];
	        this.pending_count = source["pending_count"];
	        this.hit_rate = source["hit_rate"];
	        this.avg_return_1d = source["avg_return_1d"];
	        this.avg_return_3d = source["avg_return_3d"];
	        this.avg_return_5d = source["avg_return_5d"];
	        this.avg_return_10d = source["avg_return_10d"];
	        this.avg_max_drawdown_5d = source["avg_max_drawdown_5d"];
	        this.avg_score = source["avg_score"];
	        this.recommendation = source["recommendation"];
	        this.parameter_hint = source["parameter_hint"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class LimitSignalTimeMachineSlice {
	    signal_type: string;
	    strategy_version: string;
	    parameter_key: string;
	    signal_date: string;
	    candidate_count: number;
	    evaluated_count: number;
	    hit_rate: number;
	    limit_up_hit_rate: number;
	    avg_return_1d: number;
	    avg_return_3d: number;
	    avg_return_5d: number;
	    avg_return_10d: number;
	    avg_target_return: number;
	    avg_max_drawdown_5d: number;
	    avg_score: number;
	    slice_score: number;
	    market_heat_score: number;
	    limit_up_count: number;
	    limit_up_ratio: number;
	    up_ratio: number;
	    hot_tags_json: string;
	    top_industries_json: string;
	    recommendation: string;
	    summary_json: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new LimitSignalTimeMachineSlice(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.signal_type = source["signal_type"];
	        this.strategy_version = source["strategy_version"];
	        this.parameter_key = source["parameter_key"];
	        this.signal_date = source["signal_date"];
	        this.candidate_count = source["candidate_count"];
	        this.evaluated_count = source["evaluated_count"];
	        this.hit_rate = source["hit_rate"];
	        this.limit_up_hit_rate = source["limit_up_hit_rate"];
	        this.avg_return_1d = source["avg_return_1d"];
	        this.avg_return_3d = source["avg_return_3d"];
	        this.avg_return_5d = source["avg_return_5d"];
	        this.avg_return_10d = source["avg_return_10d"];
	        this.avg_target_return = source["avg_target_return"];
	        this.avg_max_drawdown_5d = source["avg_max_drawdown_5d"];
	        this.avg_score = source["avg_score"];
	        this.slice_score = source["slice_score"];
	        this.market_heat_score = source["market_heat_score"];
	        this.limit_up_count = source["limit_up_count"];
	        this.limit_up_ratio = source["limit_up_ratio"];
	        this.up_ratio = source["up_ratio"];
	        this.hot_tags_json = source["hot_tags_json"];
	        this.top_industries_json = source["top_industries_json"];
	        this.recommendation = source["recommendation"];
	        this.summary_json = source["summary_json"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class LimitUpMomentumCandidate {
	    ts_code: string;
	    name: string;
	    industry: string;
	    trade_date: string;
	    close: number;
	    stage: string;
	    recommendation: string;
	    score: number;
	    chain_potential: number;
	    end_risk: number;
	    liquidity_risk: number;
	    fund_confirmation: number;
	    limit_up_count: number;
	    consecutive_boards: number;
	    next_day_return: number;
	    return_3d: number;
	    return_5d: number;
	    return_10d: number;
	    max_drawdown_5d: number;
	    recent_20_return: number;
	    recent_60_return: number;
	    turnover_rate: number;
	    volume_ratio: number;
	    amount: number;
	    total_mv: number;
	    circ_mv: number;
	    dragon_tiger_net_buy: number;
	    institution_net_buy: number;
	    reasons: string[];
	    risks: string[];
	    bars: BreakoutBar[];
	    projected_bars: BreakoutBar[];
	    first_seen_date: string;
	    last_seen_date: string;
	    seen_count: number;
	    observation_days: number;
	    observation_status: string;
	    observation_reason: string;
	    observation_result: string;
	
	    static createFrom(source: any = {}) {
	        return new LimitUpMomentumCandidate(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.trade_date = source["trade_date"];
	        this.close = source["close"];
	        this.stage = source["stage"];
	        this.recommendation = source["recommendation"];
	        this.score = source["score"];
	        this.chain_potential = source["chain_potential"];
	        this.end_risk = source["end_risk"];
	        this.liquidity_risk = source["liquidity_risk"];
	        this.fund_confirmation = source["fund_confirmation"];
	        this.limit_up_count = source["limit_up_count"];
	        this.consecutive_boards = source["consecutive_boards"];
	        this.next_day_return = source["next_day_return"];
	        this.return_3d = source["return_3d"];
	        this.return_5d = source["return_5d"];
	        this.return_10d = source["return_10d"];
	        this.max_drawdown_5d = source["max_drawdown_5d"];
	        this.recent_20_return = source["recent_20_return"];
	        this.recent_60_return = source["recent_60_return"];
	        this.turnover_rate = source["turnover_rate"];
	        this.volume_ratio = source["volume_ratio"];
	        this.amount = source["amount"];
	        this.total_mv = source["total_mv"];
	        this.circ_mv = source["circ_mv"];
	        this.dragon_tiger_net_buy = source["dragon_tiger_net_buy"];
	        this.institution_net_buy = source["institution_net_buy"];
	        this.reasons = source["reasons"];
	        this.risks = source["risks"];
	        this.bars = this.convertValues(source["bars"], BreakoutBar);
	        this.projected_bars = this.convertValues(source["projected_bars"], BreakoutBar);
	        this.first_seen_date = source["first_seen_date"];
	        this.last_seen_date = source["last_seen_date"];
	        this.seen_count = source["seen_count"];
	        this.observation_days = source["observation_days"];
	        this.observation_status = source["observation_status"];
	        this.observation_reason = source["observation_reason"];
	        this.observation_result = source["observation_result"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class LimitUpMomentumQuery {
	    limit: number;
	    lookback: number;
	    history_days: number;
	
	    static createFrom(source: any = {}) {
	        return new LimitUpMomentumQuery(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.limit = source["limit"];
	        this.lookback = source["lookback"];
	        this.history_days = source["history_days"];
	    }
	}
	export class StockBasic {
	    ts_code: string;
	    symbol: string;
	    name: string;
	    area: string;
	    industry: string;
	    market: string;
	    list_date: string;
	    list_status: string;
	
	    static createFrom(source: any = {}) {
	        return new StockBasic(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	        this.symbol = source["symbol"];
	        this.name = source["name"];
	        this.area = source["area"];
	        this.industry = source["industry"];
	        this.market = source["market"];
	        this.list_date = source["list_date"];
	        this.list_status = source["list_status"];
	    }
	}
	export class StockBasicQuery {
	    keyword: string;
	    limit: number;
	
	    static createFrom(source: any = {}) {
	        return new StockBasicQuery(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.keyword = source["keyword"];
	        this.limit = source["limit"];
	    }
	}
	export class StockValuation {
	    ts_code: string;
	    name: string;
	    industry: string;
	    trade_date: string;
	    close: number;
	    total_mv: number;
	    circ_mv: number;
	    pe_ttm: number;
	    pb: number;
	    ps_ttm: number;
	    roe: number;
	    debt_to_assets: number;
	    peer_count: number;
	    valuation_percentile: number;
	    market_cap_percentile: number;
	    implied_mv: number;
	    mispricing_pct: number;
	    score: number;
	    verdict: string;
	    reason: string;
	    tags: string[];
	
	    static createFrom(source: any = {}) {
	        return new StockValuation(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.trade_date = source["trade_date"];
	        this.close = source["close"];
	        this.total_mv = source["total_mv"];
	        this.circ_mv = source["circ_mv"];
	        this.pe_ttm = source["pe_ttm"];
	        this.pb = source["pb"];
	        this.ps_ttm = source["ps_ttm"];
	        this.roe = source["roe"];
	        this.debt_to_assets = source["debt_to_assets"];
	        this.peer_count = source["peer_count"];
	        this.valuation_percentile = source["valuation_percentile"];
	        this.market_cap_percentile = source["market_cap_percentile"];
	        this.implied_mv = source["implied_mv"];
	        this.mispricing_pct = source["mispricing_pct"];
	        this.score = source["score"];
	        this.verdict = source["verdict"];
	        this.reason = source["reason"];
	        this.tags = source["tags"];
	    }
	}
	export class ValuationQuery {
	    ts_code: string;
	
	    static createFrom(source: any = {}) {
	        return new ValuationQuery(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	    }
	}

}

export namespace position {
	
	export class GenerateSignalRequest {
	    date: string;
	    initial_cash: number;
	    rebalance_freq: number;
	    portfolio_run_id: string;
	    portfolio_candidate_id: string;
	
	    static createFrom(source: any = {}) {
	        return new GenerateSignalRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.date = source["date"];
	        this.initial_cash = source["initial_cash"];
	        this.rebalance_freq = source["rebalance_freq"];
	        this.portfolio_run_id = source["portfolio_run_id"];
	        this.portfolio_candidate_id = source["portfolio_candidate_id"];
	    }
	}
	export class GenerateSignalResponse {
	    date: string;
	    output: string;
	    success: boolean;
	
	    static createFrom(source: any = {}) {
	        return new GenerateSignalResponse(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.date = source["date"];
	        this.output = source["output"];
	        this.success = source["success"];
	    }
	}
	export class HistoryPoint {
	    date: string;
	    cash: number;
	    market_value: number;
	    equity: number;
	    n_holdings: number;
	    unrealized_pnl: number;
	    realized_pnl: number;
	    cum_return: number;
	    daily_return: number;
	
	    static createFrom(source: any = {}) {
	        return new HistoryPoint(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.date = source["date"];
	        this.cash = source["cash"];
	        this.market_value = source["market_value"];
	        this.equity = source["equity"];
	        this.n_holdings = source["n_holdings"];
	        this.unrealized_pnl = source["unrealized_pnl"];
	        this.realized_pnl = source["realized_pnl"];
	        this.cum_return = source["cum_return"];
	        this.daily_return = source["daily_return"];
	    }
	}
	export class TradeRecord {
	    date: string;
	    action: string;
	    shares: number;
	    price: number;
	    amount: number;
	    realized_pnl: number;
	    exit_reason: string;
	    exit_pct: number;
	
	    static createFrom(source: any = {}) {
	        return new TradeRecord(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.date = source["date"];
	        this.action = source["action"];
	        this.shares = source["shares"];
	        this.price = source["price"];
	        this.amount = source["amount"];
	        this.realized_pnl = source["realized_pnl"];
	        this.exit_reason = source["exit_reason"];
	        this.exit_pct = source["exit_pct"];
	    }
	}
	export class Source {
	    strategy: string;
	    weight: number;
	
	    static createFrom(source: any = {}) {
	        return new Source(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.strategy = source["strategy"];
	        this.weight = source["weight"];
	    }
	}
	export class Position {
	    ts_code: string;
	    name: string;
	    industry: string;
	    shares: number;
	    avg_cost: number;
	    peak_price: number;
	    first_entry_date: string;
	    last_action_date: string;
	    holder_account: string;
	    note: string;
	    sources: Source[];
	    trades: TradeRecord[];
	    price: number;
	    cost: number;
	    market_value: number;
	    unrealized_pnl: number;
	    unrealized_pct: number;
	    prev_close: number;
	    today_pnl: number;
	    today_pct: number;
	    weight: number;
	    hold_days: number;
	
	    static createFrom(source: any = {}) {
	        return new Position(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.shares = source["shares"];
	        this.avg_cost = source["avg_cost"];
	        this.peak_price = source["peak_price"];
	        this.first_entry_date = source["first_entry_date"];
	        this.last_action_date = source["last_action_date"];
	        this.holder_account = source["holder_account"];
	        this.note = source["note"];
	        this.sources = this.convertValues(source["sources"], Source);
	        this.trades = this.convertValues(source["trades"], TradeRecord);
	        this.price = source["price"];
	        this.cost = source["cost"];
	        this.market_value = source["market_value"];
	        this.unrealized_pnl = source["unrealized_pnl"];
	        this.unrealized_pct = source["unrealized_pct"];
	        this.prev_close = source["prev_close"];
	        this.today_pnl = source["today_pnl"];
	        this.today_pct = source["today_pct"];
	        this.weight = source["weight"];
	        this.hold_days = source["hold_days"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class RecommendationItem {
	    action: string;
	    ts_code: string;
	    name: string;
	    industry: string;
	    from_weight: number;
	    to_weight: number;
	    delta_weight: number;
	    price: number;
	    pct_chg: number;
	    target_shares: number;
	    target_amount: number;
	    buy_trigger_price: number;
	    sell_target_price: number;
	    stop_price: number;
	    sources: Source[];
	
	    static createFrom(source: any = {}) {
	        return new RecommendationItem(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.action = source["action"];
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.from_weight = source["from_weight"];
	        this.to_weight = source["to_weight"];
	        this.delta_weight = source["delta_weight"];
	        this.price = source["price"];
	        this.pct_chg = source["pct_chg"];
	        this.target_shares = source["target_shares"];
	        this.target_amount = source["target_amount"];
	        this.buy_trigger_price = source["buy_trigger_price"];
	        this.sell_target_price = source["sell_target_price"];
	        this.stop_price = source["stop_price"];
	        this.sources = this.convertValues(source["sources"], Source);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class RecommendationStrategyVersion {
	    strategy: string;
	    label: string;
	    version: number;
	    mode: string;
	    weight: number;
	
	    static createFrom(source: any = {}) {
	        return new RecommendationStrategyVersion(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.strategy = source["strategy"];
	        this.label = source["label"];
	        this.version = source["version"];
	        this.mode = source["mode"];
	        this.weight = source["weight"];
	    }
	}
	export class Recommendation {
	    date: string;
	    generated_at: string;
	    total_weight: number;
	    n_holdings: number;
	    n_buy: number;
	    n_sell: number;
	    rebalanced: boolean;
	    rebalance_trades: number;
	    active_strategy_versions: RecommendationStrategyVersion[];
	    rows: RecommendationItem[];
	
	    static createFrom(source: any = {}) {
	        return new Recommendation(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.date = source["date"];
	        this.generated_at = source["generated_at"];
	        this.total_weight = source["total_weight"];
	        this.n_holdings = source["n_holdings"];
	        this.n_buy = source["n_buy"];
	        this.n_sell = source["n_sell"];
	        this.rebalanced = source["rebalanced"];
	        this.rebalance_trades = source["rebalance_trades"];
	        this.active_strategy_versions = this.convertValues(source["active_strategy_versions"], RecommendationStrategyVersion);
	        this.rows = this.convertValues(source["rows"], RecommendationItem);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	
	export class RunStatus {
	    task: string;
	    task_type: string;
	    state: string;
	    idx: number;
	    total: number;
	    stage: string;
	    name: string;
	    message: string;
	    worker_pid: number;
	    started_at: string;
	    updated_at: string;
	    finished_at: string;
	
	    static createFrom(source: any = {}) {
	        return new RunStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.task = source["task"];
	        this.task_type = source["task_type"];
	        this.state = source["state"];
	        this.idx = source["idx"];
	        this.total = source["total"];
	        this.stage = source["stage"];
	        this.name = source["name"];
	        this.message = source["message"];
	        this.worker_pid = source["worker_pid"];
	        this.started_at = source["started_at"];
	        this.updated_at = source["updated_at"];
	        this.finished_at = source["finished_at"];
	    }
	}
	
	export class Summary {
	    initial_cash: number;
	    cash: number;
	    market_value: number;
	    total_assets: number;
	    total_cost: number;
	    total_fee: number;
	    total_pnl: number;
	    today_pnl: number;
	    today_pct: number;
	    unrealized_pnl: number;
	    unrealized_pct: number;
	    realized_pnl: number;
	    cum_return: number;
	    n_holdings: number;
	    n_closed: number;
	    updated_at: string;
	    positions: Position[];
	
	    static createFrom(source: any = {}) {
	        return new Summary(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.initial_cash = source["initial_cash"];
	        this.cash = source["cash"];
	        this.market_value = source["market_value"];
	        this.total_assets = source["total_assets"];
	        this.total_cost = source["total_cost"];
	        this.total_fee = source["total_fee"];
	        this.total_pnl = source["total_pnl"];
	        this.today_pnl = source["today_pnl"];
	        this.today_pct = source["today_pct"];
	        this.unrealized_pnl = source["unrealized_pnl"];
	        this.unrealized_pct = source["unrealized_pct"];
	        this.realized_pnl = source["realized_pnl"];
	        this.cum_return = source["cum_return"];
	        this.n_holdings = source["n_holdings"];
	        this.n_closed = source["n_closed"];
	        this.updated_at = source["updated_at"];
	        this.positions = this.convertValues(source["positions"], Position);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	export class TradeRequest {
	    ts_code: string;
	    action: string;
	    shares: number;
	    price: number;
	    date: string;
	    exit_reason: string;
	    exit_pct: number;
	    trigger_type: string;
	    trigger_price: number;
	    sources: Source[];
	
	    static createFrom(source: any = {}) {
	        return new TradeRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts_code = source["ts_code"];
	        this.action = source["action"];
	        this.shares = source["shares"];
	        this.price = source["price"];
	        this.date = source["date"];
	        this.exit_reason = source["exit_reason"];
	        this.exit_pct = source["exit_pct"];
	        this.trigger_type = source["trigger_type"];
	        this.trigger_price = source["trigger_price"];
	        this.sources = this.convertValues(source["sources"], Source);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

}

export namespace result {
	
	export class PositionRow {
	    date: string;
	    ts_code: string;
	    name: string;
	    shares: number;
	    avg_cost: number;
	    price: number;
	    market_value: number;
	    unrealized_pnl: number;
	    unrealized_pct: number;
	    today_pnl: number;
	    today_pct: number;
	    weight: number;
	    hold_days: number;
	
	    static createFrom(source: any = {}) {
	        return new PositionRow(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.date = source["date"];
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.shares = source["shares"];
	        this.avg_cost = source["avg_cost"];
	        this.price = source["price"];
	        this.market_value = source["market_value"];
	        this.unrealized_pnl = source["unrealized_pnl"];
	        this.unrealized_pct = source["unrealized_pct"];
	        this.today_pnl = source["today_pnl"];
	        this.today_pct = source["today_pct"];
	        this.weight = source["weight"];
	        this.hold_days = source["hold_days"];
	    }
	}
	export class SnapshotRow {
	    date: string;
	    cash: number;
	    market_value: number;
	    equity: number;
	    n_holdings: number;
	    unrealized_pnl: number;
	    realized_pnl: number;
	    cum_return: number;
	
	    static createFrom(source: any = {}) {
	        return new SnapshotRow(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.date = source["date"];
	        this.cash = source["cash"];
	        this.market_value = source["market_value"];
	        this.equity = source["equity"];
	        this.n_holdings = source["n_holdings"];
	        this.unrealized_pnl = source["unrealized_pnl"];
	        this.realized_pnl = source["realized_pnl"];
	        this.cum_return = source["cum_return"];
	    }
	}
	export class TradeRow {
	    date: string;
	    ts_code: string;
	    name: string;
	    action: string;
	    shares: number;
	    price: number;
	    amount: number;
	    hold_days: number;
	    realized_pnl: number;
	    exit_reason: string;
	    exec_date: string;
	    is_new: boolean;
	
	    static createFrom(source: any = {}) {
	        return new TradeRow(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.date = source["date"];
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.action = source["action"];
	        this.shares = source["shares"];
	        this.price = source["price"];
	        this.amount = source["amount"];
	        this.hold_days = source["hold_days"];
	        this.realized_pnl = source["realized_pnl"];
	        this.exit_reason = source["exit_reason"];
	        this.exec_date = source["exec_date"];
	        this.is_new = source["is_new"];
	    }
	}
	export class TimeMachineDetail {
	    run_id: string;
	    summary: Record<string, any>;
	    snapshots: SnapshotRow[];
	    trades: TradeRow[];
	    positions: PositionRow[];
	
	    static createFrom(source: any = {}) {
	        return new TimeMachineDetail(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.summary = source["summary"];
	        this.snapshots = this.convertValues(source["snapshots"], SnapshotRow);
	        this.trades = this.convertValues(source["trades"], TradeRow);
	        this.positions = this.convertValues(source["positions"], PositionRow);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

}

export namespace task {
	
	export class CreateRequest {
	    name: string;
	    task_type: string;
	    params: Record<string, any>;
	
	    static createFrom(source: any = {}) {
	        return new CreateRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.task_type = source["task_type"];
	        this.params = source["params"];
	    }
	}
	export class DTO {
	    id: string;
	    name: string;
	    task_type: string;
	    status: string;
	    progress: number;
	    params: Record<string, any>;
	    summary: Record<string, any>;
	    result_path: string;
	    log_path: string;
	    worker_type: string;
	    worker_pid: number;
	    external_run_id: string;
	    error_message: string;
	    parent_id: string;
	    group_run_id: string;
	    subtask_key: string;
	    subtask_name: string;
	    sequence: number;
	    total: number;
	    attempt: number;
	    max_attempts: number;
	    created_at: string;
	    queued_at: string;
	    started_at: string;
	    finished_at: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new DTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.name = source["name"];
	        this.task_type = source["task_type"];
	        this.status = source["status"];
	        this.progress = source["progress"];
	        this.params = source["params"];
	        this.summary = source["summary"];
	        this.result_path = source["result_path"];
	        this.log_path = source["log_path"];
	        this.worker_type = source["worker_type"];
	        this.worker_pid = source["worker_pid"];
	        this.external_run_id = source["external_run_id"];
	        this.error_message = source["error_message"];
	        this.parent_id = source["parent_id"];
	        this.group_run_id = source["group_run_id"];
	        this.subtask_key = source["subtask_key"];
	        this.subtask_name = source["subtask_name"];
	        this.sequence = source["sequence"];
	        this.total = source["total"];
	        this.attempt = source["attempt"];
	        this.max_attempts = source["max_attempts"];
	        this.created_at = source["created_at"];
	        this.queued_at = source["queued_at"];
	        this.started_at = source["started_at"];
	        this.finished_at = source["finished_at"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class Query {
	    status: string;
	    limit: number;
	
	    static createFrom(source: any = {}) {
	        return new Query(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.status = source["status"];
	        this.limit = source["limit"];
	    }
	}

}


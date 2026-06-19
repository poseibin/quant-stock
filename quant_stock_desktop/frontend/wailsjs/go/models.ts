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
	    llm_provider: string;
	    openai_token: string;
	    openai_model: string;
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
	        this.llm_provider = source["llm_provider"];
	        this.openai_token = source["openai_token"];
	        this.openai_model = source["openai_model"];
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
	export class ArenaStrategyDefinitionDTO {
	    strategy_id: string;
	    display_name: string;
	    default_arena_name: string;
	    artifact_dir_name: string;
	    task_label: string;
	    tables: Record<string, any>;
	    metadata: Record<string, any>;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new ArenaStrategyDefinitionDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.strategy_id = source["strategy_id"];
	        this.display_name = source["display_name"];
	        this.default_arena_name = source["default_arena_name"];
	        this.artifact_dir_name = source["artifact_dir_name"];
	        this.task_label = source["task_label"];
	        this.tables = source["tables"];
	        this.metadata = source["metadata"];
	        this.updated_at = source["updated_at"];
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
	export class ProfitArenaEvaluation {
	    run_id: string;
	    scope: string;
	    horizon: number;
	    top_n: number;
	    min_pred_return: number;
	    min_market_up_ratio: number;
	    min_market_ret5: number;
	    min_market_amount_chg5: number;
	    min_industry_up_ratio: number;
	    segment: string;
	    trade_count: number;
	    trade_days: number;
	    avg_return: number;
	    win_rate: number;
	    compound_return: number;
	    annual_return: number;
	    max_drawdown: number;
	    sharpe: number;
	    capital_compound_return: number;
	    capital_annual_return: number;
	    capital_max_drawdown: number;
	    capital_sharpe: number;
	    capital_final_equity: number;
	    summary_json: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new ProfitArenaEvaluation(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.scope = source["scope"];
	        this.horizon = source["horizon"];
	        this.top_n = source["top_n"];
	        this.min_pred_return = source["min_pred_return"];
	        this.min_market_up_ratio = source["min_market_up_ratio"];
	        this.min_market_ret5 = source["min_market_ret5"];
	        this.min_market_amount_chg5 = source["min_market_amount_chg5"];
	        this.min_industry_up_ratio = source["min_industry_up_ratio"];
	        this.segment = source["segment"];
	        this.trade_count = source["trade_count"];
	        this.trade_days = source["trade_days"];
	        this.avg_return = source["avg_return"];
	        this.win_rate = source["win_rate"];
	        this.compound_return = source["compound_return"];
	        this.annual_return = source["annual_return"];
	        this.max_drawdown = source["max_drawdown"];
	        this.sharpe = source["sharpe"];
	        this.capital_compound_return = source["capital_compound_return"];
	        this.capital_annual_return = source["capital_annual_return"];
	        this.capital_max_drawdown = source["capital_max_drawdown"];
	        this.capital_sharpe = source["capital_sharpe"];
	        this.capital_final_equity = source["capital_final_equity"];
	        this.summary_json = source["summary_json"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class ProfitArenaFeature {
	    run_id: string;
	    scope: string;
	    horizon: number;
	    feature: string;
	    importance: number;
	    rank_no: number;
	
	    static createFrom(source: any = {}) {
	        return new ProfitArenaFeature(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.scope = source["scope"];
	        this.horizon = source["horizon"];
	        this.feature = source["feature"];
	        this.importance = source["importance"];
	        this.rank_no = source["rank_no"];
	    }
	}
	export class ProfitArenaPrediction {
	    run_id: string;
	    scope: string;
	    horizon: number;
	    trade_date: string;
	    ts_code: string;
	    name: string;
	    industry: string;
	    size_bucket: string;
	    price: number;
	    amount: number;
	    pred_return: number;
	    model_score: number;
	    realized_return: number;
	    future_return: number;
	    future_max_return: number;
	    future_drawdown: number;
	    crash_prob: number;
	    exit_date: string;
	    is_latest: boolean;
	    summary_json: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new ProfitArenaPrediction(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.scope = source["scope"];
	        this.horizon = source["horizon"];
	        this.trade_date = source["trade_date"];
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.industry = source["industry"];
	        this.size_bucket = source["size_bucket"];
	        this.price = source["price"];
	        this.amount = source["amount"];
	        this.pred_return = source["pred_return"];
	        this.model_score = source["model_score"];
	        this.realized_return = source["realized_return"];
	        this.future_return = source["future_return"];
	        this.future_max_return = source["future_max_return"];
	        this.future_drawdown = source["future_drawdown"];
	        this.crash_prob = source["crash_prob"];
	        this.exit_date = source["exit_date"];
	        this.is_latest = source["is_latest"];
	        this.summary_json = source["summary_json"];
	        this.updated_at = source["updated_at"];
	    }
	}
	export class ProfitArenaRunSummary {
	    run_id: string;
	    start_date: string;
	    end_date: string;
	    train_mode: string;
	    model_type: string;
	    feature_count: number;
	    status: string;
	    best_scope: string;
	    best_horizon: number;
	    best_top_n: number;
	    best_compound_return: number;
	    summary_json: string;
	    model_path: string;
	    updated_at: string;
	
	    static createFrom(source: any = {}) {
	        return new ProfitArenaRunSummary(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_id = source["run_id"];
	        this.start_date = source["start_date"];
	        this.end_date = source["end_date"];
	        this.train_mode = source["train_mode"];
	        this.model_type = source["model_type"];
	        this.feature_count = source["feature_count"];
	        this.status = source["status"];
	        this.best_scope = source["best_scope"];
	        this.best_horizon = source["best_horizon"];
	        this.best_top_n = source["best_top_n"];
	        this.best_compound_return = source["best_compound_return"];
	        this.summary_json = source["summary_json"];
	        this.model_path = source["model_path"];
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

}

export namespace market {
	
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
	    id: number;
	    date: string;
	    action: string;
	    ts_code: string;
	    name: string;
	    shares: number;
	    price: number;
	    amount: number;
	    fee: number;
	    net_amount: number;
	    cash_after: number;
	    position_pnl: number;
	    realized_pnl: number;
	    exit_reason: string;
	    exit_pct: number;
	
	    static createFrom(source: any = {}) {
	        return new TradeRecord(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.date = source["date"];
	        this.action = source["action"];
	        this.ts_code = source["ts_code"];
	        this.name = source["name"];
	        this.shares = source["shares"];
	        this.price = source["price"];
	        this.amount = source["amount"];
	        this.fee = source["fee"];
	        this.net_amount = source["net_amount"];
	        this.cash_after = source["cash_after"];
	        this.position_pnl = source["position_pnl"];
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
	    metadata?: Record<string, any>;
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
	        this.metadata = source["metadata"];
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
	    quote_status?: string;
	    quote_message?: string;
	    quote_source?: string;
	    quote_updated_at?: string;
	    positions: Position[];
	    trades: TradeRecord[];
	
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
	        this.quote_status = source["quote_status"];
	        this.quote_message = source["quote_message"];
	        this.quote_source = source["quote_source"];
	        this.quote_updated_at = source["quote_updated_at"];
	        this.positions = this.convertValues(source["positions"], Position);
	        this.trades = this.convertValues(source["trades"], TradeRecord);
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


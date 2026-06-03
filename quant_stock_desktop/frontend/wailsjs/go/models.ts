export namespace config {
	
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
	    workspace_path: string;
	    data_path: string;
	    default_initial_cash: number;
	    default_rebalance_freq: number;
	    tushare_token: string;
	    strategies: Record<string, StrategySettings>;
	    portfolio_risk: Record<string, any>;
	    exit_rules: Record<string, any>;
	
	    static createFrom(source: any = {}) {
	        return new Settings(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.workspace_path = source["workspace_path"];
	        this.data_path = source["data_path"];
	        this.default_initial_cash = source["default_initial_cash"];
	        this.default_rebalance_freq = source["default_rebalance_freq"];
	        this.tushare_token = source["tushare_token"];
	        this.strategies = this.convertValues(source["strategies"], StrategySettings, true);
	        this.portfolio_risk = source["portfolio_risk"];
	        this.exit_rules = source["exit_rules"];
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
	    state: string;
	    idx: number;
	    total: number;
	    stage: string;
	    name: string;
	    message: string;
	    started_at: string;
	    updated_at: string;
	    finished_at: string;
	
	    static createFrom(source: any = {}) {
	        return new RunStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.task = source["task"];
	        this.state = source["state"];
	        this.idx = source["idx"];
	        this.total = source["total"];
	        this.stage = source["stage"];
	        this.name = source["name"];
	        this.message = source["message"];
	        this.started_at = source["started_at"];
	        this.updated_at = source["updated_at"];
	        this.finished_at = source["finished_at"];
	    }
	}
	export class UpdateRequest {
	    phase: string;
	    start_date: string;
	    dataset: string;
	
	    static createFrom(source: any = {}) {
	        return new UpdateRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.phase = source["phase"];
	        this.start_date = source["start_date"];
	        this.dataset = source["dataset"];
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
	export class DataFetchJob {
	    name: string;
	    category: string;
	
	    static createFrom(source: any = {}) {
	        return new DataFetchJob(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.category = source["category"];
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
	export class DatasetPreview {
	    dataset: string;
	    columns: string[];
	    rows: any[];
	
	    static createFrom(source: any = {}) {
	        return new DatasetPreview(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.dataset = source["dataset"];
	        this.columns = source["columns"];
	        this.rows = source["rows"];
	    }
	}
	export class DatasetPreviewQuery {
	    dataset: string;
	    limit: number;
	
	    static createFrom(source: any = {}) {
	        return new DatasetPreviewQuery(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.dataset = source["dataset"];
	        this.limit = source["limit"];
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
	
	    static createFrom(source: any = {}) {
	        return new GenerateSignalRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.date = source["date"];
	        this.initial_cash = source["initial_cash"];
	        this.rebalance_freq = source["rebalance_freq"];
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
	export class Recommendation {
	    date: string;
	    generated_at: string;
	    total_weight: number;
	    n_holdings: number;
	    n_buy: number;
	    n_sell: number;
	    rebalanced: boolean;
	    rebalance_trades: number;
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
	    state: string;
	    idx: number;
	    total: number;
	    stage: string;
	    name: string;
	    message: string;
	    started_at: string;
	    updated_at: string;
	    finished_at: string;
	
	    static createFrom(source: any = {}) {
	        return new RunStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.task = source["task"];
	        this.state = source["state"];
	        this.idx = source["idx"];
	        this.total = source["total"];
	        this.stage = source["stage"];
	        this.name = source["name"];
	        this.message = source["message"];
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


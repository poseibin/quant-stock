import { useCallback, useEffect, useMemo, useState } from 'react'
import { BarChart3, BrainCircuit, CheckCircle2, DatabaseZap, FlaskConical, Layers3, Play, RefreshCw, ShieldCheck } from 'lucide-react'
import { createTask, getFactorModelRun, listCrashWarningFeatures, listCrashWarningRuns, listFactorAdmissionComparisons, listFactorCorrelationResults, listFactorICResults, listFactorLatestPredictions, listFactorModelFeatures, listFactorModelPredictions, listFactorObservationEvents, listFactorResearchRuns, listFactorStateICResults, listFactorStressResults, listTasks, runFactorLatestInference, startTask, type CrashWarningFeature, type CrashWarningRunSummary, type FactorAdmissionComparison, type FactorCorrelationResult, type FactorICResult, type FactorLatestPrediction, type FactorModelFeature, type FactorModelPrediction, type FactorModelRun, type FactorObservationEvent, type FactorResearchRunSummary, type FactorStateICResult, type FactorStressResult, type TaskDTO } from '../services/app'

type FactorFamily = {
  name: string
  count: number
  examples: string
  role: string
  status: 'ready' | 'design' | 'next'
}

type PipelineStep = {
  key: string
  title: string
  owner: string
  output: string
  detail: string
  status: '已完成' | '运行中' | '排队中' | '待执行' | '失败' | '已取消'
}

type ResearchTab = 'recommend' | 'model' | 'evaluation'

type GeneralStrategyPlan = {
  buy: number
  sell: number
  stop: number
  shares: number
}

const researchTabs: Array<{ key: ResearchTab; label: string }> = [
  { key: 'recommend', label: '股票推荐' },
  { key: 'model', label: '模型训练' },
  { key: 'evaluation', label: '模型评估' }
]

const factorFamilies: FactorFamily[] = [
  { name: '估值', count: 13, examples: 'EP、BP、SP、PE/PB/PS、股息率、行业内估值分位', role: '提供长期均值回归和估值保护', status: 'ready' },
  { name: '质量', count: 27, examples: 'ROE、ROA、ROIC、毛利率、现金流质量、负债和营运效率', role: '过滤利润质量和资产负债表风险', status: 'ready' },
  { name: '成长', count: 14, examples: '营收同比、利润同比、现金流同比、资产和权益扩张', role: '识别基本面改善和业绩弹性', status: 'ready' },
  { name: '动量', count: 10, examples: '20/60/120/240日收益、收益差、均线距离、趋势强度', role: '捕捉中期价格确认', status: 'ready' },
  { name: '反转/过热', count: 7, examples: '5/10日收益、距高点、短期均线乖离、量能尖峰', role: '控制追高和拥挤交易', status: 'ready' },
  { name: '风险', count: 9, examples: '20/60日波动、下行波动、回撤、跳空、短期尾部风险', role: '降低裸策略回撤', status: 'ready' },
  { name: '流动性/拥挤', count: 8, examples: '成交额、换手率、量比、成交额变化、Amihud', role: '控制容量、滑点和拥挤度', status: 'ready' },
  { name: '市值/结构', count: 6, examples: '总市值、流通市值、自由流通股本、上市天数', role: '处理规模暴露和新股风险', status: 'ready' },
  { name: '事件/预期', count: 11, examples: '业绩预告、预告利润、龙虎榜、机构净买、高管增减持', role: '作为低容量卫星信号，辅助模型识别催化', status: 'ready' }
]

const pipelineBase: Array<Omit<PipelineStep, 'status'>> = [
  { key: 'build_factor_panel', title: '生成因子面板', owner: 'Python 研究引擎', output: 'monthly_factor_panel', detail: '按调仓日生成 point-in-time 横截面，财务和事件字段只使用调仓日前可见数据。' },
  { key: 'evaluate_factors', title: '因子检验', owner: 'Python 研究引擎', output: 'factor_ic_results', detail: '计算 IC、Rank IC、ICIR、分层收益、多空收益和市场状态下的因子强弱。' },
  { key: 'factor_correlation_report', title: '相关性去冗余', owner: 'Python 研究引擎', output: 'factor_correlation_report', detail: '按 Spearman 相关性识别重复特征，给训练特征写入保留和剔除依据。' },
  { key: 'train_lgbm', title: '训练 LightGBM', owner: 'Python 模型引擎', output: 'factor_model_runs', detail: '用 walk-forward 预测未来 20 日行业相对收益，落库 OOS 预测和特征重要度。' },
  { key: 'latest_inference', title: '最新截面推理', owner: 'Python 模型引擎', output: 'factor_latest_predictions', detail: '使用最新生效模型对当前截面打分，输出 Top20% 候选池。' },
  { key: 'stress_report', title: '压力分段报告', owner: 'Python 评估引擎', output: 'factor_model_stress_results', detail: '按股灾、弱势、流动性挤压、年度等分段检查模型失效区间。' },
  { key: 'strategy_admission', title: '策略准入评估', owner: 'Go 编排 + 准入评估', output: 'eval_strategy_admission', detail: '把 ml_factor_ranker 接入准入表，统一输出可启用、观察或拒绝的依据。' },
  { key: 'validate_research_run', title: '产物完整性检查', owner: 'Python 研究引擎', output: 'factor_research_stage_results', detail: '检查面板、IC、模型、推理、压力报告和准入结果是否齐全。' }
]

const validationRows = [
  ['IC', 'Pearson 横截面相关', '判断线性预测力', '月频/周频'],
  ['Rank IC', 'Spearman 排名相关', '判断选股排序能力', '主指标'],
  ['ICIR', 'IC 均值 / IC 波动', '判断稳定性', '分段检查'],
  ['分层回测', 'Q1-Q5 未来收益', '判断单调性', '必须看图'],
  ['多空收益', 'Top - Bottom', '判断强弱分离', '扣成本前后'],
  ['中性化对照', '原始 / 行业 / 市值 / 流动性', '剥离暴露', '保留多版本']
]

function currentResearchEndDate() {
  const today = new Date()
  const year = today.getFullYear()
  const month = String(today.getMonth() + 1).padStart(2, '0')
  const day = String(today.getDate()).padStart(2, '0')
  return `${year}${month}${day}`
}

function statusClass(status: FactorFamily['status'] | PipelineStep['status']) {
  if (status === 'ready' || status === '已完成') return 'success'
  if (status === 'design' || status === '运行中' || status === '排队中') return 'running'
  if (status === '失败' || status === '已取消') return 'failed'
  return 'created'
}

function statusText(status: FactorFamily['status']) {
  if (status === 'ready') return '已有雏形'
  if (status === 'design') return '待实现'
  return '后续扩展'
}

export function FactorResearchPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [activeTab, setActiveTab] = useState<ResearchTab>('recommend')
  const [tasks, setTasks] = useState<TaskDTO[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [runs, setRuns] = useState<FactorResearchRunSummary[]>([])
  const [icRows, setIcRows] = useState<FactorICResult[]>([])
  const [stateIcRows, setStateIcRows] = useState<FactorStateICResult[]>([])
  const [model, setModel] = useState<FactorModelRun | null>(null)
  const [modelFeatures, setModelFeatures] = useState<FactorModelFeature[]>([])
  const [predictions, setPredictions] = useState<FactorModelPrediction[]>([])
  const [latestPredictions, setLatestPredictions] = useState<FactorLatestPrediction[]>([])
  const [observationEvents, setObservationEvents] = useState<FactorObservationEvent[]>([])
  const [correlations, setCorrelations] = useState<FactorCorrelationResult[]>([])
  const [stressRows, setStressRows] = useState<FactorStressResult[]>([])
  const [admissionRows, setAdmissionRows] = useState<FactorAdmissionComparison[]>([])
  const [warningRuns, setWarningRuns] = useState<CrashWarningRunSummary[]>([])
  const [warningFeatures, setWarningFeatures] = useState<CrashWarningFeature[]>([])
  const modelSummary = useMemo(() => parseModelSummary(model?.summary_json), [model])
  const stressEvents = useMemo(() => stressRows.filter((row) => row.bucket_type === 'full' || row.bucket_type === 'event'), [stressRows])
  const stressYears = useMemo(() => stressRows.filter((row) => row.bucket_type === 'year'), [stressRows])
  const stressStates = useMemo(() => stressRows.filter((row) => row.bucket_type === 'market_state'), [stressRows])
  const latestAdmission = admissionRows[0]
  const latestWarningRun = warningRuns[0]
  const weakestStressRows = useMemo(() => [...stressRows]
    .filter((row) => row.bucket_type !== 'full')
    .sort((a, b) => a.annual_return - b.annual_return)
    .slice(0, 4), [stressRows])
  const parentTasks = useMemo(() => tasks.filter((task) => !task.parent_id), [tasks])
  const researchParentTasks = useMemo(() => parentTasks.filter((task) => task.task_type === 'factor_research'), [parentTasks])
  const latestInferenceTask = useMemo(() => parentTasks.find(isLatestInferenceTask), [parentTasks])
  const latestInferenceChild = useMemo(() => latestInferenceTask
    ? tasks.find((task) => task.parent_id === latestInferenceTask.id && task.subtask_key === 'latest_inference')
    : undefined, [latestInferenceTask, tasks])
  const latestTask = researchParentTasks.find((task) => !isLatestInferenceTask(task)) || researchParentTasks[0]
  const pipelineSteps = useMemo(() => buildPipelineSteps({
    task: latestTask,
    latestRun: runs[0],
    icRows,
    correlations,
    model,
    latestPredictions,
    stressRows,
    admissionRows
  }), [latestTask, runs, icRows, correlations, model, latestPredictions, stressRows, admissionRows])
  const runningTasks = parentTasks.filter((task) => task.status === 'running').length
  const queuedTasks = parentTasks.filter((task) => task.status === 'queued' || task.status === 'created').length
  const failedTasks = parentTasks.filter((task) => task.status === 'failed' || task.status === 'interrupted').length
  const totalFactors = factorFamilies.reduce((sum, item) => sum + item.count, 0)
  const readyFactors = factorFamilies.filter((item) => item.status === 'ready').reduce((sum, item) => sum + item.count, 0)
  const latestPredictionDate = latestPredictions[0]?.trade_date || ''
  const dailyRecommendations = useMemo(() => {
    const rows = latestPredictionDate
      ? latestPredictions.filter((row) => row.trade_date === latestPredictionDate)
      : latestPredictions
    return rows
      .filter((row) => row.is_top20)
      .sort((a, b) => b.pred_score - a.pred_score)
      .slice(0, 20)
  }, [latestPredictionDate, latestPredictions])
  const droppedObservationEvents = useMemo(() => observationEvents
    .filter((row) => row.event_type === 'dropped')
    .slice(0, 12), [observationEvents])
  const top10Recommendations = dailyRecommendations.slice(0, 10)
  const recommendationVerdict = model?.status === 'success' && dailyRecommendations.length > 0
    ? '可观察'
    : model?.status === 'success'
      ? '待推理'
      : '等待训练'
  const endDate = useMemo(() => currentResearchEndDate(), [])
  const startDate = useMemo(() => '20100101', [])

  const refresh = useCallback(async () => {
    const items = (await listTasks({ limit: 300 })).filter((item) => item.task_type === 'factor_research')
    setTasks(items)
    const runItems = await listFactorResearchRuns(20)
    setRuns(runItems)
    setAdmissionRows(await listFactorAdmissionComparisons(30))
    const crashRuns = await listCrashWarningRuns(10)
    setWarningRuns(crashRuns)
    setWarningFeatures(await listCrashWarningFeatures(crashRuns[0]?.run_id || '', 12))
    const latestRun = runItems[0]?.run_id || ''
    if (latestRun) {
      setIcRows(await listFactorICResults(latestRun, 80))
      setStateIcRows(await listFactorStateICResults(latestRun, 120))
      setModel(await getFactorModelRun(latestRun))
      setModelFeatures(await listFactorModelFeatures(latestRun, 24))
      setPredictions(await listFactorModelPredictions(latestRun, 80))
      setLatestPredictions(await listFactorLatestPredictions(latestRun, 80))
      setObservationEvents(await listFactorObservationEvents(80))
      setCorrelations(await listFactorCorrelationResults(latestRun, 80))
      setStressRows(await listFactorStressResults(latestRun, 160))
    } else {
      setIcRows([])
      setStateIcRows([])
      setModel(null)
      setModelFeatures([])
      setPredictions([])
      setLatestPredictions([])
      setObservationEvents([])
      setCorrelations([])
      setStressRows([])
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    const hasActiveTask = busy || runningTasks > 0 || queuedTasks > 0
    const intervalMs = hasActiveTask ? 3000 : 15000
    const timer = window.setInterval(() => {
      refresh()
    }, intervalMs)
    return () => window.clearInterval(timer)
  }, [busy, queuedTasks, refresh, runningTasks])

  const createAndStart = async (profile: 'smoke' | 'full') => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const params = profile === 'smoke'
        ? {
            start_date: '20200101',
            end_date: endDate,
            freq: 'monthly',
            label: 'fwd20_excess_industry',
            profile,
            min_train_years: 2,
            min_test_year: 2023,
            stress_aware: true
          }
        : {
            start_date: startDate,
            end_date: endDate,
            freq: 'monthly',
            label: 'fwd20_excess_industry',
            profile,
            min_train_years: 4,
            min_test_year: 2015,
            stress_aware: true
          }
      const task = await createTask({
        name: profile === 'smoke' ? `通用策略烟测-${params.start_date}-${params.end_date}` : `通用策略正式-${params.start_date}-${params.end_date}`,
        task_type: 'factor_research',
        params
      })
      await startTask(task.id)
      await refresh()
      setNotice(profile === 'smoke' ? '已启动通用策略烟测任务' : '已启动通用策略正式任务')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const startExistingTask = async (taskID: string) => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await startTask(taskID)
      await refresh()
      setNotice('已启动通用策略任务，Go 会按流水线顺序启动子阶段')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const refreshLatestInference = async () => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const task = await runFactorLatestInference()
      await refresh()
      setNotice(`已启动通用策略最新截面推理：${task.name || task.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="factorResearchPage">
      {notice ? <div className="saveHint">{notice}</div> : null}
      {error ? <div className="errorBanner">{error}</div> : null}

      <div className="pageTabsHeader">
        <div className="inlineTabs evaluationModeTabs signalViewTabs" role="tablist" aria-label="通用策略页签">
          {researchTabs.map((tab) => (
            <button key={tab.key} className={activeTab === tab.key ? 'active' : ''} onClick={() => setActiveTab(tab.key)}>
              {tab.label}
            </button>
          ))}
        </div>
        <div className="dataUpdatedPill">数据更新：{formatTradeDate(latestPredictionDate || runs[0]?.updated_at || '')}</div>
      </div>

      {activeTab === 'recommend' ? (
        <>
      {latestInferenceTask ? (
        <RunInferenceProgress parentTask={latestInferenceTask} childTask={latestInferenceChild} />
      ) : null}
      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">GENERAL STRATEGY</div>
            <h2>通用策略每日股票推荐</h2>
            <p className="recommendationMeta">基于通用因子模型的最新截面推理，每天给出 Top20% 候选；重新推理只使用当前模型跑最新行情截面，不重新训练模型。</p>
          </div>
          <div className="tableHeaderRight">
            <button className="secondaryButton startButton" onClick={refreshLatestInference} disabled={busy}>
              <RefreshCw size={16} />
              重新推理
            </button>
          </div>
        </div>

        <div className="metricStrip">
          <div className={`metricCard ${dailyRecommendations.length > 0 ? 'good' : ''}`}><span>策略结论</span><b>{recommendationVerdict}</b><em>{latestPredictionDate ? `${formatTradeDate(latestPredictionDate)} 截面` : '等待最新推理'}</em></div>
          <div className="metricCard"><span>今日推荐</span><b>{numberText(dailyRecommendations.length)}</b><em>Top20% 候选池</em></div>
          <div className="metricCard"><span>TOP10均值分位</span><b>{percentText(avg(top10Recommendations.map((row) => row.pred_rank)))}</b><em>分位越高，排序越靠前</em></div>
          <div className={`metricCard ${latestAdmission?.admission === '可启用' || latestAdmission?.admission === '可模拟' ? 'good' : ''}`}><span>准入状态</span><b>{latestAdmission?.admission || '待评估'}</b><em>{latestAdmission ? `评分 ${decimalText(latestAdmission.admission_score, 2)}` : '等待模型评估'}</em></div>
        </div>

        <div className="metricStrip">
          <div className="metricCard"><span>1 生成因子</span><b>{numberText(runs[0]?.factor_count || totalFactors)}</b><em>基础因子 + rank/neutral 版本</em></div>
          <div className={`metricCard ${model?.status === 'success' ? 'good' : ''}`}><span>2 训练模型</span><b>{model?.status || '-'}</b><em>{model?.model_type || 'LightGBM 等待训练'}</em></div>
          <div className={`metricCard ${latestPredictions.length > 0 ? 'good' : ''}`}><span>3 最新推理</span><b>{numberText(latestPredictions.length)}</b><em>当前截面候选</em></div>
          <div className="metricCard"><span>4 执行建议</span><b>{dailyRecommendations.length > 0 ? '观察建仓' : '不行动'}</b><em>先进入观察，不自动下单</em></div>
        </div>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">STOCK LIST</div>
            <h2>今日推荐股票列表</h2>
            <p className="recommendationMeta">观察池会保留入池日期、保留次数和刷新原因；Top10 给小仓建仓计划，后续候选只观察，不自动下单。</p>
          </div>
          <span>{latestPredictionDate ? `${formatTradeDate(latestPredictionDate)} · ${shortRunID(latestPredictions[0]?.run_id || '')}` : '暂无推荐截面'}</span>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>排名</th>
                <th>股票</th>
                <th>动作</th>
                <th>条件买入</th>
                <th>买入股数</th>
                <th>条件卖出</th>
                <th>卖出股数</th>
                <th>止损/停手</th>
                <th>验证 / 风险</th>
              </tr>
            </thead>
            <tbody>
              {dailyRecommendations.length === 0 ? (
                <tr><td colSpan={9} className="emptyCell">暂无每日通用策略推荐，请先在模型训练页完成正式全量并生成最新截面推理</td></tr>
              ) : dailyRecommendations.map((row, index) => {
                const plan = generalStrategyPlan(row, index)
                const executable = index < 10 && plan.shares > 0
                const displayAction = executable ? '可试仓' : '观察'
                return (
                  <tr key={`${row.run_id}-${row.trade_date}-${row.ts_code}`}>
                    <td><strong>{index + 1}</strong></td>
                    <td className="t0StockCell">
                      <button className="tableActionButton" onClick={() => onOpenResearch?.(row.ts_code)} title="查看个股研究">
                        {row.name || row.ts_code}
                      </button>
                      <div className="mono">{row.ts_code}</div>
                      <div className="recommendationMeta t0CurrentPrice">当前价 ¥{moneyText(row.price)}</div>
                      <div className="recommendationMeta">{row.industry || '—'} · {formatTradeDate(row.trade_date)}</div>
                      <div className="recommendationMeta">首次推荐 {formatTradeDate(row.first_seen_date)} · 观察 {numberText(row.observation_days)} 天</div>
                      <div className="recommendationMeta">保留 {numberText(row.seen_count)} 次 · {row.observation_result || '观察中'}</div>
                    </td>
                    <td>
                      <span className={`badge ${executable ? 'success' : 'running'}`}>{displayAction}</span>
                      <div className="recommendationMeta">{executable ? 'Top10 可按计划试仓' : '等组合和仓位确认'}</div>
                      <div className="recommendationMeta">今日 {percentFromPct(row.pct_chg, true)}</div>
                      <div className="recommendationMeta">保留原因：{row.observation_reason || 'Top20%模型候选'}</div>
                    </td>
                    <td>
                      <strong>¥{moneyText(plan.buy)}</strong>
                      <div className="recommendationMeta">回落到价再买</div>
                      <div className="recommendationMeta">现价下方 {priceDistance(row.price, plan.buy, 'down')}</div>
                      <div className="recommendationMeta">不到价不追</div>
                    </td>
                    <td>
                      <strong>{executable ? `${plan.shares} 股` : '不买'}</strong>
                      <div className="recommendationMeta">{executable ? '按1万元试仓估算' : '观察层不下单'}</div>
                      <div className="recommendationMeta">100股取整</div>
                    </td>
                    <td>
                      <strong>¥{moneyText(plan.sell)}</strong>
                      <div className="recommendationMeta">建仓后目标卖出价</div>
                      <div className="recommendationMeta">距当前 {priceDistance(row.price, plan.sell, 'up')}</div>
                      <div className="recommendationMeta">未触达不抢跑</div>
                    </td>
                    <td>
                      <strong>{executable ? `${plan.shares} 股` : '不卖'}</strong>
                      <div className="recommendationMeta">{executable ? '建仓后同股数卖出' : '未建仓无卖单'}</div>
                      <div className="recommendationMeta">先买后卖，不做裸卖</div>
                    </td>
                    <td>
                      <strong className="negative">¥{moneyText(plan.stop)}</strong>
                      <div className="recommendationMeta">跌破不建/减仓复核</div>
                      <div className="recommendationMeta">重新站回再评估</div>
                    </td>
                    <td>
                      <strong>{decimalText(row.pred_score, 4)}</strong>
                      <div className="recommendationMeta">分位 {percentText(row.pred_rank)}</div>
                      <div className="recommendationMeta">保留原因：{row.observation_reason || 'Top20%模型候选'}</div>
                      <div className="recommendationMeta">{observationStatusText(row.observation_status)} · 未来20日行业相对收益排序</div>
                      <div className="recommendationMeta">{latestAdmission ? admissionRiskText(latestAdmission) : '待准入评估'} · 不自动成交</div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">OBSERVATION HISTORY</div>
            <h2>最近移出观察池</h2>
            <p className="recommendationMeta">每天刷新 Top20% 后，如果股票不再进入推荐池，会在这里保留移出日期、入池日期和移出原因。</p>
          </div>
          <span>{droppedObservationEvents.length > 0 ? `最近 ${numberText(droppedObservationEvents.length)} 条移出记录` : '暂无移出记录'}</span>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>移出日期</th>
                <th>股票</th>
                <th>状态</th>
                <th>入池/保留</th>
                <th>模型分数</th>
                <th>预测分位</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>
              {droppedObservationEvents.length === 0 ? (
                <tr><td colSpan={7} className="emptyCell">暂无移出记录；刷新产生变化后会在这里留下为什么被刷掉的历史</td></tr>
              ) : droppedObservationEvents.map((row) => (
                <tr key={`${row.run_id}-${row.trade_date}-${row.ts_code}-${row.event_type}`}>
                  <td className="mono">{formatTradeDate(row.trade_date)}</td>
                  <td className="t0StockCell">
                    <button className="tableActionButton" onClick={() => onOpenResearch?.(row.ts_code)} title="查看个股研究">
                      {row.name || row.ts_code}
                    </button>
                    <div className="mono">{row.ts_code}</div>
                    <div className="recommendationMeta">{row.industry || '—'}</div>
                  </td>
                  <td><span className="badge failed">{observationEventText(row.event_type)}</span></td>
                  <td>
                    <strong>{formatTradeDate(row.first_seen_date)}</strong>
                    <div className="recommendationMeta">保留 {numberText(row.seen_count)} 次</div>
                    <div className="recommendationMeta">最近在池 {formatTradeDate(row.last_seen_date)}</div>
                  </td>
                  <td>{decimalText(row.score, 4)}</td>
                  <td>{percentText(row.rank_pct)}</td>
                  <td>
                    <strong>{row.reason || '未进入本次Top20候选'}</strong>
                    <div className="recommendationMeta">{shortRunID(row.run_id)} · {observationStatusText(row.observation_status)}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
        </>
      ) : null}

      {activeTab === 'model' ? (
        <>
      <FactorAdmissionPanel
        rows={admissionRows}
        latestPredictionDate={latestPredictionDate}
      />

      <section className="detailCard">
          <div className="tableHeader">
            <div>
              <div className="sectionLabel">PIPELINE</div>
              <h3>自动研究流水线</h3>
            </div>
            <span>{latestTask ? `${latestTask.name} · ${statusLabel(latestTask.status)}` : '暂无进行中的通用策略任务'}</span>
            <div className="tableHeaderRight">
              <button className="secondaryButton startButton" onClick={() => createAndStart('smoke')} disabled={busy} title="2020 至今快速跑通完整链路">
                <DatabaseZap size={16} />
                烟测闭环
              </button>
              <button className="primaryButton startButton" onClick={() => createAndStart('full')} disabled={busy} title="2010 至今正式全量策略研究">
                <Play size={16} />
                正式全量
              </button>
            </div>
          </div>
          <div className="factorPipeline">
            {pipelineSteps.map((step, index) => (
              <div className="factorStep" key={step.key}>
                <div className="factorStepIcon">{index + 1}</div>
                <div>
                  <div className="factorStepTitle">
                    <strong>{step.title}</strong>
                    <span className={`badge ${statusClass(step.status)}`}>{step.status}</span>
                  </div>
                  <p>{step.detail}</p>
                  <div className="factorStepMeta">
                    <span>{step.owner}</span>
                    <code>{step.output}</code>
                  </div>
                </div>
              </div>
            ))}
          </div>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">RUNS</div>
            <h3>任务执行监控</h3>
          </div>
          <span>Go 负责任务队列和阶段编排，Python 执行计算并把阶段结果写入 MySQL</span>
        </div>
        <div className="metricStrip">
          <div className="metricCard"><span>父任务数</span><b>{numberText(parentTasks.length)}</b><em>只展示可手动启动的研究任务</em></div>
          <div className="metricCard good"><span>运行中</span><b>{numberText(runningTasks)}</b><em>正在执行的 worker</em></div>
          <div className="metricCard"><span>排队/待启动</span><b>{numberText(queuedTasks)}</b><em>created 需要点击启动</em></div>
          <div className="metricCard bad"><span>失败/中断</span><b>{numberText(failedTasks)}</b><em>需要重跑或看日志</em></div>
        </div>
        <table>
          <thead>
            <tr>
              <th>任务</th>
              <th>状态</th>
              <th>进度</th>
              <th>当前步骤</th>
              <th>样本</th>
              <th>因子</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {parentTasks.length === 0 ? (
              <tr><td colSpan={8} className="mutedText">暂无通用策略任务</td></tr>
            ) : parentTasks.slice(0, 12).map((task) => {
              const rows = Array.isArray(task.summary.rows) ? task.summary.rows as Array<Record<string, unknown>> : []
              const panel = rows.find((row) => row.stage === 'build_factor_panel') || {}
              const running = rows.find((row) => row.task_status === 'running') || {}
              const message = factorTaskMessage(task, running)
              return (
                <tr key={task.id}>
                  <td>
                    <b>{task.name}</b>
                    <div className="mono">{task.external_run_id}</div>
                  </td>
                  <td><span className={`badge ${task.status}`}>{statusLabel(task.status)}</span></td>
                  <td>{Math.round((task.progress || 0) * 100)}%</td>
                  <td>{message}</td>
                  <td>{numberText(panel.sample_rows)} / {numberText(panel.sample_dates)}期</td>
                  <td>{numberText(panel.factor_count)}</td>
                  <td className="mono">{task.updated_at || task.created_at}</td>
                  <td>
                    {canStartTask(task.status) ? (
                      <button className="secondaryButton startButton" onClick={() => startExistingTask(task.id)} disabled={busy}>
                        {task.status === 'created' || task.status === 'queued' ? '启动' : '重启'}
                      </button>
                    ) : (
                      <span className="mutedText">-</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>
        </>
      ) : null}

      {activeTab === 'evaluation' ? (
        <>
      <GeneralModelEvaluationPanel
        model={model}
        predictions={predictions}
        latestPredictions={latestPredictions}
        stressYears={stressYears}
        modelFeatures={modelFeatures}
        admissionRows={admissionRows}
      />

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">FACTOR LIBRARY</div>
            <h3>第一版因子目录</h3>
          </div>
          <span>当前 105 个基础因子，模型训练使用 rank 与 neutral 版本</span>
        </div>
        <div className="factorFamilyGrid">
          {factorFamilies.map((family) => (
            <article className="factorFamilyCard" key={family.name}>
              <div className="factorFamilyTop">
                <strong>{family.name}</strong>
                <span className={`badge ${statusClass(family.status)}`}>{statusText(family.status)}</span>
              </div>
              <div className="factorCount">{family.count}</div>
              <p>{family.examples}</p>
              <em>{family.role}</em>
            </article>
          ))}
        </div>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">VALIDATION</div>
            <h3>因子检验矩阵</h3>
          </div>
          <FlaskConical size={22} />
        </div>
        <table>
          <thead>
            <tr>
              <th>检验</th>
              <th>计算方式</th>
              <th>用途</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            {validationRows.map((row) => (
              <tr key={row[0]}>
                <td><b>{row[0]}</b></td>
                <td>{row[1]}</td>
                <td>{row[2]}</td>
                <td className="mono">{row[3]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">LIVE RESULTS</div>
            <h3>最新真实因子检验</h3>
          </div>
          <span>{runs[0]?.run_id || '暂无 run'} · {runs[0]?.label || 'fwd20_excess_industry'}</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>因子</th>
              <th>版本</th>
              <th>类别</th>
              <th>Rank IC</th>
              <th>胜率</th>
              <th>ICIR</th>
              <th>多空收益</th>
              <th>单调性</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {icRows.length === 0 ? (
              <tr><td colSpan={9} className="mutedText">暂无真实 IC 结果</td></tr>
            ) : icRows.slice(0, 20).map((row) => (
              <tr key={`${row.run_id}-${row.factor}-${row.variant}`}>
                <td><b>{factorLabel(row.factor)}</b><div className="mono">{row.factor}</div></td>
                <td><span className={`badge ${row.variant === 'neutral' ? 'success' : 'created'}`}>{variantLabel(row.variant)}</span></td>
                <td>{row.family}</td>
                <td className={row.rank_ic_mean >= 0 ? 'positive' : 'negative'}>{decimalText(row.rank_ic_mean, 4)}</td>
                <td>{percentText(row.ic_win_rate)}</td>
                <td>{decimalText(row.icir, 2)}</td>
                <td className={row.long_short_return >= 0 ? 'positive' : 'negative'}>{percentText(row.long_short_return)}</td>
                <td>{percentText(row.monotonic_score, 0)}</td>
                <td><span className={`badge ${row.status === 'ready' ? 'success' : row.status === 'watch' ? 'running' : 'failed'}`}>{factorStatusLabel(row.status)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">STATE IC</div>
            <h3>市场状态因子强弱</h3>
          </div>
          <span>优先看急跌、弱势和流动性挤压状态下仍有 Rank IC 的因子</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>市场状态</th>
              <th>因子</th>
              <th>版本</th>
              <th>类别</th>
              <th>Rank IC</th>
              <th>胜率</th>
              <th>ICIR</th>
              <th>期数</th>
              <th>样本</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {stateIcRows.length === 0 ? (
              <tr><td colSpan={10} className="mutedText">暂无市场状态 IC，跑完因子检验后生成</td></tr>
            ) : stateIcRows.slice(0, 36).map((row) => (
              <tr key={`${row.run_id}-${row.market_state}-${row.factor}-${row.variant}`}>
                <td><span className={`badge ${marketStateBadge(row.market_state)}`}>{marketStateLabel(row.market_state)}</span></td>
                <td><b>{factorLabel(row.factor)}</b><div className="mono">{row.factor}</div></td>
                <td>{variantLabel(row.variant)}</td>
                <td>{row.family}</td>
                <td className={row.rank_ic_mean >= 0 ? 'positive' : 'negative'}>{decimalText(row.rank_ic_mean, 4)}</td>
                <td>{percentText(row.ic_win_rate)}</td>
                <td>{decimalText(row.icir, 2)}</td>
                <td>{numberText(row.n_periods)}</td>
                <td>{numberText(row.n_obs)}</td>
                <td><span className={`badge ${row.status === 'ready' ? 'success' : row.status === 'watch' ? 'running' : 'failed'}`}>{factorStatusLabel(row.status)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
        </>
      ) : null}

      {activeTab === 'model' ? (
        <>
      <section className="detailCard factorModelCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">MODEL DESIGN</div>
            <h3>LightGBM 设计</h3>
          </div>
          <BrainCircuit size={22} />
        </div>
        <div className="modelChecklist">
          <div><CheckCircle2 size={16} /><span>Label 使用未来 20 日行业相对收益</span></div>
          <div><ShieldCheck size={16} /><span>训练集按 walk-forward 滚动，禁止随机切分</span></div>
          <div><Layers3 size={16} /><span>特征保留 raw、rank、neutralized 多版本</span></div>
          <div><BarChart3 size={16} /><span>输出预测分数后进入组合约束</span></div>
        </div>
        <div className="factorFormula">
          <span>主标签</span>
          <code>fwd20_return - industry_fwd20_return</code>
        </div>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">MODEL STATUS</div>
            <h3>LightGBM 训练状态</h3>
          </div>
          <BrainCircuit size={22} />
        </div>
        {model ? (
          <div className="factorModelSummary">
            <div><span>模型</span><b>{model.model_type}</b></div>
            <div><span>特征数</span><b>{numberText(model.feature_count)}</b></div>
            <div><span>OOS Rank IC</span><b>{decimalText(model.rank_ic, 4)}</b></div>
            <div><span>Top-Bottom</span><b>{percentText(model.top_bottom_spread)}</b></div>
            <div><span>预测行数</span><b>{numberText(modelSummary.prediction_rows)}</b></div>
            <div><span>Top候选</span><b>{numberText(modelSummary.top20_rows)}</b></div>
            <div className="wide"><span>模型文件</span><code>{model.model_path || '等待生成'}</code></div>
          </div>
        ) : (
          <div className="mutedText">暂无模型训练记录</div>
        )}
        <div className="subTableTitle">模型特征重要度</div>
        <table>
          <thead>
            <tr>
              <th>排名</th>
              <th>特征</th>
              <th>基础因子</th>
              <th>版本</th>
              <th>重要度</th>
            </tr>
          </thead>
          <tbody>
            {modelFeatures.length === 0 ? (
              <tr><td colSpan={5} className="mutedText">暂无模型特征重要度</td></tr>
            ) : modelFeatures.slice(0, 16).map((row) => (
              <tr key={`${row.run_id}-${row.feature}`}>
                <td>{row.rank_no}</td>
                <td><b>{featureDisplayName(row.feature)}</b><div className="mono">{row.feature}</div></td>
                <td>{factorLabel(baseFactor(row.feature))}</td>
                <td>{featureVariantLabel(row.feature)}</td>
                <td>{decimalText(row.importance, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

        </>
      ) : null}

      {activeTab === 'evaluation' ? (
        <>
      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">CRASH WARNING</div>
            <h3>股灾预警模型</h3>
          </div>
          <span>{latestWarningRun?.run_id || '暂无预警模型'}</span>
        </div>
        <div className="metricStrip">
          <div className="metricCard good"><span>AUC</span><b>{decimalText(latestWarningRun?.roc_auc, 4)}</b><em>{latestWarningRun?.model_type || '-'}</em></div>
          <div className="metricCard"><span>AP</span><b>{decimalText(latestWarningRun?.avg_precision, 4)}</b><em>正样本 {percentText(latestWarningRun?.positive_rate)}</em></div>
          <div className="metricCard"><span>Top10 命中</span><b>{percentText(latestWarningRun?.top10_precision)}</b><em>捕获 {percentText(latestWarningRun?.top10_capture)}</em></div>
          <div className="metricCard"><span>样本</span><b>{numberText(latestWarningRun?.rows)}</b><em>{dateRangeText(latestWarningRun?.start_date, latestWarningRun?.end_date)}</em></div>
        </div>
        <table>
          <thead>
            <tr>
              <th>排名</th>
              <th>特征</th>
              <th>重要度</th>
            </tr>
          </thead>
          <tbody>
            {warningFeatures.length === 0 ? (
              <tr><td colSpan={3} className="mutedText">暂无预警特征重要度</td></tr>
            ) : warningFeatures.map((row) => (
              <tr key={`${row.run_id}-${row.feature}`}>
                <td>{row.rank_no}</td>
                <td><b>{factorLabel(baseFactor(row.feature))}</b><div className="mono">{row.feature}</div></td>
                <td>{decimalText(row.importance, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">STRESS REPORT</div>
            <h3>模型压力分段</h3>
          </div>
          <span>按事件、年份、市场状态检查失效区间</span>
        </div>
        {weakestStressRows.length > 0 ? (
          <>
            <div className="subTableTitle">最弱压力区间</div>
            <StressTable rows={weakestStressRows} emptyText="暂无最弱压力区间" compact />
          </>
        ) : null}
        <StressTable rows={stressEvents} emptyText="暂无事件压力测试，跑完 stress_report 后生成" />
        {stressStates.length > 0 ? (
          <>
            <div className="subTableTitle">市场状态</div>
            <StressTable rows={stressStates} emptyText="暂无市场状态分段" compact />
          </>
        ) : null}
        {stressYears.length > 0 ? (
          <>
            <div className="subTableTitle">年度分段</div>
            <StressTable rows={stressYears.slice(0, 20)} emptyText="暂无年度分段" compact />
          </>
        ) : null}
      </section>
        </>
      ) : null}

      {activeTab === 'evaluation' ? (
        <>
      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">MODEL PICKS</div>
            <h3>最新模型候选</h3>
          </div>
          <span>OOS 预测 Top 20%，按最近测试日期和模型分数排序</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>股票</th>
              <th>预测分数</th>
              <th>预测分位</th>
              <th>实际20日超额</th>
              <th>测试年</th>
            </tr>
          </thead>
          <tbody>
            {predictions.length === 0 ? (
              <tr><td colSpan={6} className="mutedText">暂无模型候选，训练成功后生成</td></tr>
            ) : predictions.slice(0, 30).map((row) => (
              <tr key={`${row.run_id}-${row.trade_date}-${row.ts_code}`}>
                <td className="mono">{row.trade_date}</td>
                <td><b>{row.ts_code}</b></td>
                <td>{decimalText(row.pred_score, 4)}</td>
                <td>{percentText(row.pred_rank)}</td>
                <td className={row.realized_return >= 0 ? 'positive' : 'negative'}>{percentText(row.realized_return)}</td>
                <td>{row.test_year}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">LATEST INFERENCE</div>
            <h3>最新截面候选池</h3>
          </div>
          <span>{latestPredictions[0]?.trade_date || '暂无截面'} · 使用生效 LightGBM 模型直接推理</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>股票</th>
              <th>预测分数</th>
              <th>预测分位</th>
              <th>Top20%</th>
            </tr>
          </thead>
          <tbody>
            {latestPredictions.length === 0 ? (
              <tr><td colSpan={5} className="mutedText">暂无最新截面推理结果</td></tr>
            ) : latestPredictions.slice(0, 30).map((row) => (
              <tr key={`${row.run_id}-${row.trade_date}-${row.ts_code}`}>
                <td className="mono">{row.trade_date}</td>
                <td><b>{row.ts_code}</b></td>
                <td>{decimalText(row.pred_score, 4)}</td>
                <td>{percentText(row.pred_rank)}</td>
                <td><span className={`badge ${row.is_top20 ? 'success' : 'created'}`}>{row.is_top20 ? '是' : '否'}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
        </>
      ) : null}

      {activeTab === 'evaluation' ? (
        <>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">CORRELATION REPORT</div>
            <h3>因子相关性与剔除原因</h3>
          </div>
          <span>按 Spearman 绝对相关性排序，高相关因子只保留代表特征</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>特征A</th>
              <th>特征B</th>
              <th>相关性</th>
              <th>保留</th>
              <th>剔除</th>
              <th>原因</th>
            </tr>
          </thead>
          <tbody>
            {correlations.length === 0 ? (
              <tr><td colSpan={6} className="mutedText">暂无相关性报告</td></tr>
            ) : correlations.slice(0, 30).map((row) => (
              <tr key={`${row.run_id}-${row.feature_a}-${row.feature_b}`}>
                <td><b>{factorLabel(baseFactor(row.feature_a))}</b><div className="mono">{row.feature_a}</div></td>
                <td><b>{factorLabel(baseFactor(row.feature_b))}</b><div className="mono">{row.feature_b}</div></td>
                <td className={row.correlation >= 0 ? 'positive' : 'negative'}>{decimalText(row.correlation, 4)}</td>
                <td><span className="badge success">{row.keep_feature}</span></td>
                <td><span className="badge failed">{row.drop_feature}</span></td>
                <td>{row.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
        </>
      ) : null}
    </div>
  )
}

function GeneralModelEvaluationPanel({
  model,
  predictions,
  latestPredictions,
  stressYears,
  modelFeatures,
  admissionRows
}: {
  model: FactorModelRun | null
  predictions: FactorModelPrediction[]
  latestPredictions: FactorLatestPrediction[]
  stressYears: FactorStressResult[]
  modelFeatures: FactorModelFeature[]
  admissionRows: FactorAdmissionComparison[]
}) {
  const summary = parseModelSummary(model?.summary_json)
  const tiers = buildFactorPredictionTiers(predictions)
  const yearly = buildFactorYearRows(predictions)
  const tradeRows = buildFactorTradeValidation(predictions)
  const recentDates = Array.from(new Set(predictions.map((row) => row.trade_date))).sort().reverse().slice(0, 10)
  const recentRows = recentDates.map((date) => {
    const dateRows = predictions.filter((row) => row.trade_date === date).sort((a, b) => b.pred_score - a.pred_score)
    const top = dateRows.slice(0, 10)
    return {
      date,
      count: dateRows.length,
      topReturn: avg(top.map((row) => row.realized_return)),
      rankIC: Number.NaN,
    }
  })
  const bestAdmission = admissionRows
    .filter((row) => row.admission.includes('启用') || row.admission.includes('准入') || row.admission.includes('限制'))
    .sort((a, b) => b.admission_score - a.admission_score)[0]
  const latestDate = latestPredictions[0]?.trade_date || ''
  const activeSummary = model ? `${model.model_type} · ${model.status}` : '暂无模型'
  return (
    <section className="detailCard">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">MODEL EVALUATION</div>
          <h3>通用策略效果评估</h3>
        </div>
        <span>{latestDate ? `最新截面 ${formatTradeDate(latestDate)}` : activeSummary}</span>
      </div>
      <div className="limitModelVerdict">
        <div>
          <span className={bestAdmission ? 'positiveText' : model?.status === 'success' ? 'warningText' : 'negativeText'}>
            {bestAdmission ? bestAdmission.admission : model?.status === 'success' ? '可观察' : '等待训练'}
          </span>
          <b>{model?.run_id ? shortRunID(model.run_id) : '等待模型'}</b>
          <p>
            {model
              ? `OOS Rank IC ${decimalText(summary.oos_rank_ic_mean, 3)}，Top-Bottom ${signedPercentText(summary.top_bottom_spread)}，Top20均值 ${signedPercentText(summary.top20_mean_return)}；准入仍需看压力段和最新截面。`
              : '暂无通用策略模型评估结果。'}
          </p>
        </div>
        <div className="limitModelMetrics">
          <Mini label="OOS折数" value={numberText(summary.fold_count)} />
          <Mini label="预测样本" value={numberText(summary.prediction_rows)} />
          <Mini label="Top候选" value={numberText(summary.top20_rows)} />
          <Mini label="Rank IC" value={decimalText(summary.oos_rank_ic_mean, 3)} valueClassName={Number(summary.oos_rank_ic_mean) >= 0 ? 'positive' : 'negative'} />
          <Mini label="Top-Bottom" value={signedPercentText(summary.top_bottom_spread)} valueClassName={Number(summary.top_bottom_spread) >= 0 ? 'positive' : 'negative'} />
          <Mini label="准入分" value={bestAdmission ? decimalText(bestAdmission.admission_score, 2) : '—'} />
        </div>
      </div>

      <div className="limitModelEvalGrid">
        <div>
          <div className="formTitle">Top 分层表现</div>
          <div className="modelEvalTableWrap">
            <table className="modelEvalTable">
              <thead>
                <tr>
                  <th>层级</th>
                  <th>单期超额</th>
                  <th>命中率</th>
                  <th>样本</th>
                </tr>
              </thead>
              <tbody>
                {tiers.length === 0 ? (
                  <tr><td colSpan={4}>暂无 OOS 分层结果</td></tr>
                ) : tiers.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    <td className={row.avgReturn >= 0 ? 'positive' : 'negative'}>{signedPercentText(row.avgReturn)}</td>
                    <td>{percentText(row.winRate)}</td>
                    <td>{numberText(row.count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div>
          <div className="formTitle">分年 Walk-forward</div>
          <div className="modelEvalTableWrap">
            <table className="modelEvalTable">
              <thead>
                <tr>
                  <th>年份</th>
                  <th>Top10超额</th>
                  <th>命中率</th>
                  <th>样本</th>
                </tr>
              </thead>
              <tbody>
                {yearly.length === 0 ? (
                  <tr><td colSpan={4}>暂无分年结果</td></tr>
                ) : yearly.map((row) => (
                  <tr key={row.year}>
                    <td>{row.year}</td>
                    <td className={row.avgReturn >= 0 ? 'positive' : 'negative'}>{signedPercentText(row.avgReturn)}</td>
                    <td>{percentText(row.winRate)}</td>
                    <td>{numberText(row.count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="formTitle">交易层验证</div>
      <div className="cardHint">通用策略没有日内触价条件，这里按每个测试截面 TopN 等权持有 20 日超额做近似验证；真实执行仍以推荐页条件单价格为准。</div>
      <div className="modelEvalTableWrap">
        <table className="modelEvalTable">
          <thead>
            <tr>
              <th>规则</th>
              <th>截面/信号</th>
              <th>胜率</th>
              <th>单期超额</th>
              <th>累计近似</th>
              <th>最大回撤</th>
            </tr>
          </thead>
          <tbody>
            {tradeRows.length === 0 ? (
              <tr><td colSpan={6}>暂无交易层验证</td></tr>
            ) : tradeRows.map((row) => (
              <tr key={row.label}>
                <td>{row.label}</td>
                <td>{row.periods}/{row.signals}</td>
                <td>{percentText(row.winRate)}</td>
                <td className={row.avgReturn >= 0 ? 'positive' : 'negative'}>{signedPercentText(row.avgReturn)}</td>
                <td className={row.compoundReturn >= 0 ? 'positive' : 'negative'}>{signedPercentText(row.compoundReturn)}</td>
                <td className={row.maxDrawdown >= -0.2 ? 'positive' : 'negative'}>{signedPercentText(row.maxDrawdown)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="limitModelEvalGrid">
        <div>
          <div className="formTitle">最近评测切面</div>
          <div className="limitModelList">
            {recentRows.length === 0 ? <div className="taskGridEmpty compactEmpty">暂无最近评测切面</div> : recentRows.map((row) => (
              <div className="limitModelSliceRow" key={row.date}>
                <b>{formatTradeDate(row.date)}</b>
                <span>候选 {row.count} · Top10超额 {signedPercentText(row.topReturn)}</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div className="formTitle">重要特征</div>
          <div className="limitModelFeatureList">
            {modelFeatures.length === 0 ? <div className="taskGridEmpty compactEmpty">暂无特征重要性</div> : modelFeatures.slice(0, 8).map((row) => (
              <span key={`${row.run_id}-${row.feature}`}>{row.rank_no}. {featureDisplayName(row.feature)}</span>
            ))}
          </div>
        </div>
      </div>

      {stressYears.length > 0 ? (
        <>
          <div className="subTableTitle">压力年份</div>
          <StressTable rows={stressYears.slice(0, 8)} emptyText="暂无年度压力分段" compact />
        </>
      ) : null}
    </section>
  )
}

function buildFactorPredictionTiers(rows: FactorModelPrediction[]) {
  return [1, 3, 5, 10].map((topN) => {
    const selected = topRowsPerDate(rows, topN)
    return {
      label: `Top${topN}`,
      count: selected.length,
      avgReturn: avg(selected.map((row) => row.realized_return)),
      winRate: avg(selected.map((row) => row.realized_return > 0 ? 1 : 0)),
    }
  }).filter((row) => row.count > 0)
}

function buildFactorYearRows(rows: FactorModelPrediction[]) {
  const years = Array.from(new Set(rows.map((row) => row.test_year).filter(Number.isFinite))).sort((a, b) => a - b)
  return years.map((year) => {
    const selected = topRowsPerDate(rows.filter((row) => row.test_year === year), 10)
    return {
      year,
      count: selected.length,
      avgReturn: avg(selected.map((row) => row.realized_return)),
      winRate: avg(selected.map((row) => row.realized_return > 0 ? 1 : 0)),
    }
  }).filter((row) => row.count > 0)
}

function buildFactorTradeValidation(rows: FactorModelPrediction[]) {
  return [3, 5, 10].map((topN) => {
    const grouped = groupPredictionsByDate(rows)
    const returns = Array.from(grouped.values()).map((items) => avg(items.sort((a, b) => b.pred_score - a.pred_score).slice(0, topN).map((row) => row.realized_return))).filter(Number.isFinite)
    const equity = returns.reduce<{ peak: number; value: number; maxDrawdown: number }>((state, item) => {
      const value = state.value * (1 + item)
      const peak = Math.max(state.peak, value)
      const drawdown = peak > 0 ? value / peak - 1 : 0
      return { value, peak, maxDrawdown: Math.min(state.maxDrawdown, drawdown) }
    }, { value: 1, peak: 1, maxDrawdown: 0 })
    return {
      label: `Top${topN} / 20日持有`,
      periods: returns.length,
      signals: returns.length * topN,
      winRate: avg(returns.map((item) => item > 0 ? 1 : 0)),
      avgReturn: avg(returns),
      compoundReturn: equity.value - 1,
      maxDrawdown: equity.maxDrawdown,
    }
  }).filter((row) => row.periods > 0)
}

function topRowsPerDate(rows: FactorModelPrediction[], topN: number) {
  return Array.from(groupPredictionsByDate(rows).values()).flatMap((items) => items.sort((a, b) => b.pred_score - a.pred_score).slice(0, topN))
}

function groupPredictionsByDate(rows: FactorModelPrediction[]) {
  const grouped = new Map<string, FactorModelPrediction[]>()
  rows.forEach((row) => {
    const items = grouped.get(row.trade_date) || []
    items.push(row)
    grouped.set(row.trade_date, items)
  })
  return grouped
}

function StressTable({ rows, emptyText, compact = false }: { rows: FactorStressResult[], emptyText: string, compact?: boolean }) {
  return (
    <table className={compact ? 'compactTable' : ''}>
      <thead>
        <tr>
          <th>分段</th>
          <th>区间</th>
          <th>交易日</th>
          <th>总收益</th>
          <th>年化</th>
          <th>最大回撤</th>
          <th>胜率</th>
          <th>Sharpe</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr><td colSpan={8} className="mutedText">{emptyText}</td></tr>
        ) : rows.map((row) => (
          <tr key={`${row.bucket_type}-${row.bucket_key}`}>
            <td><b>{row.bucket_label}</b><div className="mono">{stressBucketType(row.bucket_type)}</div></td>
            <td className="mono">{row.start_date} - {row.end_date}</td>
            <td>{numberText(row.n_days)}</td>
            <td className={row.total_return >= 0 ? 'positive' : 'negative'}>{percentText(row.total_return)}</td>
            <td className={row.annual_return >= 0 ? 'positive' : 'negative'}>{percentText(row.annual_return)}</td>
            <td className={row.max_drawdown >= -0.2 ? 'positive' : 'negative'}>{percentText(row.max_drawdown)}</td>
            <td>{percentText(row.win_rate)}</td>
            <td>{decimalText(row.sharpe, 2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function buildPipelineSteps(input: {
  task?: TaskDTO
  latestRun?: FactorResearchRunSummary
  icRows: FactorICResult[]
  correlations: FactorCorrelationResult[]
  model: FactorModelRun | null
  latestPredictions: FactorLatestPrediction[]
  stressRows: FactorStressResult[]
  admissionRows: FactorAdmissionComparison[]
}): PipelineStep[] {
  const rows = taskRows(input.task)
  const rowsByStage = new Map(rows.map((row) => [String(row.stage || ''), row]))
  const activeRow = rows.find((row) => ['running', 'queued'].includes(String(row.status || row.task_status || '')))
  const hasTaskRows = rows.length > 0
  const taskStatus = input.task?.status || ''
  const liveTask = input.task && ['created', 'queued', 'running'].includes(taskStatus) ? input.task : null
  const hasLiveTask = Boolean(liveTask)
  const allArtifactsDone = Boolean(
    input.latestRun?.sample_rows &&
    input.icRows.length &&
    input.correlations.length &&
    input.model &&
    input.latestPredictions.length &&
    input.stressRows.length &&
    input.admissionRows.length
  )

  return pipelineBase.map((step, index) => {
    const row = rowsByStage.get(step.key)
    let status = row ? stageStatusLabel(String(row.status || row.task_status || '')) : '待执行'
    if (!hasTaskRows && !hasLiveTask) {
      status = inferredStageStatus(step.key, input, allArtifactsDone)
    }
    if (status === '待执行' && hasLiveTask) {
      const activeStage = String(activeRow?.stage || '')
      if (activeStage === step.key) {
        status = stageStatusLabel(String(activeRow?.status || activeRow?.task_status || liveTask?.status || ''))
      } else if (!activeStage && index === 0) {
        status = stageStatusLabel(liveTask?.status || '')
      }
    }
    return { ...step, status }
  })
}

function taskRows(task?: TaskDTO) {
  return Array.isArray(task?.summary?.rows) ? task.summary.rows as Array<Record<string, unknown>> : []
}

function isLatestInferenceTask(task: TaskDTO) {
  const profile = String(task.params?.profile || '')
  const stage = String(task.params?.stage || task.subtask_key || '')
  return profile === 'inference' || stage === 'latest_inference' || task.name.includes('重新推理')
}

function RunInferenceProgress({ parentTask, childTask }: { parentTask: TaskDTO; childTask?: TaskDTO }) {
  const task = childTask || parentTask
  if (parentTask.status === 'success' || task.status === 'success') return null
  const rows = taskRows(parentTask)
  const running = rows.find((row) => row.task_status === 'running' || row.status === 'running') || {}
  const progress = Math.max(0, Math.min(100, Math.round((Number(task.progress) || 0) * 100)))
  const stageName = String(task.summary.name || task.summary.stage_name || running.name || running.stage_name || '最新截面推理')
  const message = factorTaskMessage(task, running)
  const detail = task.status === 'success'
    ? '已完成'
    : task.status === 'failed' || task.status === 'interrupted' || task.status === 'cancelled'
      ? statusLabel(task.status)
      : `${progress}% · ${statusLabel(task.status)}`
  return (
    <div className="signalProgress signalProgressStandalone">
      <div className="signalProgressHeader">
        <span>{parentTask.name} · {stageName}</span>
        <span>{detail}</span>
      </div>
      <div className="signalProgressBar">
        <div className="signalProgressBarFill" style={{ width: `${task.status === 'success' ? 100 : progress}%` }} />
      </div>
      {message ? <div className={task.status === 'failed' ? 'errorText' : 'cardHint'}>{message}</div> : null}
    </div>
  )
}

function inferredStageStatus(
  key: string,
  input: {
    task?: TaskDTO
    latestRun?: FactorResearchRunSummary
    icRows: FactorICResult[]
    correlations: FactorCorrelationResult[]
    model: FactorModelRun | null
    latestPredictions: FactorLatestPrediction[]
    stressRows: FactorStressResult[]
    admissionRows: FactorAdmissionComparison[]
  },
  allArtifactsDone: boolean
): PipelineStep['status'] {
  if (key === 'build_factor_panel' && Number(input.latestRun?.sample_rows) > 0) return '已完成'
  if (key === 'evaluate_factors' && input.icRows.length > 0) return '已完成'
  if (key === 'factor_correlation_report' && input.correlations.length > 0) return '已完成'
  if (key === 'train_lgbm' && input.model) return '已完成'
  if (key === 'latest_inference' && input.latestPredictions.length > 0) return '已完成'
  if (key === 'stress_report' && input.stressRows.length > 0) return '已完成'
  if (key === 'strategy_admission' && input.admissionRows.length > 0) return '已完成'
  if (key === 'validate_research_run' && (allArtifactsDone || input.task?.status === 'success')) return '已完成'
  if (!input.task && !input.latestRun) return '待执行'
  return '待执行'
}

function stageStatusLabel(status: string): PipelineStep['status'] {
  if (status === 'success') return '已完成'
  if (status === 'running') return '运行中'
  if (status === 'queued') return '排队中'
  if (status === 'failed' || status === 'interrupted') return '失败'
  if (status === 'cancelled') return '已取消'
  return '待执行'
}

function canStartTask(status: string) {
  return ['created', 'queued', 'failed', 'interrupted', 'cancelled'].includes(status)
}

function factorTaskMessage(task: TaskDTO, running: Record<string, unknown>) {
  if (task.status === 'created') return '等待手动启动'
  if (task.status === 'queued') return '等待调度'
  if (task.status === 'failed' || task.status === 'interrupted' || task.status === 'cancelled') {
    return task.error_message || statusLabel(task.status)
  }
  if (task.status === 'success') return '完成'
  return String(task.summary.message || running.message || running.stage_name || running.stage || '-')
}

function stressBucketType(type: string) {
  return {
    full: '全周期',
    event: '事件',
    year: '年度',
    market_state: '市场状态'
  }[type] || type
}

function marketStateLabel(state: string) {
  return {
    normal: '常态',
    weak: '弱势',
    crash: '急跌',
    liquidity_squeeze: '流动性挤压',
    post_crash_repair: '急跌后修复'
  }[state] || state
}

function marketStateBadge(state: string) {
  if (state === 'crash' || state === 'liquidity_squeeze') return 'failed'
  if (state === 'weak') return 'running'
  if (state === 'post_crash_repair') return 'created'
  return 'success'
}

function parseModelSummary(raw?: string) {
  try {
    return raw ? JSON.parse(raw) as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function numberText(value: unknown) {
  const n = Number(value)
  return Number.isFinite(n) ? n.toLocaleString('zh-CN') : '-'
}

function moneyText(value: unknown) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return '-'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function roundLotShares(price: number, cash: number) {
  if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(cash) || cash <= 0) return 0
  return Math.floor(cash / price / 100) * 100
}

function avg(values: unknown[]) {
  const nums = values.map(Number).filter(Number.isFinite)
  if (nums.length === 0) return Number.NaN
  return nums.reduce((sum, value) => sum + value, 0) / nums.length
}

function decimalText(value: unknown, digits = 2) {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(digits) : '-'
}

function percentText(value: unknown, digits = 2) {
  const n = Number(value)
  return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : '-'
}

function signedPercentText(value: unknown, digits = 2) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return `${n > 0 ? '+' : ''}${(n * 100).toFixed(digits)}%`
}

function percentFromPct(value: unknown, signed = false) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  const sign = signed && n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function priceDistance(base: number, target: number, direction: 'up' | 'down') {
  if (!Number.isFinite(base) || base <= 0 || !Number.isFinite(target) || target <= 0) return '-'
  const value = direction === 'up' ? target / base - 1 : 1 - target / base
  return percentText(value)
}

function generalStrategyPlan(row: FactorLatestPrediction, index: number): GeneralStrategyPlan {
  const price = Number(row.price)
  if (!Number.isFinite(price) || price <= 0) {
    return { buy: Number.NaN, sell: Number.NaN, stop: Number.NaN, shares: 0 }
  }
  const rank = Number.isFinite(row.pred_rank) ? row.pred_rank : 0.8
  const buyBand = Math.max(0.006, Math.min(0.025, 0.026 - rank * 0.014))
  const sellBand = Math.max(0.025, Math.min(0.08, 0.028 + rank * 0.04))
  const stopBand = Math.max(0.035, Math.min(0.08, 0.075 - Math.min(rank, 1) * 0.025))
  const cash = index < 3 ? 10000 : index < 10 ? 6000 : 0
  const buy = price * (1 - buyBand)
  return {
    buy,
    sell: price * (1 + sellBand),
    stop: price * (1 - stopBand),
    shares: roundLotShares(buy, cash)
  }
}

function Mini({ label, value, valueClassName = '' }: { label: string; value: string; valueClassName?: string }) {
  return <div className="miniMetric compact"><span>{label}</span><b className={valueClassName}>{value}</b></div>
}

function observationStatusText(status: string) {
  if (status === 'active') return '观察池内'
  if (status === 'dropped') return '已移出观察池'
  return status || '观察记录'
}

function observationEventText(eventType: string) {
  if (eventType === 'entered') return '新入池'
  if (eventType === 'kept') return '继续保留'
  if (eventType === 'dropped') return '已移出'
  return eventType || '观察事件'
}

function formatTradeDate(value?: string) {
  if (!value) return '-'
  if (/^\d{8}$/.test(value)) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
    return value.slice(0, 10)
  }
  return value
}

function factorLabel(factor: string) {
  return {
    mkt_risk_score: '市场风险分',
    mkt_breadth20: '市场宽度',
    mkt_limit_down_ratio: '跌停占比',
    mkt_limit_down_ratio5: '5日跌停占比',
    mkt_amount_chg20: '市场成交变化',
    mkt_small_large_rel20: '小盘相对大盘',
    mkt_drawdown20: '市场20日回撤',
    mkt_drawdown60: '市场60日回撤',
    mkt_drawdown120: '市场120日回撤',
    mkt_trend60: '市场60日趋势',
    mkt_volatility20: '市场20日波动',
    mkt_state_normal: '常态哑变量',
    mkt_state_weak: '弱势哑变量',
    mkt_state_crash: '急跌哑变量',
    mkt_state_liquidity_squeeze: '流动性挤压哑变量',
    mkt_state_post_crash_repair: '急跌修复哑变量',
    turnover_rate: '低换手',
    vol20: '低波动',
    bp: 'BP',
    pb: '低PB',
    dv_ttm: '股息率',
    ep: 'EP',
    pe_ttm: '低PE',
    sp: 'SP',
    ps_ttm: '低PS',
    ocfps: '每股现金流',
    q_ocf_to_sales: '经营现金流率',
    q_op_qoq: '利润环比改善',
    q_sales_yoy: '收入同比',
    netprofit_yoy: '利润同比',
    log_circ_mv: '小市值'
  }[factor] || factor
}

function featureDisplayName(feature: string) {
  return factorLabel(baseFactor(feature))
}

function featureVariantLabel(feature: string) {
  if (feature.endsWith('_neutral')) return '中性化'
  if (feature.endsWith('_rank')) return '方向Rank'
  if (feature.startsWith('mkt_')) return '市场状态'
  return '原始'
}

function factorStatusLabel(status: string) {
  return { ready: '可用', watch: '观察', reject: '废弃' }[status] || status
}

function variantLabel(variant: string) {
  return { rank: '方向Rank', neutral: '中性化', raw: '旧版' }[variant] || variant
}

function baseFactor(feature: string) {
  return feature.replace(/_neutral$/, '').replace(/_rank$/, '')
}

function FactorAdmissionPanel({
  rows,
  latestPredictionDate
}: {
  rows: FactorAdmissionComparison[]
  latestPredictionDate: string
}) {
  const admissionRows = rows.slice(0, 10).map((row) => buildFactorAdmission(row, latestPredictionDate))
  const enabled = admissionRows.find((row) => row.active)
  const bestGoverned = admissionRows.reduce<FactorAdmissionView | null>((memo, row) => {
    if (!row.canEnable) return memo
    return !memo || row.score > memo.score ? row : memo
  }, null)
  const bestScored = admissionRows.reduce<FactorAdmissionView | null>((memo, row) => {
    return !memo || row.score > memo.score ? row : memo
  }, null)
  const current = enabled || bestGoverned || bestScored || admissionRows[0]
  return (
    <section className="detailCard modelVersionCompare">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">ADMISSION COMPARE</div>
          <h3>模型版本准入对比</h3>
        </div>
        <span>{enabled ? `启用中 ${shortRunID(enabled.row.run_id)}` : bestGoverned ? `建议启用 ${shortRunID(bestGoverned.row.run_id)}` : '暂无治理通过版本'}</span>
      </div>
      <div className="metricStrip">
        <div className={`metricCard ${enabled?.canEnable ? 'good' : enabled ? 'bad' : ''}`}>
          <span>当前启用</span>
          <b>{enabled ? enabled.admission : '暂无'}</b>
          <em>{enabled?.row.run_id || '未配置可用版本'}</em>
        </div>
        <div className="metricCard">
          <span>最高准入分</span>
          <b>{bestScored ? decimalText(bestScored.score, 2) : '—'}</b>
          <em>{bestScored ? `${bestScored.admission} · ${shortRunID(bestScored.row.run_id)}` : '等待训练结果'}</em>
        </div>
        <div className={`metricCard ${current?.needsRefresh ? 'bad' : 'good'}`}>
          <span>最新截面</span>
          <b>{current?.needsRefresh ? '需更新' : '已覆盖'}</b>
          <em>{current ? `版本 ${current.cutoffText} / 最新 ${formatTradeDate(latestPredictionDate)}` : '暂无准入记录'}</em>
        </div>
        <div className={`metricCard ${current?.complete ? 'good' : 'bad'}`}>
          <span>训练完整性</span>
          <b>{current?.complete ? '完整' : '不完整'}</b>
          <em>{current?.failure || '有效期、指标、压力和截面均通过'}</em>
        </div>
      </div>
      <div className="modelVersionTableWrap">
        <table className="modelVersionTable">
          <thead>
            <tr>
              <th>版本</th>
              <th>模型/治理</th>
              <th>完整性</th>
              <th>分数</th>
              <th>核心收益</th>
              <th>辅助指标</th>
              <th>风险</th>
              <th>排序指标</th>
              <th>训练区间</th>
              <th>评估员意见</th>
            </tr>
          </thead>
          <tbody>
            {admissionRows.length === 0 ? (
              <tr><td colSpan={10} className="mutedText">暂无模型准入记录</td></tr>
            ) : admissionRows.map((item) => (
              <tr key={`${item.row.run_id}-${item.row.generated_at}`}>
                <td>
                  <b>{item.active ? '已启用' : '候选版本'} · {shortRunID(item.row.run_id)}</b>
                  {item.active ? <span className="versionActiveTag">启用中</span> : null}
                  <div className="mono">{item.row.generated_at || '—'}</div>
                </td>
                <td><span className={`badge ${admissionBadge(item.admission)}`}>{item.admission}</span></td>
                <td><span className={`badge ${item.complete ? 'success' : 'failed'}`}>{item.complete ? '完整' : '不完整'}</span></td>
                <td>{decimalText(item.score, 2)}</td>
                <td className={item.row.annual_return >= 0 ? 'positive' : 'negative'}><b>年化</b><div>{percentText(item.row.annual_return)}</div></td>
                <td className={item.row.total_return >= 0 ? 'positive' : 'negative'}><b>总收益</b><div>{percentText(item.row.total_return)}</div></td>
                <td className={item.row.max_drawdown >= -0.2 ? 'positive' : 'negative'}><b>最大回撤</b><div>{percentText(item.row.max_drawdown)}</div></td>
                <td><b>Sharpe</b><div>{decimalText(item.row.sharpe, 2)}</div></td>
                <td>{dateRangeText(item.row.effective_start, item.row.effective_end)}</td>
                <td className="versionFailureText">{item.failure || item.row.reason || '训练日期、截面、收益回撤和压力检查通过，可进入候选启用。'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

type FactorAdmissionView = {
  row: FactorAdmissionComparison
  admission: string
  active: boolean
  complete: boolean
  canEnable: boolean
  needsRefresh: boolean
  score: number
  cutoffText: string
  failure: string
}

function buildFactorAdmission(row: FactorAdmissionComparison, latestPredictionDate: string): FactorAdmissionView {
  const latest = normalizeTradeDate(latestPredictionDate)
  const effectiveEnd = normalizeTradeDate(row.effective_end)
  const needsRefresh = Boolean(latest && effectiveEnd && effectiveEnd < latest)
  const issues: string[] = []
  if (!row.run_id) issues.push('缺少版本号')
  if (!row.effective_start || !row.effective_end) issues.push('缺少训练/有效区间')
  if (!row.generated_at) issues.push('缺少生成时间')
  if (!Number.isFinite(row.admission_score)) issues.push('缺少准入分')
  if (!Number.isFinite(row.annual_return) || !Number.isFinite(row.max_drawdown) || !Number.isFinite(row.sharpe)) issues.push('核心绩效指标不完整')
  if (row.stress_crash_state_failed || row.stress_weak_drawdown_failed || row.stress_bad_event_count > 0) issues.push(`压力失败：${admissionRiskText(row)}`)
  if (needsRefresh) issues.push('需要用最新截面重新训练/推理')
  const complete = issues.length === 0
  const score = Math.max(0, Math.min(100, Number(row.admission_score || 0)))
  const declaredEnable = row.admission.includes('启用') || row.admission.includes('准入')
  const metricUsable = score >= 45 && row.annual_return > 0 && row.total_return > 0 && row.max_drawdown > -0.3 && row.sharpe > 0
  const canEnable = complete && declaredEnable && row.annual_return > 0 && row.max_drawdown > -0.22 && row.sharpe > 0
  const admission = canEnable
    ? row.admission
    : complete
      ? '继续观察'
      : metricUsable
        ? '治理未完整'
        : '不可启用'
  return {
    row,
    admission,
    active: canEnable && declaredEnable,
    complete,
    canEnable,
    needsRefresh,
    score,
    cutoffText: row.effective_end ? formatTradeDate(row.effective_end) : '—',
    failure: issues.slice(0, 3).join(' / ')
  }
}

function normalizeTradeDate(value?: string) {
  if (!value) return ''
  const compact = value.replace(/-/g, '').slice(0, 8)
  return /^\d{8}$/.test(compact) ? compact : ''
}

function shortRunID(runID: string) {
  return runID.replace(/^eval_/, '').replace(/^ml_factor_/, '')
}

function dateRangeText(start?: string, end?: string) {
  if (!start && !end) return '-'
  return `${start || '-'} - ${end || '-'}`
}

function admissionBadge(admission: string) {
  if (admission === '通过' || admission === '可准入' || admission === '可启用' || admission === '可模拟') return 'success'
  if (admission === '继续观察' || admission === '观察' || admission === '治理未完整') return 'running'
  return 'failed'
}

function admissionRiskText(row: FactorAdmissionComparison) {
  const risks = []
  if (row.stress_crash_state_failed) risks.push('股灾状态')
  if (row.stress_weak_drawdown_failed) risks.push('弱市回撤')
  if (row.stress_bad_event_count > 0) risks.push(`${row.stress_bad_event_count}个事件`)
  return risks.length > 0 ? risks.join(' / ') : '无硬失败'
}

function statusLabel(status: string) {
  return {
    created: '待启动',
    queued: '排队中',
    running: '运行中',
    success: '完成',
    failed: '失败',
    cancelled: '取消',
    interrupted: '中断'
  }[status] || status
}

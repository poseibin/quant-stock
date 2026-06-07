import { useEffect, useMemo, useState } from 'react'
import { BarChart3, BrainCircuit, CheckCircle2, DatabaseZap, FlaskConical, Layers3, Play, RefreshCw, ShieldCheck } from 'lucide-react'
import { createTask, getFactorModelRun, listCrashWarningFeatures, listCrashWarningRuns, listFactorAdmissionComparisons, listFactorCorrelationResults, listFactorICResults, listFactorLatestPredictions, listFactorModelFeatures, listFactorModelPredictions, listFactorResearchRuns, listFactorStateICResults, listFactorStressResults, listTasks, startTask, type CrashWarningFeature, type CrashWarningRunSummary, type FactorAdmissionComparison, type FactorCorrelationResult, type FactorICResult, type FactorLatestPrediction, type FactorModelFeature, type FactorModelPrediction, type FactorModelRun, type FactorResearchRunSummary, type FactorStateICResult, type FactorStressResult, type TaskDTO } from '../services/app'

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

type ResearchTab = 'overview' | 'runs' | 'factors' | 'model' | 'risk'

const researchTabs: Array<{ key: ResearchTab; label: string }> = [
  { key: 'overview', label: '任务流水线' },
  { key: 'runs', label: '运行监控' },
  { key: 'factors', label: '因子检验' },
  { key: 'model', label: '模型训练' },
  { key: 'risk', label: '压力准入' }
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
  { key: 'strategy_admission', title: '策略准入评估', owner: 'Go 编排 + 评估中心', output: 'eval_strategy_admission', detail: '把 ml_factor_ranker 接入准入表，统一输出可启用、观察或拒绝的依据。' },
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

export function FactorResearchPage() {
  const [activeTab, setActiveTab] = useState<ResearchTab>('runs')
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
  const bestAdmission = useMemo(() => [...admissionRows].sort((a, b) => b.admission_score - a.admission_score)[0], [admissionRows])
  const latestWarningRun = warningRuns[0]
  const weakestStressRows = useMemo(() => [...stressRows]
    .filter((row) => row.bucket_type !== 'full')
    .sort((a, b) => a.annual_return - b.annual_return)
    .slice(0, 4), [stressRows])
  const parentTasks = useMemo(() => tasks.filter((task) => !task.parent_id), [tasks])
  const latestTask = parentTasks[0]
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
  const endDate = useMemo(() => '20251231', [])
  const startDate = useMemo(() => '20100101', [])

  const refresh = async () => {
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
      setCorrelations(await listFactorCorrelationResults(latestRun, 80))
      setStressRows(await listFactorStressResults(latestRun, 160))
    } else {
      setIcRows([])
      setStateIcRows([])
      setModel(null)
      setModelFeatures([])
      setPredictions([])
      setLatestPredictions([])
      setCorrelations([])
      setStressRows([])
    }
  }

  useEffect(() => {
    refresh()
  }, [])

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
        name: profile === 'smoke' ? `因子研究烟测-${params.start_date}-${params.end_date}` : `因子研究正式-${params.start_date}-${params.end_date}`,
        task_type: 'factor_research',
        params
      })
      await startTask(task.id)
      await refresh()
      setNotice(profile === 'smoke' ? '已启动因子研究烟测任务' : '已启动因子研究正式任务')
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
      setNotice('已启动因子研究任务，Go 会按流水线顺序启动子阶段')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="factorResearchPage">
      <div className="pageToolbar factorHero">
        <div>
          <div className="sectionLabel">QUANT RESEARCH CENTER</div>
          <h2>量化研究中心</h2>
          <p>从 10-15 年历史数据里自动生成因子、检验稳定性，再训练 LightGBM 预测未来 20 日相对收益。</p>
        </div>
        <div className="factorHeroActions">
          <button className="secondaryButton" onClick={refresh} disabled={busy}>
            <RefreshCw size={16} />
            刷新
          </button>
          <button className="secondaryButton" onClick={() => createAndStart('smoke')} disabled={busy} title="2020-2025 快速跑通完整链路">
            <DatabaseZap size={16} />
            烟测闭环
          </button>
          <button className="primaryButton" onClick={() => createAndStart('full')} disabled={busy} title="2010-2025 正式全量研究闭环">
            <Play size={16} />
            正式全量
          </button>
        </div>
      </div>
      {notice ? <div className="saveHint">{notice}</div> : null}
      {error ? <div className="errorBanner">{error}</div> : null}

      <div className="metricStrip">
        <div className="metricCard good"><span>当前样本</span><b>{numberText(runs[0]?.sample_rows)}</b><em>{runs[0]?.sample_dates ? `${runs[0].sample_dates} 期月频截面` : '等待运行'}</em></div>
        <div className="metricCard"><span>当前因子</span><b>{numberText(runs[0]?.factor_count || totalFactors)}</b><em>当前覆盖 105 个基础因子，含 rank/neutral 两版</em></div>
        <div className="metricCard"><span>可用因子</span><b>{icRows.filter((row) => row.status === 'ready').length || readyFactors}</b><em>按 Rank IC、胜率、分层筛选</em></div>
        <div className="metricCard"><span>模型状态</span><b>{model?.status || '-'}</b><em>{model?.model_type || '等待训练'}</em></div>
      </div>

      <div className="inlineTabs" role="tablist" aria-label="量化研究中心页签">
        {researchTabs.map((tab) => (
          <button key={tab.key} className={activeTab === tab.key ? 'active' : ''} onClick={() => setActiveTab(tab.key)}>
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'overview' ? (
        <>
      <section className="detailCard">
          <div className="tableHeader">
            <div>
              <div className="sectionLabel">PIPELINE</div>
              <h3>自动研究流水线</h3>
            </div>
            <span>{latestTask ? `${latestTask.name} · ${statusLabel(latestTask.status)}` : '暂无进行中的因子研究任务'}</span>
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
        </>
      ) : null}

      {activeTab === 'runs' ? (
        <>
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
              <tr><td colSpan={8} className="mutedText">暂无因子研究任务</td></tr>
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

      {activeTab === 'factors' ? (
        <>
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

      {activeTab === 'risk' ? (
        <>
      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">ADMISSION COMPARE</div>
            <h3>模型版本准入对比</h3>
          </div>
          <span>{bestAdmission ? `当前最高分 ${bestAdmission.run_id}` : '等待准入评估'}</span>
        </div>
        <div className="metricStrip">
          <div className="metricCard"><span>最新版本</span><b>{latestAdmission?.admission || '-'}</b><em>{latestAdmission?.run_id || '暂无'}</em></div>
          <div className="metricCard good"><span>最高准入分</span><b>{decimalText(bestAdmission?.admission_score, 2)}</b><em>{bestAdmission?.generated_at || '-'}</em></div>
          <div className="metricCard"><span>最新年化</span><b>{percentText(latestAdmission?.annual_return)}</b><em>有效期 {dateRangeText(latestAdmission?.effective_start, latestAdmission?.effective_end)}</em></div>
          <div className="metricCard bad"><span>压力失败</span><b>{numberText(latestAdmission?.stress_bad_event_count)}</b><em>{latestAdmission ? admissionRiskText(latestAdmission) : '-'}</em></div>
        </div>
        <table>
          <thead>
            <tr>
              <th>版本</th>
              <th>准入</th>
              <th>分数</th>
              <th>年化</th>
              <th>最大回撤</th>
              <th>Sharpe</th>
              <th>压力惩罚</th>
              <th>失败点</th>
              <th>生成时间</th>
            </tr>
          </thead>
          <tbody>
            {admissionRows.length === 0 ? (
              <tr><td colSpan={9} className="mutedText">暂无模型准入记录</td></tr>
            ) : admissionRows.slice(0, 10).map((row) => (
              <tr key={`${row.run_id}-${row.generated_at}`}>
                <td><b>{shortRunID(row.run_id)}</b><div className="mono">{dateRangeText(row.effective_start, row.effective_end)}</div></td>
                <td><span className={`badge ${admissionBadge(row.admission)}`}>{row.admission}</span></td>
                <td>{decimalText(row.admission_score, 2)}</td>
                <td className={row.annual_return >= 0 ? 'positive' : 'negative'}>{percentText(row.annual_return)}</td>
                <td className={row.max_drawdown >= -0.2 ? 'positive' : 'negative'}>{percentText(row.max_drawdown)}</td>
                <td>{decimalText(row.sharpe, 2)}</td>
                <td className={row.stress_penalty <= 0 ? 'positive' : 'negative'}>{decimalText(row.stress_penalty, 2)}</td>
                <td>{admissionRiskText(row)}</td>
                <td className="mono">{row.generated_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {latestAdmission?.reason ? <div className="saveHint">{latestAdmission.reason}</div> : null}
      </section>

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

      {activeTab === 'model' ? (
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

      {activeTab === 'factors' ? (
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
    let status = row ? stageStatusLabel(String(row.status || row.task_status || '')) : inferredStageStatus(step.key, input, allArtifactsDone)
    if (status === '待执行' && input.task && ['created', 'queued', 'running'].includes(input.task.status)) {
      const activeStage = String(activeRow?.stage || '')
      if (activeStage === step.key) {
        status = stageStatusLabel(String(activeRow?.status || activeRow?.task_status || input.task.status))
      } else if (!activeStage && index === 0) {
        status = stageStatusLabel(input.task.status)
      }
    }
    return { ...step, status }
  })
}

function taskRows(task?: TaskDTO) {
  return Array.isArray(task?.summary?.rows) ? task.summary.rows as Array<Record<string, unknown>> : []
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

function decimalText(value: unknown, digits = 2) {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(digits) : '-'
}

function percentText(value: unknown, digits = 2) {
  const n = Number(value)
  return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : '-'
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

function shortRunID(runID: string) {
  return runID.replace(/^eval_/, '').replace(/^ml_factor_/, '')
}

function dateRangeText(start?: string, end?: string) {
  if (!start && !end) return '-'
  return `${start || '-'} - ${end || '-'}`
}

function admissionBadge(admission: string) {
  if (admission === '通过' || admission === '可准入') return 'success'
  if (admission === '继续观察') return 'running'
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

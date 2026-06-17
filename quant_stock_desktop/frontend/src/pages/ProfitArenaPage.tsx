import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, BrainCircuit, CheckCircle2, Play, RefreshCw, ShieldCheck, Trophy } from 'lucide-react'
import {
  getProfitArenaMarketDate,
  getProfitArenaRunStatus,
  listProfitArenaEvaluations,
  listProfitArenaFeatures,
  listProfitArenaPredictions,
  listProfitArenaRuns,
  listTasks,
  runProfitArenaLatestInference,
  runProfitArenaTraining,
  type ProfitArenaEvaluation,
  type ProfitArenaFeature,
  type ProfitArenaPrediction,
  type ProfitArenaRunSummary,
  type RunStatus,
  type TaskDTO
} from '../services/app'

type ArenaTab = 'recommend' | 'training' | 'evaluation'

type ArenaScorePayload = {
  score?: number
  raw?: {
    capital_annual_return?: number
    capital_max_drawdown?: number
    capital_sharpe?: number
    rank_ic?: number
    rank_ic_days?: number
    trade_count?: number
    calmar?: number
  }
}

type ArenaSummaryPayload = {
  arena_score?: number
  best_challenger_score_components?: ArenaScorePayload
  best?: Record<string, unknown>
  leaderboards?: Record<string, unknown[]>
  source_run_id?: string
  source_predictions?: string
  champion_validation?: Record<string, unknown>
  validation_status?: string
}

type ArenaExecutionConfig = {
  topN: number
  horizon: number
  maxCrashProb: number
  takeProfit: number
  stopLoss: number
  positionWeighting: string
  capitalFraction: number
}

const ARENA_TOTAL_CAPITAL = 30000

const tabs: Array<{ key: ArenaTab; label: string }> = [
  { key: 'recommend', label: '股票推荐' },
  { key: 'training', label: '擂台训练' },
  { key: 'evaluation', label: '擂主评估' }
]

export function ProfitArenaPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [activeTab, setActiveTab] = useState<ArenaTab>('recommend')
  const [runs, setRuns] = useState<ProfitArenaRunSummary[]>([])
  const [evaluations, setEvaluations] = useState<ProfitArenaEvaluation[]>([])
  const [predictions, setPredictions] = useState<ProfitArenaPrediction[]>([])
  const [features, setFeatures] = useState<ProfitArenaFeature[]>([])
  const [tasks, setTasks] = useState<TaskDTO[]>([])
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [marketDate, setMarketDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const sortedRuns = useMemo(() => [...runs].sort(compareArenaRuns), [runs])
  const selectedRun = sortedRuns[0]
  const summary = useMemo(() => parseArenaSummary(selectedRun), [selectedRun])
  const selectedScore = useMemo(() => runScore(selectedRun), [selectedRun])
  const bestEval = useMemo(() => bestEvaluation(evaluations), [evaluations])
  const executionConfig = useMemo(() => arenaExecutionConfig(bestEval, selectedRun), [bestEval, selectedRun])
  const latestDate = predictions.find((row) => row.is_latest)?.trade_date || predictions[0]?.trade_date || ''
  const recommendationStale = Boolean(marketDate && latestDate && normalizeDateKey(latestDate) < normalizeDateKey(marketDate))
  const latestPredictions = useMemo(() => {
    const rows = latestDate ? predictions.filter((row) => row.trade_date === latestDate || row.is_latest) : predictions
    return rows
      .sort((a, b) => b.model_score - a.model_score)
      .slice(0, 20)
  }, [latestDate, predictions])
  const topRecommendations = latestPredictions
    .filter((row) => Number(row.crash_prob || 0) <= executionConfig.maxCrashProb)
    .slice(0, executionConfig.topN)
  const arenaTasks = useMemo(() => tasks.filter((task) => {
    const strategy = String(task.params?.strategy || '')
    return task.task_type === 'model_training' && (strategy === 'profit_arena_model' || strategy === 'profit_arena')
  }), [tasks])
  const runningTasks = arenaTasks.filter((task) => task.status === 'running').length
  const queuedTasks = arenaTasks.filter((task) => task.status === 'queued' || task.status === 'created').length
  const failedTasks = arenaTasks.filter((task) => task.status === 'failed' || task.status === 'interrupted').length
  const latestInferenceTask = arenaTasks.find((task) => isArenaLatestInferenceTask(task) && isActiveTask(task))
  const activeTask = latestInferenceTask || arenaTasks.find(isActiveTask)

  const refresh = useCallback(async () => {
    const [runItems, taskItems, status, marketLatest] = await Promise.all([
      listProfitArenaRuns(30),
      listTasks({ limit: 300 }),
      getProfitArenaRunStatus(),
      getProfitArenaMarketDate()
    ])
    setRuns(runItems)
    setTasks(taskItems)
    setRunStatus(status)
    setMarketDate(marketLatest || '')
    const runID = [...runItems].sort(compareArenaRuns)[0]?.run_id || ''
    if (runID) {
      const [evalRows, predRows, featureRows] = await Promise.all([
        listProfitArenaEvaluations(runID, 160),
        listProfitArenaPredictions('', 160),
        listProfitArenaFeatures(runID, 60)
      ])
      setEvaluations(evalRows)
      setPredictions(predRows)
      setFeatures(featureRows)
    } else {
      setEvaluations([])
      setPredictions([])
      setFeatures([])
    }
  }, [])

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [refresh])

  useEffect(() => {
    const intervalMs = busy || runningTasks > 0 || queuedTasks > 0 ? 3000 : 15000
    const timer = window.setInterval(() => {
      refresh().catch(() => {})
    }, intervalMs)
    return () => window.clearInterval(timer)
  }, [busy, queuedTasks, refresh, runningTasks])

  const startTraining = async () => {
    setBusy(true)
    setNotice('')
    setError('')
    try {
      await runProfitArenaTraining()
      await refresh()
      setNotice('已启动收益擂台训练任务，可在训练页查看实时进度')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const refreshLatestInference = async () => {
    setBusy(true)
    setNotice('')
    setError('')
    try {
      const task = await runProfitArenaLatestInference()
      await refresh()
      setNotice(`已启动收益擂台最新截面推理：${task.name || task.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="factorResearchPage profitArenaPage">
      {notice ? <div className="saveHint">{notice}</div> : null}
      {error ? <div className="errorBanner">{error}</div> : null}

      <div className="pageTabsHeader">
        <div className="inlineTabs evaluationModeTabs signalViewTabs" role="tablist" aria-label="收益擂台页签">
          {tabs.map((tab) => (
            <button key={tab.key} className={activeTab === tab.key ? 'active' : ''} onClick={() => setActiveTab(tab.key)}>
              {tab.label}
            </button>
          ))}
        </div>
        <div className="dataUpdatedPill">市场数据：{dateLabel(marketDate || latestDate || selectedRun?.updated_at || '')}</div>
      </div>

      {activeTab === 'recommend' ? (
        <>
          {activeTask ? <ArenaTaskProgress task={activeTask} /> : null}
          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">PROFIT ARENA</div>
                <h2>收益擂台每日股票推荐</h2>
                <p className="recommendationMeta">基于当前擂主规则输出进攻候选；擂主按 Score 自动守擂，不需要人工选择生效。</p>
              </div>
              <div className="tableHeaderRight">
                <button className="secondaryButton startButton" onClick={refreshLatestInference} disabled={busy}>
                  <RefreshCw size={16} />
                  {marketDate ? `重新推理至 ${dateLabel(marketDate)}` : '重新推理'}
                </button>
              </div>
            </div>

            <div className="metricStrip">
              <div className={`metricCard ${selectedRun?.run_id ? 'good' : ''}`}><span>当前擂主</span><b>{selectedRun?.run_id ? '自动生效' : '等待擂主'}</b><em>{shortRunID(selectedRun?.run_id || '') || '未产生擂主'}</em></div>
              <div className="metricCard"><span>擂主评分</span><b>{decimalText(selectedScore.score, 1)}</b><em>按当前100分桶规则重算</em></div>
              <div className="metricCard"><span>年化 / 回撤</span><b>{pct(rawMetric(selectedRun, 'capital_annual_return'))}</b><em>回撤 {pct(rawMetric(selectedRun, 'capital_max_drawdown'))}</em></div>
              <div className={`metricCard ${rawMetric(selectedRun, 'rank_ic') >= 0.08 ? 'good' : ''}`}><span>RankIC / Sharpe</span><b>{decimalText(rawMetric(selectedRun, 'rank_ic'), 4)}</b><em>Sharpe {decimalText(rawMetric(selectedRun, 'capital_sharpe'), 2)}</em></div>
            </div>

            <div className="metricStrip">
              <div className={`metricCard ${recommendationStale ? 'bad' : ''}`}><span>推荐截面</span><b>{dateLabel(latestDate)}</b><em>{recommendationStale ? `落后市场数据 ${dateLabel(marketDate)}` : `Top${numberText(executionConfig.topN)} 买入清单`}</em></div>
              <div className="metricCard"><span>推荐数量</span><b>{numberText(topRecommendations.length)}</b><em>{latestDate ? `${dateLabel(latestDate)} 截面` : '等待最新预测'}</em></div>
              <div className="metricCard"><span>擂主TopN</span><b>{numberText(executionConfig.topN)}</b><em>只展示模型买入清单</em></div>
            </div>
          </section>

          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">STOCK LIST</div>
                <h2>今日推荐股票列表</h2>
                <p className="recommendationMeta">字段、动作和条件单口径对齐通用策略；收益擂台只负责输出当前擂主最新截面候选，不自动成交。</p>
              </div>
              <span>{selectedRun ? `${dateLabel(latestDate)} · ${shortRunID(selectedRun.run_id)}` : '暂无推荐截面'}</span>
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
                  {topRecommendations.length === 0 ? (
                    <tr><td colSpan={9} className="emptyCell">暂无收益擂台推荐，请先完成训练或导入擂主预测</td></tr>
                  ) : topRecommendations.map((row, index) => {
                    const plan = arenaPlan(row, index, executionConfig, topRecommendations)
                    return (
                      <tr key={`${row.run_id}-${row.trade_date}-${row.ts_code}`} className="highlightRow">
                        <td><strong>{index + 1}</strong></td>
                        <td className="t0StockCell">
                          <button className="tableActionButton" onClick={() => onOpenResearch?.(row.ts_code)} title="查看个股研究">
                            {row.name || row.ts_code}
                          </button>
                          <div className="mono">{row.ts_code}</div>
                          <div className="recommendationMeta t0CurrentPrice">截面收盘 {priceText(row.price)}</div>
                          <div className="recommendationMeta">{row.industry || '—'} · {dateLabel(row.trade_date)}</div>
                          <div className="recommendationMeta">市值层 {row.size_bucket || row.scope || '—'} · 持有 {numberText(executionConfig.horizon)} 日</div>
                          <div className="recommendationMeta">擂主 {shortRunID(row.run_id)}</div>
                        </td>
                        <td>
                          <span className="badge success">买入</span>
                          <div className="recommendationMeta">擂主 Top{numberText(executionConfig.topN)} 买入清单</div>
                          <div className="recommendationMeta">预测净收益 {pct(row.pred_return)}</div>
                          <div className="recommendationMeta">模型分数 {decimalText(row.model_score, 4)}</div>
                        </td>
                        <td>
                          <strong>{plan.buyLabel}</strong>
                          <div className="recommendationMeta">{Number(row.price) > 0 ? '使用最新截面收盘价' : '截面价缺失，需先刷新推理'}</div>
                          <div className="recommendationMeta">训练回测按次日可买入价近似</div>
                          <div className="recommendationMeta">截面 {dateLabel(row.trade_date)}</div>
                        </td>
                        <td>
                          <strong>{plan.shares > 0 ? `${plan.shares} 股` : '不买'}</strong>
                          <div className="recommendationMeta">{executionConfig.positionWeighting} 权重</div>
                          <div className="recommendationMeta">按总资金3万元估算</div>
                          <div className="recommendationMeta">100股取整 · 目标仓位 {plan.weightLabel}</div>
                        </td>
                        <td>
                          <strong>{plan.sellLabel}</strong>
                          <div className="recommendationMeta">{executionConfig.takeProfit > 0 ? `止盈 ${pct(executionConfig.takeProfit)}` : '模型未启用硬止盈'}</div>
                          <div className="recommendationMeta">退出参考 {dateLabel(row.exit_date)}</div>
                          <div className="recommendationMeta">未触达不抢跑</div>
                        </td>
                        <td>
                          <strong>{plan.shares > 0 ? `${plan.shares} 股` : '不卖'}</strong>
                          <div className="recommendationMeta">对应买入股数</div>
                          <div className="recommendationMeta">先买后卖，不做裸卖</div>
                        </td>
                        <td>
                          <strong className="negative">{plan.stopLabel}</strong>
                          <div className="recommendationMeta">{executionConfig.stopLoss > 0 ? `止损 ${pct(executionConfig.stopLoss)}` : '模型未启用硬止损'}</div>
                          <div className="recommendationMeta">crash {pct(row.crash_prob)}</div>
                          <div className="recommendationMeta">阈值 {pct(executionConfig.maxCrashProb)}</div>
                        </td>
                        <td>
                          <strong>{decimalText(row.model_score, 4)}</strong>
                          <div className="recommendationMeta">预测净收益 {pct(row.pred_return)}</div>
                          <div className="recommendationMeta">未来收益 {pct(row.future_return)} · 最大冲高 {pct(row.future_max_return)}</div>
                          <div className="recommendationMeta">未来回撤 {pct(row.future_drawdown)} · 已结算 {pct(row.realized_return)}</div>
                          <div className="recommendationMeta">当前擂主规则输出，不自动成交</div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}

      {activeTab === 'training' ? (
        <>
          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">TASK FRAMEWORK</div>
                <h3>收益擂台训练任务</h3>
              </div>
              <div className="tableHeaderRight">
                <button className="primaryButton startButton" onClick={startTraining} disabled={busy}>
                  <Play size={16} />
                  继续打擂
                </button>
              </div>
            </div>
            <div className="metricStrip">
              <div className="metricCard"><span>任务数</span><b>{numberText(arenaTasks.length)}</b><em>Task 框架内可观测</em></div>
              <div className="metricCard good"><span>运行中</span><b>{numberText(runningTasks)}</b><em>worker 正在执行</em></div>
              <div className="metricCard"><span>排队/待启动</span><b>{numberText(queuedTasks)}</b><em>created/queued</em></div>
              <div className="metricCard bad"><span>失败/中断</span><b>{numberText(failedTasks)}</b><em>需要检查日志</em></div>
            </div>
            <table>
              <thead>
                <tr>
                  <th>任务</th>
                  <th>状态</th>
                  <th>进度</th>
                  <th>当前步骤</th>
                  <th>Run ID</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                {arenaTasks.length === 0 ? (
                  <tr><td colSpan={6} className="mutedText">暂无收益擂台训练任务</td></tr>
                ) : arenaTasks.slice(0, 14).map((task) => (
                  <tr key={task.id}>
                    <td><b>{task.name}</b><div className="mutedText">{task.id}</div></td>
                    <td><span className={`badge ${task.status}`}>{statusLabel(task.status)}</span></td>
                    <td>{Math.round(Number(task.progress || 0) * 100)}%</td>
                    <td>{task.subtask_name || task.subtask_key || taskStatusMessage(task)}</td>
                    <td className="mono">{task.external_run_id || task.group_run_id || '-'}</td>
                    <td className="mono">{task.updated_at || task.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">VERSIONS</div>
                <h3>擂主和挑战者版本</h3>
              </div>
              <span>{selectedRun ? `当前擂主 ${shortRunID(selectedRun.run_id)}` : '暂无擂主版本'}</span>
            </div>
            <table>
              <thead>
                <tr>
                  <th>版本</th>
                  <th>状态</th>
                  <th>Score</th>
                  <th>年化</th>
                  <th>最大回撤</th>
                  <th>RankIC</th>
                  <th>Sharpe</th>
                  <th>规则</th>
                  <th>守擂状态</th>
                </tr>
              </thead>
              <tbody>
                {sortedRuns.length === 0 ? (
                  <tr><td colSpan={9} className="mutedText">暂无收益擂台版本</td></tr>
                ) : sortedRuns.slice(0, 12).map((run, index) => {
                  const champion = index === 0
                  const score = runScore(run)
                  return (
                    <tr key={run.run_id}>
                      <td>
                        <b>{champion ? '当前擂主' : '历史挑战者'} · {shortRunID(run.run_id)}</b>
                        {champion ? <span className="versionActiveTag">守擂中</span> : null}
                        <div className="mono">{dateTimeLabel(run.updated_at)}</div>
                      </td>
                      <td><span className={`badge ${run.status === 'success' ? 'success' : run.status === 'running' ? 'running' : 'failed'}`}>{statusLabel(run.status)}</span></td>
                      <td>{decimalText(score.score, 1)}</td>
                      <td className="positive">{pct(score.annual)}</td>
                      <td className={score.drawdown >= -0.15 ? 'positive' : 'negative'}>{pct(score.drawdown)}</td>
                      <td>{decimalText(score.rankIC, 4)}</td>
                      <td>{decimalText(score.sharpe, 2)}</td>
                      <td>Top{numberText(run.best_top_n)} / {numberText(run.best_horizon)}日 / {run.best_scope || '-'}</td>
                      <td>
                        <span className={`badge ${champion ? 'success' : 'created'}`}>{champion ? '默认生效' : '未打赢擂主'}</span>
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
          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">CHAMPION REVIEW</div>
                <h3>擂主复验和核心指标</h3>
              </div>
              <Trophy size={22} />
            </div>
            <div className="modelChecklist">
              <div><CheckCircle2 size={16} /><span>按 Score 决定擂主，未打赢不替换</span></div>
              <div><ShieldCheck size={16} /><span>新擂主需要同配置复验后才允许通知</span></div>
              <div><BrainCircuit size={16} /><span>训练采用 4 年训练、第 5 年样本外滚动验证</span></div>
              <div><Activity size={16} /><span>推荐进入市场验证，不自动交易</span></div>
            </div>
            <div className="factorModelSummary">
              <div><span>Score</span><b>{decimalText(selectedScore.score, 1)}</b></div>
              <div><span>年化收益</span><b>{pct(rawMetric(selectedRun, 'capital_annual_return'))}</b></div>
              <div><span>最大回撤</span><b>{pct(rawMetric(selectedRun, 'capital_max_drawdown'))}</b></div>
              <div><span>Calmar</span><b>{decimalText(rawMetric(selectedRun, 'calmar'), 2)}</b></div>
              <div><span>RankIC</span><b>{decimalText(rawMetric(selectedRun, 'rank_ic'), 4)}</b></div>
              <div><span>Sharpe</span><b>{decimalText(rawMetric(selectedRun, 'capital_sharpe'), 2)}</b></div>
              <div><span>交易数</span><b>{numberText(rawMetric(selectedRun, 'trade_count'))}</b></div>
              <div><span>RankIC天数</span><b>{numberText(rawMetric(selectedRun, 'rank_ic_days'))}</b></div>
              <div className="wide"><span>模型来源</span><code>{summary.source_run_id || selectedRun?.model_path || '-'}</code></div>
            </div>
          </section>

          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">ARENA GRID</div>
                <h3>收益擂台评估结果</h3>
              </div>
              <span>{selectedRun ? shortRunID(selectedRun.run_id) : '暂无 run'}</span>
            </div>
            <table>
              <thead>
                <tr>
                  <th>规则</th>
                  <th>交易数</th>
                  <th>胜率</th>
                  <th>年化</th>
                  <th>最大回撤</th>
                  <th>Sharpe</th>
                  <th>资金终值</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                {evaluations.length === 0 ? (
                  <tr><td colSpan={8} className="mutedText">暂无擂台评估结果</td></tr>
                ) : evaluations.slice(0, 20).map((row) => (
                  <tr key={`${row.run_id}-${row.scope}-${row.horizon}-${row.top_n}-${row.min_pred_return}-${row.segment}`}>
                    <td><b>{row.scope} / Top{row.top_n}</b><div className="mutedText">{row.horizon}日 · 阈值 {decimalText(row.min_pred_return, 3)}</div></td>
                    <td>{numberText(row.trade_count)}</td>
                    <td>{pct(row.win_rate)}</td>
                    <td className="positive">{pct(row.capital_annual_return || row.annual_return)}</td>
                    <td className={(row.capital_max_drawdown || row.max_drawdown) >= -0.15 ? 'positive' : 'negative'}>{pct(row.capital_max_drawdown || row.max_drawdown)}</td>
                    <td>{decimalText(row.capital_sharpe || row.sharpe, 2)}</td>
                    <td>{decimalText(row.capital_final_equity, 2)}</td>
                    <td className="mono">{dateTimeLabel(row.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">FEATURES</div>
                <h3>模型特征重要度</h3>
              </div>
              <span>{numberText(features.length)} 个特征</span>
            </div>
            <div className="limitModelFeatureList">
              {features.length === 0 ? (
                <div className="taskGridEmpty compactEmpty">暂无特征重要度</div>
              ) : features.slice(0, 30).map((row) => (
                <span key={`${row.run_id}-${row.feature}`}>{row.rank_no}. {featureLabel(row.feature)} · {decimalText(row.importance, 1)}</span>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}

function isActiveTask(task: TaskDTO) {
  return task.status === 'running' || task.status === 'queued' || task.status === 'created'
}

function isArenaLatestInferenceTask(task: TaskDTO) {
  const profile = String(task.params?.profile || '')
  const name = String(task.name || '')
  return profile === 'inference' || name.includes('重新推理')
}

function ArenaTaskProgress({ task }: { task: TaskDTO }) {
  return (
    <section className="detailCard compactRunCard">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">RUNNING TASK</div>
          <h3>{task.name}</h3>
        </div>
        <span>{statusLabel(task.status)} · {Math.round(Number(task.progress || 0) * 100)}%</span>
      </div>
      <div className="progressTrack"><div style={{ width: `${Math.max(0, Math.min(100, Number(task.progress || 0) * 100))}%` }} /></div>
      <div className="cardHint">{task.subtask_name || task.subtask_key || taskStatusMessage(task)}</div>
    </section>
  )
}

function parseArenaSummary(run?: ProfitArenaRunSummary): ArenaSummaryPayload {
  if (!run?.summary_json) return {}
  try {
    const parsed = JSON.parse(run.summary_json) as ArenaSummaryPayload
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function parseJSONRecord(text?: string): Record<string, unknown> {
  if (!text) return {}
  try {
    const parsed = JSON.parse(text)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function bestEvaluation(rows: ProfitArenaEvaluation[]) {
  return rows.reduce<ProfitArenaEvaluation | null>((best, row) => {
    const score = row.capital_annual_return || row.annual_return || 0
    const bestScore = best ? best.capital_annual_return || best.annual_return || 0 : Number.NEGATIVE_INFINITY
    return score > bestScore ? row : best
  }, null)
}

function runScore(run?: ProfitArenaRunSummary) {
  const summary = parseArenaSummary(run)
  const raw = summary.best_challenger_score_components?.raw || {}
  const best = summary.best || {}
  const annual = Number(raw.capital_annual_return ?? best.capital_annual_return ?? 0)
  const drawdown = Number(raw.capital_max_drawdown ?? best.capital_max_drawdown ?? 0)
  const rankIC = Number(raw.rank_ic ?? best.rank_ic ?? 0)
  const sharpe = Number(raw.capital_sharpe ?? best.capital_sharpe ?? 0)
  const calmar = drawdown < 0 ? annual / Math.abs(drawdown) : annual > 0 ? annual / 1e-9 : 0
  return {
    score: currentArenaScore(annual, drawdown, rankIC, sharpe),
    annual,
    drawdown,
    calmar,
    rankIC,
    sharpe
  }
}

function currentArenaScore(annual: number, drawdown: number, rankIC: number, sharpe: number) {
  const calmar = drawdown < 0 ? annual / Math.abs(drawdown) : annual > 0 ? annual / 1e-9 : 0
  return annualBucketScore(annual) * 0.40
    + calmarBucketScore(calmar) * 0.30
    + rankICBucketScore(rankIC) * 0.20
    + sharpeBucketScore(sharpe) * 0.10
}

function annualBucketScore(annual: number) {
  if (annual < 0.05) return 0
  if (annual < 0.10) return 20
  if (annual < 0.15) return 40
  if (annual < 0.20) return 60
  if (annual < 0.30) return 80
  if (annual < 0.40) return 90
  if (annual <= 0.60) return 95
  return 100
}

function calmarBucketScore(calmar: number) {
  if (calmar < 0.5) return 0
  if (calmar < 1.0) return 30
  if (calmar < 1.5) return 60
  if (calmar < 2.0) return 80
  if (calmar < 2.5) return 90
  if (calmar < 3.0) return 95
  return 100
}

function rankICBucketScore(rankIC: number) {
  if (rankIC < 0.01) return 0
  if (rankIC < 0.03) return 30
  if (rankIC < 0.05) return 50
  if (rankIC < 0.08) return 70
  if (rankIC < 0.10) return 85
  if (rankIC < 0.12) return 95
  return 100
}

function sharpeBucketScore(sharpe: number) {
  if (sharpe < 0.5) return 0
  if (sharpe < 1.0) return 40
  if (sharpe < 1.2) return 60
  if (sharpe < 1.5) return 75
  if (sharpe < 2.0) return 90
  return 100
}

function compareArenaRuns(a: ProfitArenaRunSummary, b: ProfitArenaRunSummary) {
  const left = runScore(a)
  const right = runScore(b)
  return (
    right.score - left.score ||
    right.annual - left.annual ||
    right.calmar - left.calmar ||
    right.rankIC - left.rankIC ||
    right.sharpe - left.sharpe ||
    right.drawdown - left.drawdown
  )
}

function rawMetric(run: ProfitArenaRunSummary | undefined, key: string) {
  const summary = parseArenaSummary(run)
  const raw = summary.best_challenger_score_components?.raw || {}
  const best = summary.best || {}
  return Number((raw as Record<string, unknown>)[key] ?? best[key] ?? 0)
}

function arenaExecutionConfig(evalRow?: ProfitArenaEvaluation | null, run?: ProfitArenaRunSummary): ArenaExecutionConfig {
  const payload = parseJSONRecord(evalRow?.summary_json)
  const topN = Math.max(1, Math.round(Number(payload.top_n ?? evalRow?.top_n ?? run?.best_top_n ?? 3)))
  const horizon = Math.max(1, Math.round(Number(payload.horizon ?? evalRow?.horizon ?? run?.best_horizon ?? 20)))
  const capitalFractionRaw = Number(payload.capital_tranche_fraction ?? 1)
  return {
    topN,
    horizon,
    maxCrashProb: Number(payload.max_crash_prob ?? 999),
    takeProfit: Math.max(0, Number(payload.execution_take_profit ?? 0)),
    stopLoss: Math.max(0, Number(payload.execution_stop_loss ?? 0)),
    positionWeighting: String(payload.position_weighting || 'equal'),
    capitalFraction: Number.isFinite(capitalFractionRaw) && capitalFractionRaw > 0 ? capitalFractionRaw : 1
  }
}

function arenaPlan(row: ProfitArenaPrediction, index: number, config: ArenaExecutionConfig, topRows: ProfitArenaPrediction[]) {
  const price = Number(row.price)
  const hasPrice = Number.isFinite(price) && price > 0
  const buy = hasPrice ? price : Number.NaN
  const sell = hasPrice && config.takeProfit > 0 ? price * (1 + config.takeProfit) : Number.NaN
  const stop = hasPrice && config.stopLoss > 0 ? price * (1 - config.stopLoss) : Number.NaN
  const weight = arenaPositionWeight(row, topRows, config, index)
  const shares = hasPrice ? roundLotShares(buy, ARENA_TOTAL_CAPITAL * weight) : 0
  return {
    buyLabel: hasPrice ? `¥${moneyText(buy)}` : '截面价缺失',
    sellLabel: hasPrice && config.takeProfit > 0 ? `¥${moneyText(sell)}` : '按持有期退出',
    stopLabel: hasPrice && config.stopLoss > 0 ? `¥${moneyText(stop)}` : '无硬止损',
    weightLabel: pct(weight),
    shares
  }
}

function roundLotShares(price: number, cash: number) {
  if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(cash) || cash <= 0) return 0
  return Math.floor(cash / price / 100) * 100
}

function arenaPositionWeight(row: ProfitArenaPrediction, rows: ProfitArenaPrediction[], config: ArenaExecutionConfig, index: number) {
  const capital = Math.max(0, Math.min(1, config.capitalFraction || 1))
  if (rows.length === 0) return 0
  if (config.positionWeighting === 'equal') return capital / rows.length
  const scores = rows.map((item) => Math.max(0, Number(item.model_score) || 0))
  const total = scores.reduce((sum, value) => sum + value, 0)
  if (total <= 0) return capital / rows.length
  let weight = capital * (Math.max(0, Number(row.model_score) || 0) / total)
  if (config.positionWeighting === 'score_cap50') {
    weight = Math.min(weight, 0.5)
  }
  if (!Number.isFinite(weight) || weight <= 0) return capital / rows.length
  return weight
}

function numberText(value: unknown) {
  const n = Number(value)
  return Number.isFinite(n) ? n.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) : '-'
}

function moneyText(value: unknown) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return '-'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function priceText(value: unknown) {
  const text = moneyText(value)
  return text === '-' ? '缺失' : `¥${text}`
}

function decimalText(value: unknown, digits = 2) {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(digits) : '-'
}

function pct(value: unknown, digits = 2) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return `${n > 0 ? '+' : ''}${(n * 100).toFixed(digits)}%`
}

function dateLabel(value?: string) {
  if (!value) return '-'
  if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10)
  return value
}

function normalizeDateKey(value?: string) {
  if (!value) return ''
  const text = String(value)
  if (/^\d{8}$/.test(text)) return text
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10).replace(/-/g, '')
  return text.replace(/-/g, '').slice(0, 8)
}

function dateTimeLabel(value?: string) {
  if (!value) return '-'
  if (/^\d{8}$/.test(value)) return dateLabel(value)
  return value.replace('T', ' ').replace(/\.\d+Z?$/, '').slice(0, 16) || value
}

function shortRunID(runID: string) {
  if (!runID) return ''
  return runID.length > 28 ? `${runID.slice(0, 12)}…${runID.slice(-8)}` : runID
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
  }[status] || status || '-'
}

function taskStatusMessage(task: TaskDTO) {
  const stage = String(task.summary?.stage || task.summary?.current_stage || '')
  const message = String(task.summary?.message || '')
  return stage || message || '等待 worker 上报进度'
}

function featureLabel(value: string) {
  const labels: Record<string, string> = {
    ret5: '近5日收益',
    ret10: '近10日收益',
    ret20: '近20日收益',
    ret60: '近60日收益',
    turnover_rate: '换手率',
    amount_chg5: '5日成交变化',
    amount_chg20: '20日成交变化',
    volatility20: '20日波动',
    drawdown20: '20日回撤',
    circ_mv_log: '流通市值',
    pb: 'PB',
    pe_ttm: 'PE TTM',
    market_up_ratio: '市场上涨占比',
    small_up_ratio: '小盘上涨占比',
    industry_up_ratio: '行业上涨占比',
    rs_market20: '20日相对市场',
    rs_industry20: '20日相对行业'
  }
  return labels[value] || value
}

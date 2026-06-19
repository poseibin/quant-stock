import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  listMarketDataFiles,
  scanMarketDataFiles,
  runDataUpdate,
  getDataUpdateStatus,
  getFactorSnapshotStatus,
  getFactorStoreGovernance,
  emptyRunStatus,
  listDatasetUpdateStatus,
  checkExternalDependencies,
  type MarketDataFile,
  type RunStatus,
  type DatasetUpdateStatus,
  type ExternalDependencyStatus,
  type FactorStoreGovernance,
} from '../services/app'
import { formatDate } from '../components/format'
import { DataHealthPanel } from '../features/data/DataHealthPanel'
import { DatasetCards } from '../features/data/DatasetCards'
import { buildJobHealth, jobMetas, type DatasetKey } from '../features/data/dataUtils'

const PHASES = [
  { value: 'all', label: '全部' },
  { value: 'basic', label: '基础' },
  { value: 'price', label: '行情' },
  { value: 'finance', label: '财务' },
  { value: 'event', label: '事件' },
]

const FACTOR_SNAPSHOT_POST_UPDATE_WAIT_MS = 180000

export function DataExplorerPage() {
  const [activeDataset, setActiveDataset] = useState<DatasetKey>('stock_basic')
  const [files, setFiles] = useState<MarketDataFile[]>([])
  const [phase, setPhase] = useState('all')
  const [updateStatus, setUpdateStatus] = useState<RunStatus | null>(null)
  const [factorSnapshotStatus, setFactorSnapshotStatus] = useState<RunStatus | null>(null)
  const [factorGovernance, setFactorGovernance] = useState<FactorStoreGovernance>({})
  const [datasetStatuses, setDatasetStatuses] = useState<DatasetUpdateStatus[]>([])
  const [dependencies, setDependencies] = useState<ExternalDependencyStatus[]>([])
  const [dependencyLoading, setDependencyLoading] = useState(false)
  const [dataRefreshedAt, setDataRefreshedAt] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const pollStartedAtRef = useRef(0)
  const expectFactorSnapshotRef = useRef(false)

  const loadDependencies = useCallback(async () => {
    setDependencyLoading(true)
    try {
      setDependencies(await checkExternalDependencies())
    } catch (error) {
      console.error('[data] check external dependencies failed', error)
      setDependencies([])
    } finally {
      setDependencyLoading(false)
    }
  }, [])

  const load = async () => {
    try {
      setFiles(await scanMarketDataFiles())
    } catch (error) {
      console.error('[data] scan market files failed', error)
      try {
        setFiles(await listMarketDataFiles())
      } catch (fallbackError) {
        console.error('[data] load market files failed', fallbackError)
        setFiles([])
      }
    }
    try {
      setDatasetStatuses(await listDatasetUpdateStatus())
    } catch (error) {
      console.error('[data] load update status failed', error)
      setDatasetStatuses([])
    }
    try {
      setUpdateStatus(await getDataUpdateStatus())
    } catch (error) {
      console.error('[data] load data update status failed', error)
      setUpdateStatus(null)
    }
    try {
      setFactorSnapshotStatus(await getFactorSnapshotStatus())
    } catch (error) {
      console.error('[data] load factor snapshot status failed', error)
      setFactorSnapshotStatus(null)
    }
    try {
      setFactorGovernance(await getFactorStoreGovernance('stock_factor_base_v1'))
    } catch (error) {
      console.error('[data] load factor governance failed', error)
      setFactorGovernance({})
    }
    setDataRefreshedAt(new Date().toISOString())
  }

  useEffect(() => {
    load()
    loadDependencies()
  }, [loadDependencies])

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const startPoll = useCallback(() => {
    stopPoll()
    pollStartedAtRef.current = Date.now()
    pollRef.current = setInterval(async () => {
      try {
        const [status, dsStatus, snapshotStatus, governance] = await Promise.all([
          getDataUpdateStatus(),
          listDatasetUpdateStatus(),
          getFactorSnapshotStatus(),
          getFactorStoreGovernance('stock_factor_base_v1'),
        ])
        setUpdateStatus(status)
        setDatasetStatuses(dsStatus)
        setFactorSnapshotStatus(snapshotStatus)
        setFactorGovernance(governance || {})
        setDataRefreshedAt(new Date().toISOString())
        const elapsed = Date.now() - pollStartedAtRef.current
        if (expectFactorSnapshotRef.current && status.state === 'success' && isWaitingForFactorSnapshot(snapshotStatus) && elapsed < FACTOR_SNAPSHOT_POST_UPDATE_WAIT_MS) {
          setFactorSnapshotStatus(emptyRunStatus('factor_snapshot', {
            state: 'running',
            stage: 'waiting_post_update',
            name: '等待后置因子截面启动',
            message: '原子数据已完成，正在等待通用策略因子截面任务接管并上报进度',
            idx: 1,
            total: 100,
            updated_at: new Date().toISOString()
          }))
          return
        }
        if (status.state !== 'running' && snapshotStatus.state !== 'running') {
          if (elapsed < 3500) {
            return
          }
          stopPoll()
          load()
        }
      } catch (error) {
        console.error('[data] poll update status failed', error)
      }
    }, 1500)
  }, [phase, stopPoll])

  useEffect(() => {
    if (pollRef.current) return
    if (updateStatus?.state === 'running' || factorSnapshotStatus?.state === 'running') {
      startPoll()
    }
  }, [updateStatus?.state, factorSnapshotStatus?.state, startPoll])

  useEffect(() => () => stopPoll(), [stopPoll])

  const handleUpdate = useCallback(async () => {
    try {
      const shouldTriggerFactorSnapshot = shouldTriggerFactorSnapshotForPhase(phase)
      expectFactorSnapshotRef.current = shouldTriggerFactorSnapshot
      await runDataUpdate({ phase, start_date: '' })
      setUpdateStatus(emptyRunStatus('data_update', { state: 'running', message: '正在启动...' }))
      setFactorSnapshotStatus(emptyRunStatus('factor_snapshot', {
        state: 'idle',
        message: shouldTriggerFactorSnapshot ? '数据更新成功后将自动生成因子截面' : '财务/事件更新不会触发完整因子截面；请运行全部/基础/行情更新触发'
      }))
      setDatasetStatuses((prev) => markPhaseDatasetsRunning(prev, phase))
      startPoll()
    } catch (error) {
      console.error('[data] start update failed', error)
      setUpdateStatus(emptyRunStatus('data_update', { state: 'error', message: error instanceof Error ? error.message : '启动失败' }))
    }
  }, [phase, startPoll])

  const handleUpdateDataset = useCallback(async (dataset: string) => {
    try {
      expectFactorSnapshotRef.current = false
      await runDataUpdate({ phase: 'all', start_date: '', dataset })
      setUpdateStatus(emptyRunStatus('data_update', { state: 'running', total: 1, name: dataset, message: '正在启动...' }))
      setFactorSnapshotStatus(emptyRunStatus('factor_snapshot', { state: 'idle', message: '单数据集更新不会触发完整因子截面；请运行全部/基础/行情更新触发' }))
      setDatasetStatuses((prev) => upsertDatasetStatus(prev, dataset, 'running'))
      startPoll()
    } catch (error) {
      console.error('[data] start dataset update failed', error)
      setUpdateStatus(emptyRunStatus('data_update', { state: 'error', name: dataset, message: error instanceof Error ? error.message : '启动失败' }))
    }
  }, [startPoll])

  const jobHealth = useMemo(() => jobMetas.map((meta) => buildJobHealth(meta, files)), [files])
  const statusByDataset = useMemo(() => {
    const map: Record<string, DatasetUpdateStatus> = {}
    for (const item of datasetStatuses) {
      map[item.dataset] = item
    }
    return map
  }, [datasetStatuses])

  const isRunning = updateStatus?.state === 'running' || factorSnapshotStatus?.state === 'running'
  const factorSnapshotVisible = true
  const arenaChainState = profitArenaRefreshState(updateStatus, factorSnapshotStatus, factorGovernance)
  const chainSteps = dataProductionChainSteps(updateStatus, factorSnapshotStatus, factorGovernance)

  return (
    <div className="taskPage">
      <section className="tableCard dependencyCard">
        <div className="tableHeader">
          <div>
            <div className="formTitle">数据更新运行链路</div>
            <div className="cardHint">一键更新会先刷新原子数据；全部/基础/行情更新成功后自动生成因子截面；如果已有通用策略冠军版本，会继续用最新截面自动刷新买入清单。前十大股东明细默认跳过，不阻塞通用策略生产链路。</div>
          </div>
          <div className="taskActions">
            <span className={`badge ${statusBadgeClass(updateStatus?.state || '')}`}>原子数据：{statusLabel(updateStatus?.state || '')}</span>
            <span className={`badge ${statusBadgeClass(factorSnapshotStatus?.state || '')}`}>因子截面：{statusLabel(factorSnapshotStatus?.state || '')}</span>
            <span className={`badge ${statusBadgeClass(arenaChainState.state)}`}>买入清单：{arenaChainState.label}</span>
            <span className="mutedText">刷新 {dataRefreshedAt ? formatDate(dataRefreshedAt).replace(/^\d{4}-/, '').slice(0, 16) : '—'}</span>
          </div>
        </div>
        <div className="modelChecklist">
          <div><span className="badge success">1</span><span>更新股票池、日线、财务、事件等原子数据</span></div>
          <div><span className="badge running">2</span><span>数据成功后自动抽取通用策略因子截面，并写入快照签名</span></div>
          <div><span className="badge created">3</span><span>通用策略签名通过后解锁训练/推理，防止模型误用旧截面</span></div>
          <div><span className="badge created">4</span><span>已有冠军版本时自动刷新通用策略买入清单；失败时在任务中心和通用策略页保留阶段和原因</span></div>
        </div>
        <div className="productionChainBoard">
          {chainSteps.map((step) => (
            <div className={`productionChainStep ${step.tone}`} key={step.key}>
              <span>{step.label}</span>
              <b>{step.value}</b>
              <em>{step.hint}</em>
            </div>
          ))}
        </div>
      </section>
      <ExternalDependencyPanel items={dependencies} loading={dependencyLoading} onRefresh={loadDependencies} />
      <DatasetCards activeDataset={activeDataset} files={files} openDataset={setActiveDataset} />
      <DataHealthPanel
        items={jobHealth}
        onRefresh={load}
        onUpdate={handleUpdate}
        onUpdateDataset={handleUpdateDataset}
        phase={phase}
        onPhaseChange={setPhase}
        phases={PHASES}
        isUpdating={isRunning}
        statusByDataset={statusByDataset}
      />
      {factorSnapshotVisible ? <FactorSnapshotPostUpdateCard status={factorSnapshotStatus} governance={factorGovernance} /> : null}
    </div>
  )
}

function profitArenaRefreshState(updateStatus: RunStatus | null, factorSnapshotStatus: RunStatus | null, governance: FactorStoreGovernance) {
  if (updateStatus?.state === 'running' || factorSnapshotStatus?.state === 'running') {
    return { state: 'running', label: '等待上游' }
  }
  if (updateStatus?.state === 'error' || factorSnapshotStatus?.state === 'error') {
    return { state: 'error', label: '未刷新' }
  }
  const snapshotStatus = String(governance.snapshot_fresh_status || '')
  if (snapshotStatus === 'pass') {
    return { state: 'pass', label: '可刷新' }
  }
  if (snapshotStatus === 'warn') {
    return { state: 'warn', label: '需复核' }
  }
  if (snapshotStatus === 'missing') {
    return { state: 'missing', label: '缺快照' }
  }
  return { state: '', label: '待触发' }
}

function dataProductionChainSteps(updateStatus: RunStatus | null, factorSnapshotStatus: RunStatus | null, governance: FactorStoreGovernance) {
  const spec = parseJSONRecord(governance.profit_arena_spec)
  const freshness = parseJSONRecord(governance.snapshot_freshness)
  const gate = parseJSONRecord(governance.quality_gate)
  const updateState = updateStatus?.state || 'idle'
  const snapshotState = factorSnapshotStatus?.state || 'idle'
  const gateStatus = String(gate.status || governance.status || 'missing')
  const specStatus = String(spec.status || governance.snapshot_fresh_status || 'missing')
  const actualDate = String(freshness.actual || governance.trade_date_max || governance.end || '')
  const factorReady = (gateStatus === 'pass' || gateStatus === 'warn') && specStatus === 'pass'
  return [
    {
      key: 'atomic',
      label: '1 原子数据',
      value: statusLabel(updateState),
      hint: runStatusMessage(updateStatus),
      tone: updateState === 'running' ? 'running' : updateState === 'error' || updateState === 'failed' ? 'blocked' : updateState === 'success' || updateState === 'done' ? 'ready' : ''
    },
    {
      key: 'factor',
      label: '2 因子截面',
      value: snapshotState === 'running' ? '生成中' : factorReady ? '已就绪' : '待生成',
      hint: actualDate ? `${dateLabel(actualDate)} · ${numberText(Number(governance.row_count || 0))} 行 · ${numberText(Number(governance.feature_count || governance.factor_count || 0))} 因子` : runStatusMessage(factorSnapshotStatus),
      tone: snapshotState === 'running' ? 'running' : factorReady ? 'ready' : 'blocked'
    },
    {
      key: 'signature',
      label: '3 策略签名',
      value: statusLabel(specStatus),
      hint: String(spec.message || '训练/推理必须使用 stock_factor_base_v1 生产签名'),
      tone: specStatus === 'pass' ? 'ready' : specStatus === 'fail' ? 'blocked' : ''
    },
    {
      key: 'buy_list',
      label: '4 买入清单',
      value: factorReady ? '可刷新' : '等待',
      hint: factorReady ? '已有冠军版本时会在因子快照成功后自动刷新最新截面' : '等待因子快照通过后再进入冠军版本推理',
      tone: factorReady ? 'ready' : ''
    }
  ]
}

function ExternalDependencyPanel({
  items,
  loading,
  onRefresh,
}: {
  items: ExternalDependencyStatus[]
  loading: boolean
  onRefresh: () => void
}) {
  const ready = items.filter((item) => item.state === 'ready').length
  const checkedAt = items.map((item) => item.checked_at).sort().pop() || ''
  return (
    <div className="tableCard dependencyCard">
      <div className="tableHeader">
        <div>
          <div className="formTitle">外部依赖监控</div>
          <div className="cardHint">数据库、行情源、模型接口和通知通道的可用性；企业微信默认只检查配置，不主动发消息。</div>
        </div>
        <div className="taskActions">
          <span className="dependencySummary">{items.length ? `${ready}/${items.length} 可用` : '未检测'}</span>
          <button className="secondaryButton" onClick={onRefresh} disabled={loading}>{loading ? '检测中…' : '重新检测'}</button>
        </div>
      </div>
      <div className="dependencyGrid">
        {items.length === 0 && (
          <div className="dependencyEmpty">{loading ? '正在检测外部依赖...' : '暂无检测结果'}</div>
        )}
        {items.map((item) => (
          <div className={`dependencyItem ${item.state}`} key={item.key}>
            <div className="dependencyItemTop">
              <span>{item.category}</span>
              <b>{dependencyStateLabel(item.state)}</b>
            </div>
            <strong>{item.name}</strong>
            <p title={item.message}>{item.message || '—'}</p>
            <div className="dependencyMeta">
              <span>{item.latency_ms > 0 ? `${item.latency_ms} ms` : '—'}</span>
              <span>{formatDate(item.checked_at || checkedAt) || '—'}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function shouldTriggerFactorSnapshotForPhase(phase: string) {
  return phase === 'all' || phase === 'basic' || phase === 'price' || phase === ''
}

function isWaitingForFactorSnapshot(status: RunStatus | null) {
  if (!status) return true
  return status.state === '' || status.state === 'idle' || status.state === 'created' || status.state === 'queued'
}

function FactorSnapshotPostUpdateCard({ status, governance }: { status: RunStatus | null, governance: FactorStoreGovernance }) {
  const progress = status && status.total > 0 ? Math.round((Number(status.idx || 0) / Number(status.total || 1)) * 100) : 0
  const clamped = Math.max(0, Math.min(100, progress))
  const isRunning = status?.state === 'running'
  const isIdle = !status || status.state === 'idle' || status.state === ''
  const progressText = status?.state === 'running' || clamped > 0 ? `${clamped}%` : ''
  const message = runStatusMessage(status)
  const observability = factorSnapshotMessageObservability(message)
  const processText = factorSnapshotProcessText(status)
  const spec = parseJSONRecord(governance.profit_arena_spec)
  const freshness = parseJSONRecord(governance.snapshot_freshness)
  const specStatus = String(spec.status || governance.snapshot_fresh_status || 'missing')
  const rawSpecMessage = String(governance.production_snapshot_message || spec.message || freshness.message || '等待因子快照签名校验')
  const specMessage = specStatus === 'fail'
    ? `${rawSpecMessage}；请重新运行全部/基础/行情更新，等待后置因子截面任务成功`
    : rawSpecMessage
  const specMissing = specStatus === 'missing'
  return (
    <div className="tableCard dependencyCard">
      <div className="tableHeader">
        <div>
          <div className="formTitle">后置因子截面任务</div>
          <div className="cardHint">数据更新成功后自动刷新通用策略因子快照；这里展示同一条可观测状态链路。</div>
        </div>
        <div className="taskActions">
          <span className={`badge ${statusBadgeClass(status?.state || '')}`}>{statusLabel(status?.state || '')}</span>
          {progressText ? <span className="dependencySummary">{progressText}</span> : null}
        </div>
      </div>
      <div className="progressTrack"><div style={{ width: `${clamped}%` }} /></div>
      <div className="dependencyMeta">
        <span>{isIdle ? '等待数据更新成功后自动触发' : message}</span>
        <span>{processText}</span>
        <span>{isIdle ? '等待首次更新' : (formatDate(status?.updated_at || '') || '未更新')}</span>
      </div>
      <div className="dependencyMeta">
        <span className={`badge ${specMissing ? 'created' : statusBadgeClass(specStatus)}`}>通用策略签名：{specMissing ? '等待' : statusLabel(specStatus)}</span>
        <span>{specMessage}</span>
      </div>
      {observability ? (
        <div className="dependencyMeta">
          <span className={`badge ${statusBadgeClass(observability.quality || '')}`}>质量：{statusLabel(observability.quality || '')}</span>
          <span>{observabilityText(observability)}</span>
        </div>
      ) : null}
    </div>
  )
}

function parseJSONRecord(value?: unknown): Record<string, unknown> {
  if (!value) return {}
  if (typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  try {
    const parsed = JSON.parse(String(value))
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function dependencyStateLabel(state: string) {
  if (state === 'ready') return '可用'
  if (state === 'missing') return '缺配置'
  return '异常'
}

function statusLabel(status: string) {
  return {
    idle: '空闲',
    pass: '通过',
    warn: '警告',
    missing: '缺失',
    running: '运行中',
    success: '完成',
    done: '完成',
    error: '失败',
    fail: '失败',
    failed: '失败',
    cancelled: '取消',
    interrupted: '中断',
    skipped: '已跳过',
    historical_offline: '已归档'
  }[status] || status || '-'
}

function statusBadgeClass(status: string) {
  if (status === 'pass') return 'success'
  if (status === 'warn') return 'running'
  if (status === 'running') return 'running'
  if (status === 'success' || status === 'done') return 'success'
  if (status === 'skipped') return 'created'
  if (status === 'fail' || status === 'missing' || status === 'error' || status === 'failed' || status === 'interrupted' || status === 'cancelled' || status === 'historical_offline') return 'failed'
  return 'created'
}

function runStatusMessage(status: RunStatus | null) {
  if (!status) return '等待任务状态上报'
  const parts = [status.stage, status.name, status.message].map((item) => String(item || '').trim()).filter(Boolean)
  if (parts.length) return parts.join(' · ')
  if (status.state === 'idle' || status.state === '') return '等待数据更新成功后自动触发'
  if (status.state === 'running') return '任务已启动，等待阶段进度上报'
  return '等待任务进度上报'
}

function factorSnapshotProcessText(status: RunStatus | null) {
  if (!status || status.state === 'idle' || status.state === '') return '未启动'
  if (status.state === 'running') return status.worker_pid ? `PID ${status.worker_pid}` : '等待进程号'
  if (status.state === 'success' || status.state === 'done') return '已完成'
  if (status.state === 'skipped') return '已跳过'
  if (status.state === 'error' || status.state === 'failed' || status.state === 'interrupted') return '异常结束'
  if (status.state === 'cancelled') return '已取消'
  return statusLabel(status.state)
}

type FactorSnapshotMessageObservability = {
  rows?: string
  factors?: string
  quality?: string
  drift?: string
  manifest?: string
}

function factorSnapshotMessageObservability(message: string): FactorSnapshotMessageObservability | null {
  const tokens = messageTokens(message)
  const observability: FactorSnapshotMessageObservability = {
    rows: tokens.rows,
    factors: tokens.factors,
    quality: tokens.quality,
    drift: tokens.drift,
    manifest: tokens.manifest,
  }
  return Object.values(observability).some(Boolean) ? observability : null
}

function observabilityText(value: FactorSnapshotMessageObservability) {
  const parts = [
    value.rows ? `${value.rows} 行` : '',
    value.factors ? `${value.factors} 因子` : '',
    value.drift ? `漂移 ${statusLabel(value.drift)}` : '',
    value.manifest ? `manifest ${shortPath(value.manifest)}` : '',
  ].filter(Boolean)
  return parts.join(' · ') || '等待因子快照摘要'
}

function messageTokens(message: string) {
  const out: Record<string, string> = {}
  String(message || '').split(/\s+/).forEach((field) => {
    const index = field.indexOf('=')
    if (index <= 0) return
    const key = field.slice(0, index).trim()
    const value = field.slice(index + 1).replace(/[,;]+$/g, '').trim()
    if (key && value) out[key] = value
  })
  return out
}

function shortPath(path: string) {
  if (!path) return ''
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts.slice(-3).join('/')
}

function dateLabel(value: string) {
  if (!value) return '—'
  const text = String(value)
  if (/^\d{8}$/.test(text)) return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`
  return formatDate(text) || text
}

function numberText(value: number) {
  if (!Number.isFinite(value)) return '0'
  return Math.round(value).toLocaleString('zh-CN')
}

function upsertDatasetStatus(items: DatasetUpdateStatus[], dataset: string, state: string): DatasetUpdateStatus[] {
  const meta = jobMetas.find((item) => item.name === dataset)
  const now = new Date().toISOString()
  const next: DatasetUpdateStatus = {
    dataset,
    category: meta?.category || '',
    state,
    progress_done: 0,
    progress_total: 0,
    message: '正在启动...',
    rows_written: 0,
    error_message: '',
    started_at: now,
    finished_at: '',
    updated_at: now,
  }
  const index = items.findIndex((item) => item.dataset === dataset)
  if (index < 0) {
    return [...items, next]
  }
  return items.map((item, i) => i === index ? { ...item, ...next } : item)
}

function markPhaseDatasetsRunning(items: DatasetUpdateStatus[], phase: string): DatasetUpdateStatus[] {
  const metas = phase === 'all'
    ? jobMetas
    : jobMetas.filter((item) => item.category === phase)
  return metas
    .reduce((acc, meta) => upsertDatasetStatus(acc, meta.name, 'pending'), items)
}

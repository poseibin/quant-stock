import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  listMarketDataFiles,
  scanMarketDataFiles,
  runDataUpdate,
  getDataUpdateStatus,
  emptyRunStatus,
  listDatasetUpdateStatus,
  checkExternalDependencies,
  type MarketDataFile,
  type RunStatus,
  type DatasetUpdateStatus,
  type ExternalDependencyStatus,
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

export function DataExplorerPage() {
  const [activeDataset, setActiveDataset] = useState<DatasetKey>('stock_basic')
  const [files, setFiles] = useState<MarketDataFile[]>([])
  const [phase, setPhase] = useState('all')
  const [updateStatus, setUpdateStatus] = useState<RunStatus | null>(null)
  const [datasetStatuses, setDatasetStatuses] = useState<DatasetUpdateStatus[]>([])
  const [dependencies, setDependencies] = useState<ExternalDependencyStatus[]>([])
  const [dependencyLoading, setDependencyLoading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const pollStartedAtRef = useRef(0)

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
        const [status, dsStatus] = await Promise.all([
          getDataUpdateStatus(),
          listDatasetUpdateStatus(),
        ])
        setUpdateStatus(status)
        setDatasetStatuses(dsStatus)
        if (status.state !== 'running') {
          if (Date.now() - pollStartedAtRef.current < 3500) {
            return
          }
          stopPoll()
          load()
        }
      } catch (error) {
        console.error('[data] poll update status failed', error)
      }
    }, 1500)
  }, [stopPoll])

  useEffect(() => () => stopPoll(), [stopPoll])

  const handleUpdate = useCallback(async () => {
    try {
      await runDataUpdate({ phase, start_date: '' })
      setUpdateStatus(emptyRunStatus('data_update', { state: 'running', message: '正在启动...' }))
      setDatasetStatuses((prev) => markPhaseDatasetsRunning(prev, phase))
      startPoll()
    } catch (error) {
      console.error('[data] start update failed', error)
      setUpdateStatus(emptyRunStatus('data_update', { state: 'error', message: error instanceof Error ? error.message : '启动失败' }))
    }
  }, [phase, startPoll])

  const handleUpdateDataset = useCallback(async (dataset: string) => {
    try {
      await runDataUpdate({ phase: 'all', start_date: '', dataset })
      setUpdateStatus(emptyRunStatus('data_update', { state: 'running', total: 1, name: dataset, message: '正在启动...' }))
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

  const isRunning = updateStatus?.state === 'running'

  return (
    <div className="taskPage">
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
    </div>
  )
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

function dependencyStateLabel(state: string) {
  if (state === 'ready') return '可用'
  if (state === 'missing') return '缺配置'
  return '异常'
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
  return metas.reduce((acc, meta) => upsertDatasetStatus(acc, meta.name, 'pending'), items)
}

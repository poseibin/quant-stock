import { useMemo } from 'react'
import { DataGrid, type Column } from 'react-data-grid'
import { formatBytes, formatDate } from '../../components/format'
import { buildJobHealth } from './dataUtils'
import type { DatasetUpdateStatus } from '../../services/app'

interface Phase {
  value: string
  label: string
}

type JobHealth = ReturnType<typeof buildJobHealth>

type HealthRow = JobHealth & {
  runStatus?: DatasetUpdateStatus
  updatedAtText: string
  reasonText: string
  missingYearsText: string
}

export function DataHealthPanel({
  items,
  onRefresh,
  onUpdate,
  onUpdateDataset,
  phase,
  onPhaseChange,
  phases,
  isUpdating,
  statusByDataset,
}: {
  items: JobHealth[]
  onRefresh: () => void
  onUpdate: () => void
  onUpdateDataset?: (dataset: string) => void
  phase?: string
  onPhaseChange?: (v: string) => void
  phases?: Phase[]
  isUpdating?: boolean
  statusByDataset?: Record<string, DatasetUpdateStatus>
}) {
  const filtered = !phase || phase === 'all' ? items : items.filter((item) => item.category === phase)
  const rows = useMemo<HealthRow[]>(() => filtered.map((item) => {
    const runStatus = statusByDataset?.[item.name]
    const updatedAtText = runStatus?.state === 'running'
      ? (runStatus.message || '—')
      : (runStatus?.finished_at
          ? formatDate(runStatus.finished_at)
          : formatDate(item.latestUpdatedAt))
    return {
      ...item,
      runStatus,
      updatedAtText: updatedAtText || '—',
      reasonText: runStatus?.error_message || (runStatus?.state === 'running' ? runStatus.message : '') || item.reason || '',
      missingYearsText: item.missingYears.length > 0 ? item.missingYears.join(', ') : '—'
    }
  }), [filtered, statusByDataset])

  const columns = useMemo<Column<HealthRow>[]>(() => [
    {
      key: 'dataset',
      name: '数据集',
      width: 210,
      frozen: true,
      renderCell: ({ row }) => (
        <div>
          <div>{row.title}</div>
          <div className="mono cardHint">{row.name}</div>
        </div>
      )
    },
    {
      key: 'category',
      name: '分类',
      width: 80,
      renderCell: ({ row }) => row.categoryLabel
    },
    {
      key: 'status',
      name: '状态',
      width: 120,
      renderCell: ({ row }) => {
        const runStatus = row.runStatus
        if (runStatus?.state === 'running') {
          const text = runStatus.progress_total > 0
            ? `更新中 ${runStatus.progress_done}/${runStatus.progress_total}`
            : '更新中'
          return <span className="healthBadge partial" title={runStatus.message}>{text}</span>
        }
        if (runStatus?.state === 'pending') {
          return <span className="healthBadge partial">等待中</span>
        }
        if (runStatus?.state === 'failed') {
          return <span className="healthBadge missing" title={runStatus.error_message}>失败</span>
        }
        if (runStatus?.state === 'skipped') {
          return <span className="healthBadge partial" title={runStatus.error_message || runStatus.message}>已跳过</span>
        }
        return <span className={`healthBadge ${row.status}`}>{row.label}</span>
      }
    },
    {
      key: 'coverage',
      name: '覆盖年份',
      width: 130,
      renderCell: ({ row }) => row.coverage || '—'
    },
    {
      key: 'updatedAt',
      name: '数据更新日期',
      width: 200,
      renderCell: ({ row }) => row.updatedAtText
    },
    {
      key: 'fileCount',
      name: '文件数',
      width: 86,
      renderCell: ({ row }) => row.fileCount
    },
    {
      key: 'size',
      name: '大小',
      width: 120,
      renderCell: ({ row }) => formatBytes(row.size)
    },
    {
      key: 'reason',
      name: '原因',
      minWidth: 260,
      resizable: true,
      renderCell: ({ row }) => <span className="reasonCell" title={row.reasonText}>{row.reasonText || '—'}</span>
    },
    {
      key: 'missingYears',
      name: '缺失年份',
      width: 360,
      resizable: true,
      cellClass: 'mono',
      renderCell: ({ row }) => <span className="missingYearsCell" title={row.missingYearsText}>{row.missingYearsText}</span>
    },
    {
      key: 'actions',
      name: '操作',
      width: 96,
      cellClass: 'dataGridActionsCell',
      headerCellClass: 'dataGridActionsCell',
      renderCell: ({ row }) => {
        const isRowUpdating = row.runStatus?.state === 'running' || (isUpdating && row.runStatus?.state === 'pending')
        const isOptional = Boolean(row.optional)
        return (
          <button
            className="tableActionButton"
            onClick={() => onUpdateDataset?.(row.name)}
            disabled={isUpdating || !onUpdateDataset || isOptional}
            title={isOptional ? `${row.title} 为非阻塞数据，默认跳过，不影响通用策略` : `更新 ${row.title}`}
          >
            {isOptional ? '非阻塞' : isRowUpdating ? '更新中' : '更新'}
          </button>
        )
      }
    }
  ], [isUpdating, onUpdateDataset])

  return (
    <div className="tableCard healthCard">
      <div className="tableHeader">
        <div>
          <div className="formTitle">数据状态</div>
          <div className="cardHint">检查原子数据覆盖；运行全部/基础/行情更新成功后会自动抽取通用策略因子截面。股东明细类数据为非阻塞项，默认跳过，不影响通用策略。</div>
        </div>
        <div className="taskActions">
          {phases && onPhaseChange && (
            <select
              className="selectInput"
              value={phase}
              onChange={(e) => onPhaseChange(e.target.value)}
              disabled={isUpdating}
            >
              {phases.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          )}
          <button className="secondaryButton" onClick={onRefresh} disabled={isUpdating}>刷新状态</button>
          <button className="primaryButton" onClick={onUpdate} disabled={isUpdating}>
            {isUpdating ? '更新中…' : '更新数据并抽因子'}
          </button>
        </div>
      </div>
      <div className="taskGridShell dataHealthGridShell">
        <DataGrid
          className="taskGrid dataHealthGrid rdg-dark"
          columns={columns}
          rows={rows}
          rowKeyGetter={(row) => row.name}
          rowHeight={66}
          headerRowHeight={48}
          defaultColumnOptions={{ resizable: true }}
          enableVirtualization={false}
        />
        {rows.length === 0 && <div className="taskGridEmpty">该分类下暂无数据集</div>}
      </div>
    </div>
  )
}

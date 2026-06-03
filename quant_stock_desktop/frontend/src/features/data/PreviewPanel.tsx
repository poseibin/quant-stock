import type { DatasetPreview } from '../../services/app'

export function PreviewPanel({ preview }: { preview: DatasetPreview }) {
  if (preview.rows.length === 0) {
    return <div className="emptyState">暂无预览数据</div>
  }

  return (
    <table>
      <thead>
        <tr>
          {preview.columns.map((column) => <th key={column}>{column}</th>)}
        </tr>
      </thead>
      <tbody>
        {preview.rows.map((row, rowIndex) => (
          <tr key={`${preview.dataset}-${rowIndex}`}>
            {preview.columns.map((column) => <td key={column} className="mono">{row[column] || '—'}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

import type { DatasetKey } from './dataUtils'
import { datasetCards, datasetStats } from './dataUtils'
import type { MarketDataFile } from '../../services/app'

export function DatasetCards({ activeDataset, files, openDataset }: { activeDataset: DatasetKey; files: MarketDataFile[]; openDataset: (dataset: DatasetKey) => void }) {
  return (
    <div className="datasetGrid">
      {datasetCards.map((item) => {
        const stats = datasetStats(item, files)
        return (
          <button key={item.id} className={activeDataset === item.id ? 'datasetCard active' : 'datasetCard'} onClick={() => openDataset(item.id)}>
            <span>{item.title}</span>
            <b>{item.name}</b>
            <em>{item.desc}</em>
            <small>{stats.text}</small>
          </button>
        )
      })}
    </div>
  )
}

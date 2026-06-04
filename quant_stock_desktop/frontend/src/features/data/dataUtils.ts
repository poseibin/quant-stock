import type { MarketDataFile } from '../../services/app'
import { formatBytes } from '../../components/format'

export type DatasetKey = 'stock_basic' | 'daily' | 'trade_cal' | 'daily_basic' | 'adj_factor' | 'finance' | 'top_list' | 'top10_holders'

export type DatasetCardConfig = {
  id: DatasetKey
  title: string
  name: string
  desc: string
  datasets: string[]
  expectedYears?: [number, number]
}

export const datasetCards: DatasetCardConfig[] = [
  { id: 'stock_basic', title: '股票基础信息', name: 'stock_basic', desc: '股票代码、名称、行业、上市状态', datasets: ['stock_basic'] },
  { id: 'daily', title: '日线行情', name: 'daily', desc: '开高低收、成交量、涨跌幅', datasets: ['daily'], expectedYears: [2010, 2026] },
  { id: 'trade_cal', title: '交易日历', name: 'trade_cal', desc: '交易所开市与休市日期', datasets: ['trade_cal'] },
  { id: 'daily_basic', title: '每日指标', name: 'daily_basic', desc: '估值、换手率、量比等指标', datasets: ['daily_basic'], expectedYears: [2010, 2026] },
  { id: 'adj_factor', title: '复权因子', name: 'adj_factor', desc: '前后复权计算所需因子', datasets: ['adj_factor'], expectedYears: [2010, 2026] },
  { id: 'finance', title: '财务数据', name: 'income / balancesheet / cashflow', desc: '利润表、资产负债表、现金流', datasets: ['income', 'balancesheet', 'cashflow'], expectedYears: [2010, 2026] },
  { id: 'top10_holders', title: '前十大股东', name: 'top10_holders', desc: '国家队跟踪所需的十大股东数据', datasets: ['top10_holders'], expectedYears: [2024, 2026] },
  { id: 'top_list', title: '龙虎榜', name: 'top_list / top_inst', desc: '龙虎榜明细和机构席位数据', datasets: ['top_list', 'top_inst'], expectedYears: [2024, 2026] }
]

// 每个数据集（与后端 JobEntry.Name 一一对应）的展示元数据。
export type DatasetCategory = 'basic' | 'price' | 'finance' | 'event'

export const categoryLabels: Record<DatasetCategory, string> = {
  basic: '基础',
  price: '行情',
  finance: '财务',
  event: '事件'
}

export type JobMeta = {
  name: string
  title: string
  category: DatasetCategory
  expectedYears?: [number, number]
}

export const jobMetas: JobMeta[] = [
  { name: 'stock_basic', title: '股票基础信息', category: 'basic' },
  { name: 'trade_cal', title: '交易日历', category: 'basic' },
  { name: 'daily', title: '日线行情', category: 'price', expectedYears: [2010, 2026] },
  { name: 'daily_basic', title: '每日指标', category: 'price', expectedYears: [2010, 2026] },
  { name: 'adj_factor', title: '复权因子', category: 'price', expectedYears: [2010, 2026] },
  { name: 'income', title: '利润表', category: 'finance', expectedYears: [2010, 2026] },
  { name: 'balancesheet', title: '资产负债表', category: 'finance', expectedYears: [2010, 2026] },
  { name: 'cashflow', title: '现金流量表', category: 'finance', expectedYears: [2010, 2026] },
  { name: 'fina_indicator', title: '财务指标', category: 'finance', expectedYears: [2010, 2026] },
  { name: 'forecast', title: '业绩预告', category: 'finance', expectedYears: [2010, 2026] },
  { name: 'stk_holdertrade', title: '股东增减持', category: 'event', expectedYears: [2010, 2026] },
  { name: 'top10_holders', title: '前十大股东', category: 'event', expectedYears: [2024, 2026] },
  { name: 'top_list', title: '龙虎榜明细', category: 'event', expectedYears: [2024, 2026] },
  { name: 'top_inst', title: '龙虎榜机构', category: 'event', expectedYears: [2024, 2026] }
]

export function partitionYear(partition: string) {
  const match = partition.match(/year=(\d{4})/)
  return match ? Number(match[1]) : 0
}

export function buildDatasetHealth(config: DatasetCardConfig, files: MarketDataFile[]) {
  const matched = files.filter((file) => config.datasets.includes(file.data_type))
  const years = Array.from(new Set(matched.map((file) => partitionYear(file.partition_name)).filter(Boolean))).sort((a, b) => a - b)
  const missingYears = config.expectedYears ? range(config.expectedYears[0], config.expectedYears[1]).filter((year) => !years.includes(year)) : []
  const hasMissingDataset = config.datasets.some((dataset) => !matched.some((file) => file.data_type === dataset))
  const status = matched.length === 0 || hasMissingDataset ? 'missing' : missingYears.length > 0 ? 'stale' : 'ready'
  return {
    id: config.id,
    title: config.title,
    status,
    label: status === 'ready' ? '正常' : status === 'stale' ? '需更新' : '缺失',
    coverage: years.length > 0 ? `${years[0]}-${years[years.length - 1]}` : '',
    latestUpdatedAt: latestUpdatedAt(matched),
    missingYears,
    fileCount: matched.length,
    size: matched.reduce((sum, file) => sum + file.file_size, 0)
  }
}

// 单 job 行的健康信息（按 JobEntry.Name 维度计算）。
export function buildJobHealth(meta: JobMeta, files: MarketDataFile[]) {
  const matched = files.filter((file) => file.data_type === meta.name)
  const years = Array.from(new Set(matched.map((file) => partitionYear(file.partition_name)).filter(Boolean))).sort((a, b) => a - b)
  const missingYears = meta.expectedYears ? range(meta.expectedYears[0], meta.expectedYears[1]).filter((year) => !years.includes(year)) : []
  const latestExpectedYear = meta.expectedYears?.[1]
  const hasLatestYear = latestExpectedYear ? years.includes(latestExpectedYear) : false
  const hasOnlyHistoricalGaps = missingYears.length > 0 && hasLatestYear
  const status = matched.length === 0 ? 'missing' : missingYears.length > 0 ? 'stale' : 'ready'
  const label = status === 'ready'
    ? '正常'
    : status === 'missing'
      ? '缺失'
      : '缺数据'
  const reason = missingYears.length > 0
    ? (hasOnlyHistoricalGaps
        ? `最新年份已有，历史缺口：${missingYears.join(', ')}。`
        : `缺少年份：${missingYears.join(', ')}。`)
    : ''
  return {
    name: meta.name,
    title: meta.title,
    category: meta.category,
    categoryLabel: categoryLabels[meta.category],
    status,
    label,
    coverage: years.length > 0 ? `${years[0]}-${years[years.length - 1]}` : '',
    latestUpdatedAt: latestUpdatedAt(matched),
    missingYears,
    reason,
    fileCount: matched.length,
    size: matched.reduce((sum, file) => sum + file.file_size, 0)
  }
}

export function datasetStats(config: DatasetCardConfig, files: MarketDataFile[]) {
  const matched = files.filter((file) => config.datasets.includes(file.data_type))
  return {
    count: matched.length,
    text: matched.length > 0 ? `${matched.length} 文件 / ${formatBytes(matched.reduce((sum, file) => sum + file.file_size, 0))}` : '未建立索引'
  }
}

function latestUpdatedAt(files: MarketDataFile[]) {
  const values = files
    .map((file) => file.updated_at)
    .filter(Boolean)
    .sort()
  return values.length > 0 ? values[values.length - 1] : ''
}

function range(start: number, end: number) {
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
}

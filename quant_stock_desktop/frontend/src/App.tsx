import { useEffect, useState } from 'react'
import { Activity, BellRing, ClipboardList, Database, FlaskConical, Search, Settings, Trophy, WalletCards } from 'lucide-react'
import { getAppInfo, getPositionRecommendation, type AppInfo } from './services/app'
import { DashboardPage } from './pages/DashboardPage'
import { DataExplorerPage } from './pages/DataExplorerPage'
import { FactorResearchPage } from './pages/FactorResearchPage'
import { PositionPage } from './pages/PositionPage'
import { ProfitArenaPage } from './pages/ProfitArenaPage'
import { ScheduleNotifyPage } from './pages/ScheduleNotifyPage'
import { SettingsPage } from './pages/SettingsPage'
import { StockResearchPage } from './pages/StockResearchPage'
import { TaskCenterPage } from './pages/TaskCenterPage'
import { formatDate } from './components/format'
import 'react-data-grid/lib/styles.css'
import './styles.css'

type Page = 'dashboard' | 'factorResearch' | 'profitArena' | 'positions' | 'research' | 'scheduleNotify' | 'taskCenter' | 'data' | 'settings'

type NavigationState = {
  page: Page
  researchCode: string
  researchReturnPage: Page | null
}

const pages: Array<{ id: Page; label: string; icon: typeof Activity }> = [
  { id: 'dashboard', label: '总览', icon: Activity },
  { id: 'data', label: '数据管理', icon: Database },
  { id: 'profitArena', label: '通用策略', icon: Trophy },
  { id: 'positions', label: '持仓管理', icon: WalletCards },
  { id: 'taskCenter', label: '任务中心', icon: ClipboardList },
  { id: 'scheduleNotify', label: '定时通知', icon: BellRing },
  { id: 'factorResearch', label: '因子研究留档', icon: FlaskConical },
  { id: 'research', label: '个股研究', icon: Search },
  { id: 'settings', label: '设置', icon: Settings }
]

const navGroups: Array<{ title: string; items: typeof pages }> = [
  { title: '生产链路', items: pages.filter((item) => ['dashboard', 'data', 'profitArena', 'positions', 'taskCenter', 'scheduleNotify'].includes(item.id)) },
  { title: '研究留档', items: pages.filter((item) => ['factorResearch', 'research'].includes(item.id)) },
  { title: '系统', items: pages.filter((item) => item.id === 'settings') }
]

const navigationStorageKey = 'quant-stock.navigation'
const pageIds = new Set<Page>(pages.map((item) => item.id))

function App() {
  const initialNavigation = loadNavigationState()
  const [page, setPage] = useState<Page>(initialNavigation.page)
  const [appInfo, setAppInfo] = useState<AppInfo>({ name: 'Quant Stock 生产工作台', version: 'loading' })
  const [latestSignalAt, setLatestSignalAt] = useState('')
  const [researchCode, setResearchCode] = useState(initialNavigation.researchCode)
  const [researchReturnPage, setResearchReturnPage] = useState<Page | null>(initialNavigation.researchReturnPage)

  const navigatePage = (nextPage: Page) => {
    syncPageToUrl(nextPage)
    setPage(nextPage)
    if (nextPage !== 'research') {
      setResearchReturnPage(null)
    }
  }

  const openResearch = (tsCode: string) => {
    const code = tsCode.trim()
    if (!code) return
    setResearchCode(code)
    setResearchReturnPage(page === 'research' ? researchReturnPage : page)
    syncPageToUrl('research')
    setPage('research')
  }

  const backFromResearch = () => {
    if (!researchReturnPage) return
    syncPageToUrl(researchReturnPage)
    setPage(researchReturnPage)
    setResearchReturnPage(null)
  }

  useEffect(() => {
    getAppInfo().then(setAppInfo)
    getPositionRecommendation()
      .then((rec) => setLatestSignalAt(rec.generated_at || ''))
      .catch(() => {})
  }, [])

  useEffect(() => {
    saveNavigationState({ page, researchCode, researchReturnPage })
  }, [page, researchCode, researchReturnPage])

  useEffect(() => {
    const applyUrlPage = () => {
      const nextPage = readPageFromUrl()
      if (nextPage) {
        setPage(nextPage)
        if (nextPage !== 'research') {
          setResearchReturnPage(null)
        }
      }
    }
    applyUrlPage()
    window.addEventListener('popstate', applyUrlPage)
    return () => window.removeEventListener('popstate', applyUrlPage)
  }, [])

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark">Q</div>
          <div>
            <div className="brandName">Quant Stock</div>
            <div className="brandSub">{appVersionLabel(appInfo.version)}</div>
          </div>
        </div>

        <nav className="nav">
          {navGroups.map((group) => (
            <div className="navGroup" key={group.title}>
              <div className="navSectionTitle">{group.title}</div>
              {group.items.map((item) => {
                const Icon = item.icon
                return (
                  <button key={item.id} className={page === item.id ? 'navItem active' : 'navItem'} onClick={() => navigatePage(item.id)}>
                    <Icon size={18} />
                    <span>{item.label}</span>
                  </button>
                )
              })}
            </div>
          ))}
        </nav>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">QUANT STOCK WORKSPACE</div>
            <h1>{titleOf(page)}</h1>
          </div>
          {latestSignalAt ? <div className="statusPill">最近更新 {formatDate(latestSignalAt)}</div> : null}
        </header>

        <section className="content">{renderPage(page, appInfo, openResearch, navigatePage, researchCode, researchReturnPage, backFromResearch)}</section>
      </main>
    </div>
  )
}

function loadNavigationState(): NavigationState {
  const fallback: NavigationState = { page: 'dashboard', researchCode: '', researchReturnPage: null }
  const urlPage = readPageFromUrl()
  if (urlPage) return { ...fallback, page: urlPage }
  try {
    const stored = window.localStorage.getItem(navigationStorageKey)
    if (!stored) return fallback
    const parsed = JSON.parse(stored) as Partial<NavigationState>
    const page = isPage(parsed.page) ? parsed.page : fallback.page
    const researchReturnPage = isPage(parsed.researchReturnPage) && parsed.researchReturnPage !== 'research' ? parsed.researchReturnPage : null
    return {
      page,
      researchCode: typeof parsed.researchCode === 'string' ? parsed.researchCode : '',
      researchReturnPage
    }
  } catch {
    return fallback
  }
}

function saveNavigationState(state: NavigationState) {
  try {
    window.localStorage.setItem(navigationStorageKey, JSON.stringify(state))
  } catch {
    // Ignore storage failures; navigation still works for the current session.
  }
}

function isPage(value: unknown): value is Page {
  return typeof value === 'string' && pageIds.has(value as Page)
}

function readPageFromUrl(): Page | null {
  try {
    const params = new URLSearchParams(window.location.search)
    const queryPage = params.get('page') || params.get('view') || params.get('tab')
    if (isPage(queryPage)) return queryPage
    const hashPage = window.location.hash.replace(/^#\/?/, '')
    if (isPage(hashPage)) return hashPage
  } catch {
    return null
  }
  return null
}

function syncPageToUrl(page: Page) {
  try {
    const url = new URL(window.location.href)
    url.searchParams.set('page', page)
    url.hash = ''
    window.history.pushState({}, '', url)
  } catch {
    // Navigation state is still persisted in localStorage when URL sync is unavailable.
  }
}

function titleOf(page: Page) {
  switch (page) {
    case 'dashboard': return '总览'
    case 'factorResearch': return '因子研究留档'
    case 'profitArena': return '通用策略'
    case 'positions': return '持仓管理'
    case 'research': return '个股研究'
    case 'scheduleNotify': return '定时通知'
    case 'taskCenter': return '任务中心'
    case 'data': return '数据管理'
    case 'settings': return '设置'
  }
}

function appVersionLabel(version: string) {
  if (version === 'runtime-offline') return '生产工作台 · 运行时未连接'
  if (version === 'loading') return '生产工作台'
  if (version.includes('profit-arena')) return '生产工作台 · 通用策略'
  return `生产工作台 · ${version}`
}

function renderPage(page: Page, appInfo: AppInfo, openResearch: (tsCode: string) => void, navigatePage: (page: Page) => void, researchCode: string, researchReturnPage: Page | null, backFromResearch: () => void) {
  if (page === 'dashboard') return <DashboardPage appInfo={appInfo} />
  if (page === 'factorResearch') return <FactorResearchPage onOpenResearch={openResearch} />
  if (page === 'profitArena') return <ProfitArenaPage onOpenResearch={openResearch} onOpenData={() => navigatePage('data')} />
  if (page === 'positions') return <PositionPage onOpenResearch={openResearch} />
  if (page === 'research') return <StockResearchPage initialTsCode={researchCode} returnLabel={researchReturnPage ? titleOf(researchReturnPage) : ''} onBack={researchReturnPage ? backFromResearch : undefined} />
  if (page === 'scheduleNotify') return <ScheduleNotifyPage />
  if (page === 'taskCenter') return <TaskCenterPage onOpenResearch={openResearch} />
  if (page === 'data') return <DataExplorerPage />
  if (page === 'settings') return <SettingsPage />

  return (
    <div className="emptyState">
      <h2>{titleOf(page)}</h2>
      <p>该模块未进入当前生产工作台，请从左侧生产链路进入数据、通用策略、持仓或任务中心。</p>
    </div>
  )
}

export default App

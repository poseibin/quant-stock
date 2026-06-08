import { useEffect, useState } from 'react'
import { Activity, Database, Flame, FlaskConical, Radar, Repeat2, Search, Settings as SettingsIcon, WalletCards } from 'lucide-react'
import { getAppInfo, getPositionRecommendation, type AppInfo } from './services/app'
import { DashboardPage } from './pages/DashboardPage'
import { DataExplorerPage } from './pages/DataExplorerPage'
import { LimitBreakoutPage } from './pages/LimitBreakoutPage'
import { FactorResearchPage } from './pages/FactorResearchPage'
import { PositionPage } from './pages/PositionPage'
import { PolicySupportPage } from './pages/PolicySupportPage'
import { StockResearchPage } from './pages/StockResearchPage'
import { SettingsPage } from './pages/SettingsPage'
import { T0AssistantPage } from './pages/T0AssistantPage'
import 'react-data-grid/lib/styles.css'
import './styles.css'

type Page = 'dashboard' | 'factorResearch' | 'positions' | 't0Assistant' | 'research' | 'policySupport' | 'breakout' | 'flatBreakout' | 'data' | 'settings'

type NavigationState = {
  page: Page
  researchCode: string
  researchReturnPage: Page | null
  researchProjection: boolean
}

const pages: Array<{ id: Page; label: string; icon: typeof Activity }> = [
  { id: 'dashboard', label: '总览', icon: Activity },
  { id: 'positions', label: '持仓管理', icon: WalletCards },
  { id: 'factorResearch', label: '通用策略', icon: FlaskConical },
  { id: 't0Assistant', label: '做T助手', icon: Repeat2 },
  { id: 'breakout', label: '涨停预警', icon: Flame },
  { id: 'flatBreakout', label: '横盘预警', icon: Radar },
  { id: 'research', label: '个股研究', icon: Search },
  { id: 'policySupport', label: '托底监测', icon: Radar },
  { id: 'data', label: '数据管理', icon: Database },
  { id: 'settings', label: '设置', icon: SettingsIcon }
]

const navigationStorageKey = 'quant-stock.navigation'
const pageIds = new Set<Page>(pages.map((item) => item.id))

function App() {
  const initialNavigation = loadNavigationState()
  const [page, setPage] = useState<Page>(initialNavigation.page)
  const [appInfo, setAppInfo] = useState<AppInfo>({ name: 'Quant Stock Desktop', version: 'loading' })
  const [latestSignalAt, setLatestSignalAt] = useState('')
  const [researchCode, setResearchCode] = useState(initialNavigation.researchCode)
  const [researchReturnPage, setResearchReturnPage] = useState<Page | null>(initialNavigation.researchReturnPage)
  const [researchProjection, setResearchProjection] = useState(initialNavigation.researchProjection)

  const navigatePage = (nextPage: Page) => {
    setPage(nextPage)
    if (nextPage !== 'research') {
      setResearchReturnPage(null)
      setResearchProjection(false)
    }
  }

  const openResearch = (tsCode: string, options?: { projection?: boolean }) => {
    const code = tsCode.trim()
    if (!code) return
    setResearchCode(code)
    setResearchReturnPage(page === 'research' ? researchReturnPage : page)
    setResearchProjection(Boolean(options?.projection))
    setPage('research')
  }

  const backFromResearch = () => {
    if (!researchReturnPage) return
    setPage(researchReturnPage)
    setResearchReturnPage(null)
    setResearchProjection(false)
  }

  useEffect(() => {
    getAppInfo().then(setAppInfo)
    getPositionRecommendation()
      .then((rec) => setLatestSignalAt(rec.generated_at || ''))
      .catch(() => {})
  }, [])

  useEffect(() => {
    saveNavigationState({ page, researchCode, researchReturnPage, researchProjection })
  }, [page, researchCode, researchReturnPage, researchProjection])

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark">Q</div>
          <div>
            <div className="brandName">Quant Stock</div>
            <div className="brandSub">Desktop {appInfo.version}</div>
          </div>
        </div>

        <nav className="nav">
          {pages.map((item) => {
            const Icon = item.icon
            return (
              <button key={item.id} className={page === item.id ? 'navItem active' : 'navItem'} onClick={() => navigatePage(item.id)}>
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            )
          })}
        </nav>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">QUANT STOCK WORKSPACE</div>
            <h1>{titleOf(page)}</h1>
          </div>
          {latestSignalAt ? <div className="statusPill">最近更新 {latestSignalAt}</div> : null}
        </header>

        <section className="content">{renderPage(page, appInfo, openResearch, researchCode, researchReturnPage, researchProjection, backFromResearch)}</section>
      </main>
    </div>
  )
}

function loadNavigationState(): NavigationState {
  const fallback: NavigationState = { page: 'dashboard', researchCode: '', researchReturnPage: null, researchProjection: false }
  try {
    const stored = window.localStorage.getItem(navigationStorageKey)
    if (!stored) return fallback
    const parsed = JSON.parse(stored) as Partial<NavigationState>
    const page = isPage(parsed.page) ? parsed.page : fallback.page
    const researchReturnPage = isPage(parsed.researchReturnPage) && parsed.researchReturnPage !== 'research' ? parsed.researchReturnPage : null
    return {
      page,
      researchCode: typeof parsed.researchCode === 'string' ? parsed.researchCode : '',
      researchReturnPage,
      researchProjection: Boolean(parsed.researchProjection)
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

function titleOf(page: Page) {
  switch (page) {
    case 'dashboard': return '总览'
    case 'factorResearch': return '通用策略'
    case 'positions': return '持仓管理'
    case 't0Assistant': return '做T助手'
    case 'research': return '个股研究'
    case 'policySupport': return '托底监测'
    case 'breakout': return '涨停预警'
    case 'flatBreakout': return '横盘预警'
    case 'data': return '数据管理'
    case 'settings': return '设置'
  }
}

function renderPage(page: Page, appInfo: AppInfo, openResearch: (tsCode: string, options?: { projection?: boolean }) => void, researchCode: string, researchReturnPage: Page | null, researchProjection: boolean, backFromResearch: () => void) {
  if (page === 'dashboard') return <DashboardPage appInfo={appInfo} />
  if (page === 'factorResearch') return <FactorResearchPage onOpenResearch={openResearch} />
  if (page === 'positions') return <PositionPage onOpenResearch={openResearch} />
  if (page === 't0Assistant') return <T0AssistantPage onOpenResearch={openResearch} />
  if (page === 'research') return <StockResearchPage initialTsCode={researchCode} returnLabel={researchReturnPage ? titleOf(researchReturnPage) : ''} showLimitProjection={researchProjection} onBack={researchReturnPage ? backFromResearch : undefined} />
  if (page === 'policySupport') return <PolicySupportPage onOpenResearch={openResearch} />
  if (page === 'breakout') return <LimitBreakoutPage mode="momentum" onOpenResearch={openResearch} />
  if (page === 'flatBreakout') return <LimitBreakoutPage mode="breakout" onOpenResearch={openResearch} />
  if (page === 'data') return <DataExplorerPage />
  if (page === 'settings') return <SettingsPage />

  return (
    <div className="emptyState">
      <h2>{titleOf(page)}</h2>
      <p>页面骨架已创建，后续按实施任务清单逐步接入功能。</p>
    </div>
  )
}

export default App

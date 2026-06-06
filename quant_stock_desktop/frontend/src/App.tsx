import { useEffect, useState } from 'react'
import { Activity, Database, Flame, FlaskConical, ListChecks, Radar, Repeat2, Search, Settings as SettingsIcon, WalletCards } from 'lucide-react'
import { getAppInfo, getPositionRecommendation, type AppInfo } from './services/app'
import { DashboardPage } from './pages/DashboardPage'
import { DataExplorerPage } from './pages/DataExplorerPage'
import { LimitBreakoutPage } from './pages/LimitBreakoutPage'
import { FactorResearchPage } from './pages/FactorResearchPage'
import { PositionPage } from './pages/PositionPage'
import { PolicySupportPage } from './pages/PolicySupportPage'
import { StockResearchPage } from './pages/StockResearchPage'
import { SettingsPage } from './pages/SettingsPage'
import { TaskCenterPage } from './pages/TaskCenterPage'
import { T0AssistantPage } from './pages/T0AssistantPage'
import 'react-data-grid/lib/styles.css'
import './styles.css'

type Page = 'dashboard' | 'tasks' | 'factorResearch' | 'positions' | 't0Assistant' | 'research' | 'policySupport' | 'breakout' | 'data' | 'settings'

const pages: Array<{ id: Page; label: string; icon: typeof Activity }> = [
  { id: 'dashboard', label: '总览', icon: Activity },
  { id: 'positions', label: '持仓管理', icon: WalletCards },
  { id: 't0Assistant', label: '做T助手', icon: Repeat2 },
  { id: 'tasks', label: '评估中心', icon: ListChecks },
  { id: 'factorResearch', label: '因子研究', icon: FlaskConical },
  { id: 'research', label: '个股研究', icon: Search },
  { id: 'policySupport', label: '托底监测', icon: Radar },
  { id: 'breakout', label: '涨停预警', icon: Flame },
  { id: 'data', label: '数据管理', icon: Database },
  { id: 'settings', label: '设置', icon: SettingsIcon }
]

function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [appInfo, setAppInfo] = useState<AppInfo>({ name: 'Quant Stock Desktop', version: 'loading' })
  const [latestSignalAt, setLatestSignalAt] = useState('')
  const [researchCode, setResearchCode] = useState('')
  const [researchReturnPage, setResearchReturnPage] = useState<Page | null>(null)

  const openResearch = (tsCode: string) => {
    const code = tsCode.trim()
    if (!code) return
    setResearchCode(code)
    setResearchReturnPage(page === 'research' ? researchReturnPage : page)
    setPage('research')
  }

  const backFromResearch = () => {
    if (!researchReturnPage) return
    setPage(researchReturnPage)
    setResearchReturnPage(null)
  }

  useEffect(() => {
    getAppInfo().then(setAppInfo)
    getPositionRecommendation()
      .then((rec) => setLatestSignalAt(rec.generated_at || ''))
      .catch(() => {})
  }, [])

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
              <button key={item.id} className={page === item.id ? 'navItem active' : 'navItem'} onClick={() => setPage(item.id)}>
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

        <section className="content">{renderPage(page, appInfo, openResearch, researchCode, researchReturnPage, backFromResearch)}</section>
      </main>
    </div>
  )
}

function titleOf(page: Page) {
  switch (page) {
    case 'dashboard': return '总览'
    case 'tasks': return '评估中心'
    case 'factorResearch': return '因子研究'
    case 'positions': return '持仓管理'
    case 't0Assistant': return '做T助手'
    case 'research': return '个股研究'
    case 'policySupport': return '托底监测'
    case 'breakout': return '涨停预警'
    case 'data': return '数据管理'
    case 'settings': return '设置'
  }
}

function renderPage(page: Page, appInfo: AppInfo, openResearch: (tsCode: string) => void, researchCode: string, researchReturnPage: Page | null, backFromResearch: () => void) {
  if (page === 'dashboard') return <DashboardPage appInfo={appInfo} />
  if (page === 'tasks') return <TaskCenterPage onOpenResearch={openResearch} />
  if (page === 'factorResearch') return <FactorResearchPage />
  if (page === 'positions') return <PositionPage onOpenResearch={openResearch} />
  if (page === 't0Assistant') return <T0AssistantPage onOpenResearch={openResearch} />
  if (page === 'research') return <StockResearchPage initialTsCode={researchCode} returnLabel={researchReturnPage ? titleOf(researchReturnPage) : ''} onBack={researchReturnPage ? backFromResearch : undefined} />
  if (page === 'policySupport') return <PolicySupportPage onOpenResearch={openResearch} />
  if (page === 'breakout') return <LimitBreakoutPage onOpenResearch={openResearch} />
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

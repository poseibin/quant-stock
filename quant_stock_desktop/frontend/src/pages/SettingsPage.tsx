import { useEffect, useMemo, useState } from 'react'
import { activateStrategyVersion, getSettings, listStrategyVersions, reviewStrategyVersion, saveSettings, setStrategyVersionStatus, type Settings, type StrategySettings, type StrategyVersion, type ValidationIssue } from '../services/app'
import { Field } from '../components/Field'

const strategyOrder = [
  'market_regime_timing',
  'ml_factor_ranker',
  'multi_factor_composite',
  'small_cap_quality',
  'trend_pullback',
  'turtle_breakout',
  'dividend_quality',
  'earnings_revision',
  'industry_prosperity',
  'low_crowding_reversal',
  'event_enhanced',
  'beijing_satellite',
  'insider_buy',
  'lhb_follow',
  'trend_quality',
  'garp_quality',
  'moneyflow_pullback',
]

type JsonDrafts = Record<string, string>

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [saved, setSaved] = useState(false)
  const [jsonDrafts, setJsonDrafts] = useState<JsonDrafts>({})
  const [jsonErrors, setJsonErrors] = useState<Record<string, string>>({})
  const [versions, setVersions] = useState<Record<string, StrategyVersion[]>>({})
  const [openVersions, setOpenVersions] = useState<Record<string, boolean>>({})
  const [versionBusy, setVersionBusy] = useState('')
  const [selectedStrategy, setSelectedStrategy] = useState('')

  useEffect(() => {
    getSettings().then((response) => {
      setSettings(response.settings)
      setIssues(response.issues || [])
      setJsonDrafts(makeDrafts(response.settings))
    })
  }, [])

  const enabledWeight = useMemo(() => {
    if (!settings) return 0
    return Object.values(settings.strategies || {}).reduce((sum, strategy) => sum + (strategy.enabled ? Number(strategy.weight || 0) : 0), 0)
  }, [settings])

  if (!settings) {
    return <div className="emptyState">正在加载配置...</div>
  }

  const update = (key: keyof Settings, value: string | number) => {
    setSaved(false)
    setSettings({ ...settings, [key]: value })
  }

  const updatePortfolioRiskNumber = (key: string, value: number) => {
    const nextRisk = { ...(settings.portfolio_risk || {}), [key]: value }
    setSaved(false)
    setSettings({ ...settings, portfolio_risk: nextRisk })
    setJsonDrafts({ ...jsonDrafts, portfolio_risk: pretty(nextRisk) })
    setJsonErrors({ ...jsonErrors, portfolio_risk: '' })
  }

  const updateStrategy = (name: string, patch: Partial<StrategySettings>) => {
    setSaved(false)
    setSettings({
      ...settings,
      strategies: {
        ...settings.strategies,
        [name]: { ...settings.strategies[name], ...patch }
      }
    })
  }

  const updateJsonDraft = (path: string, value: string) => {
    setSaved(false)
    setJsonDrafts({ ...jsonDrafts, [path]: value })
    setJsonErrors({ ...jsonErrors, [path]: '' })
  }

  const applyJsonDrafts = (): Settings | null => {
    const next: Settings = {
      ...settings,
      strategies: { ...settings.strategies },
      portfolio_risk: settings.portfolio_risk || {},
      exit_rules: settings.exit_rules || {},
      governance_rules: settings.governance_rules || {}
    }
    const errors: Record<string, string> = {}

    for (const [path, draft] of Object.entries(jsonDrafts)) {
      try {
        const parsed = draft.trim() ? JSON.parse(draft) : {}
        const parts = path.split('.')
        if (parts[0] === 'strategies') {
          const [, name, section] = parts
          next.strategies[name] = { ...next.strategies[name], [section]: parsed }
        } else if (path === 'portfolio_risk') {
          next.portfolio_risk = parsed
        } else if (path === 'exit_rules') {
          next.exit_rules = parsed
        } else if (path === 'governance_rules') {
          next.governance_rules = parsed
        }
      } catch {
        errors[path] = 'JSON 格式有误'
      }
    }
    setJsonErrors(errors)
    return Object.keys(errors).length ? null : next
  }

  const onSave = async () => {
    const next = applyJsonDrafts()
    if (!next) return
    const response = await saveSettings(next)
    setSettings(response.settings)
    setIssues(response.issues || [])
    setJsonDrafts(makeDrafts(response.settings))
    setSaved(true)
    await refreshOpenVersions()
  }

  const loadVersions = async (name: string) => {
    setVersionBusy(name)
    try {
      const rows = await listStrategyVersions(name)
      setVersions((prev) => ({ ...prev, [name]: rows }))
      setOpenVersions((prev) => ({ ...prev, [name]: true }))
    } finally {
      setVersionBusy('')
    }
  }

  const refreshOpenVersions = async () => {
    const names = Object.entries(openVersions).filter(([, open]) => open).map(([name]) => name)
    if (names.length === 0) return
    const entries = await Promise.all(names.map(async (name) => [name, await listStrategyVersions(name)] as const))
    setVersions((prev) => ({ ...prev, ...Object.fromEntries(entries) }))
  }

  const activateVersion = async (name: string, version: number) => {
    setVersionBusy(`${name}@${version}`)
    try {
      const response = await activateStrategyVersion({ strategy: name, version })
      setSettings(response.settings)
      setIssues(response.issues || [])
      setJsonDrafts(makeDrafts(response.settings))
      setSaved(true)
      await loadVersions(name)
    } finally {
      setVersionBusy('')
    }
  }

  const reviewVersion = async (name: string, version: number) => {
    setVersionBusy(`${name}@${version}`)
    try {
      await reviewStrategyVersion({ strategy: name, version })
      await loadVersions(name)
    } finally {
      setVersionBusy('')
    }
  }

  const markPaperVersion = async (name: string, version: number) => {
    setVersionBusy(`${name}@${version}`)
    try {
      const rows = await setStrategyVersionStatus({ strategy: name, version, status: 'paper' })
      setVersions((prev) => ({ ...prev, [name]: rows }))
    } finally {
      setVersionBusy('')
    }
  }

  const strategyNames = orderedStrategyNames(settings.strategies || {})
  const detailStrategy = selectedStrategy && settings.strategies[selectedStrategy] ? settings.strategies[selectedStrategy] : null

  return (
    <div className="settingsPage">
      <div className="formCard">
        <div className="formTitle">本地运行配置</div>
        <div className="runtimeConfigGrid">
          <Field label="数据库后端" issue={findIssue(issues, 'database_backend')} className="runtimeField runtimeFieldCompact">
            <select value={settings.database_backend || 'sqlite'} disabled>
              <option value="sqlite">SQLite</option>
              <option value="mysql">MySQL</option>
            </select>
          </Field>
          <Field label="MySQL DSN" issue={findIssue(issues, 'mysql_dsn')} className="runtimeField runtimeFieldWide">
            <input
              value={settings.mysql_dsn || ''}
              readOnly={(settings.database_backend || 'sqlite') !== 'mysql'}
              placeholder={(settings.database_backend || 'sqlite') === 'mysql' ? 'user:pass@tcp(127.0.0.1:3306)/quant_stock?parseTime=true&charset=utf8mb4' : 'SQLite 包不使用 MySQL DSN'}
              onChange={(event) => update('mysql_dsn', event.target.value)}
            />
          </Field>
          <Field label="Tushare Token" issue={findIssue(issues, 'tushare_token')} className="runtimeField runtimeFieldWide">
            <input
              type="password"
              placeholder="请输入 Tushare Token"
              value={settings.tushare_token || ''}
              onChange={(event) => update('tushare_token', event.target.value)}
            />
          </Field>
          <Field label="DeepSeek Token" issue={findIssue(issues, 'deepseek_token')} className="runtimeField runtimeFieldWide">
            <input
              type="password"
              placeholder="请输入 DeepSeek Token"
              value={settings.deepseek_token || ''}
              onChange={(event) => update('deepseek_token', event.target.value)}
            />
          </Field>
          <Field label="DeepSeek 模型" issue={findIssue(issues, 'deepseek_model')} className="runtimeField runtimeFieldWide">
            <input
              value={settings.deepseek_model || 'deepseek-v4-pro'}
              onChange={(event) => update('deepseek_model', event.target.value)}
            />
          </Field>
          <Field label="默认初始资金" issue={findIssue(issues, 'default_initial_cash')} className="runtimeField runtimeFieldCompact">
            <input type="number" value={settings.default_initial_cash} onChange={(event) => update('default_initial_cash', Number(event.target.value))} />
          </Field>
          <Field label="默认调仓频率" issue={findIssue(issues, 'default_rebalance_freq')} className="runtimeField runtimeFieldCompact">
            <input type="number" value={settings.default_rebalance_freq} onChange={(event) => update('default_rebalance_freq', Number(event.target.value))} />
          </Field>
          <Field label="最大持仓数" issue={findIssue(issues, 'portfolio_risk.max_holdings')} className="runtimeField runtimeFieldCompact">
            <input
              type="number"
              min={1}
              max={300}
              value={numberSetting(settings.portfolio_risk?.max_holdings, 50)}
              onChange={(event) => updatePortfolioRiskNumber('max_holdings', Number(event.target.value))}
            />
          </Field>
          <Field label="任务并发数" issue={findIssue(issues, 'task_concurrency')} className="runtimeField runtimeFieldCompact">
            <input type="number" min={1} max={8} value={settings.task_concurrency || 2} onChange={(event) => update('task_concurrency', Number(event.target.value))} />
          </Field>
        </div>
      </div>

      <div className="formCard">
        <div className="formHeader">
          <div>
            <div className="formTitle">策略配置</div>
            <div className="formHint">启用权重合计：{enabledWeight.toFixed(2)}</div>
          </div>
          {detailStrategy && (
            <button className="secondaryButton quietButton" onClick={() => setSelectedStrategy('')}>返回列表</button>
          )}
        </div>
        {detailStrategy ? (
          <div className="strategyConfigDetail">
            <div className="strategyDetailHero">
              <div>
                <span className={`configStatusDot ${detailStrategy.enabled ? 'enabled' : ''}`} />
                <div>
                  <b>{detailStrategy.label || selectedStrategy}</b>
                  <em>{selectedStrategy}</em>
                </div>
              </div>
              <label className="toggleLine">
                <input type="checkbox" checked={detailStrategy.enabled} onChange={(event) => updateStrategy(selectedStrategy, { enabled: event.target.checked })} />
                <span>{detailStrategy.enabled ? '已启用' : '未启用'}</span>
              </label>
            </div>
            <div className="formGrid strategyDetailGrid">
              <Field label="权重" issue={findIssue(issues, `strategies.${selectedStrategy}.weight`)}>
                <input type="number" step="0.01" value={detailStrategy.weight} onChange={(event) => updateStrategy(selectedStrategy, { weight: Number(event.target.value) })} />
              </Field>
              <Field label="调仓">
                <select value={detailStrategy.rebalance} onChange={(event) => updateStrategy(selectedStrategy, { rebalance: event.target.value })}>
                  <option value="daily">daily</option>
                  <option value="weekly">weekly</option>
                  <option value="monthly">monthly</option>
                  <option value="quarterly">quarterly</option>
                  <option value="event">event</option>
                </select>
              </Field>
            </div>
            <div className="strategyJsonGrid">
              {(['universe', 'filters', 'selection', 'position'] as const).map((section) => (
                <JsonField
                  key={section}
                  label={section}
                  path={`strategies.${selectedStrategy}.${section}`}
                  drafts={jsonDrafts}
                  errors={jsonErrors}
                  onChange={updateJsonDraft}
                />
              ))}
            </div>
            <div className="strategyVersionPanel">
              <button className="secondaryButton quietButton" onClick={() => openVersions[selectedStrategy] ? setOpenVersions({ ...openVersions, [selectedStrategy]: false }) : loadVersions(selectedStrategy)}>
                {openVersions[selectedStrategy] ? '收起版本' : '查看版本'}
              </button>
              {openVersions[selectedStrategy] && (
                <StrategyVersionList
                  name={selectedStrategy}
                  rows={versions[selectedStrategy] || []}
                  busy={versionBusy}
                  onReview={reviewVersion}
                  onPaper={markPaperVersion}
                  onActivate={activateVersion}
                />
              )}
            </div>
          </div>
        ) : (
          <div className="strategyConfigTable">
            <div className="strategyConfigTableHead">
              <span>状态</span>
              <span>策略</span>
              <span>代码</span>
              <span>权重</span>
              <span>调仓</span>
              <span>配置概览</span>
              <span>操作</span>
            </div>
            {strategyNames.map((name) => {
              const strategy = settings.strategies[name]
              return (
                <div className="strategyConfigTableRow" key={name}>
                  <label className="compactSwitch">
                    <input type="checkbox" checked={strategy.enabled} onChange={(event) => updateStrategy(name, { enabled: event.target.checked })} />
                    <span>{strategy.enabled ? '启用' : '停用'}</span>
                  </label>
                  <b>{strategy.label || name}</b>
                  <span className="mono">{name}</span>
                  <span>{Number(strategy.weight || 0).toFixed(2)}</span>
                  <span>{strategy.rebalance || '—'}</span>
                  <span className="strategyConfigSummary">{strategyConfigSummary(strategy)}</span>
                  <button className="secondaryButton quietButton" onClick={() => setSelectedStrategy(name)}>详情</button>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="formCard">
        <div className="formTitle">组合风控、卖出与治理规则</div>
        <div className="configJsonGrid">
          <JsonField label="portfolio_risk" path="portfolio_risk" drafts={jsonDrafts} errors={jsonErrors} onChange={updateJsonDraft} />
          <JsonField label="exit_rules" path="exit_rules" drafts={jsonDrafts} errors={jsonErrors} onChange={updateJsonDraft} />
          <JsonField label="governance_rules" path="governance_rules" drafts={jsonDrafts} errors={jsonErrors} onChange={updateJsonDraft} />
        </div>
        <button className="primaryButton" onClick={onSave}>保存配置</button>
        {saved && <div className="saveHint">配置已保存，Python 策略会直接读取配置表。</div>}
      </div>
    </div>
  )
}

function JsonField({
  label,
  path,
  drafts,
  errors,
  onChange
}: {
  label: string
  path: string
  drafts: JsonDrafts
  errors: Record<string, string>
  onChange: (path: string, value: string) => void
}) {
  return (
    <label className="jsonField">
      <span>{label}</span>
      <textarea value={drafts[path] || '{}'} onChange={(event) => onChange(path, event.target.value)} spellCheck={false} />
      {errors[path] && <em>{errors[path]}</em>}
    </label>
  )
}

function StrategyVersionList({
  name,
  rows,
  busy,
  onReview,
  onPaper,
  onActivate
}: {
  name: string
  rows: StrategyVersion[]
  busy: string
  onReview: (name: string, version: number) => void
  onPaper: (name: string, version: number) => void
  onActivate: (name: string, version: number) => void
}) {
  const activeVersion = rows.find((row) => row.is_active)
  return (
    <div className="versionList">
      {rows.length > 0 && (
        <div className="versionListHeader">
          <span>版本</span>
          <span>来源 / 验证</span>
          <span>操作</span>
        </div>
      )}
      {rows.map((item) => (
        <div className="versionRow" key={`${name}-${item.version}`}>
          <div>
            <b>v{item.version}</b>
            <span className={item.is_active ? 'badge success' : 'badge created'}>{item.is_active ? '生效' : statusLabel(item.promotion_status)}</span>
            <em>{item.created_at}</em>
          </div>
          <div className="versionMeta">
            <span>{item.source || 'settings'}</span>
            <span>验证 {formatScore(item.validation?.score)}</span>
          </div>
          <div className="taskActions compactActions">
            <button className="secondaryButton quietButton" disabled={busy !== ''} onClick={() => onReview(name, item.version)}>复核</button>
            <button className="secondaryButton quietButton" disabled={item.is_active || item.promotion_status === 'paper' || busy !== ''} onClick={() => onPaper(name, item.version)}>模拟</button>
            <button className="secondaryButton startButton" disabled={item.is_active || busy !== ''} onClick={() => onActivate(name, item.version)}>设为生效</button>
          </div>
          <details className="versionDiff">
            <summary>参数差异</summary>
            <pre>{diffVersionConfig(item, activeVersion)}</pre>
          </details>
        </div>
      ))}
      {busy === name && <div className="mutedText">加载版本中...</div>}
      {rows.length === 0 && busy !== name && <div className="mutedText">暂无版本记录，保存配置后生成</div>}
    </div>
  )
}

function makeDrafts(settings: Settings): JsonDrafts {
  const drafts: JsonDrafts = {
    portfolio_risk: pretty(settings.portfolio_risk || {}),
    exit_rules: pretty(settings.exit_rules || {}),
    governance_rules: pretty(settings.governance_rules || {})
  }
  for (const [name, strategy] of Object.entries(settings.strategies || {})) {
    drafts[`strategies.${name}.universe`] = pretty(strategy.universe || {})
    drafts[`strategies.${name}.filters`] = pretty(strategy.filters || {})
    drafts[`strategies.${name}.selection`] = pretty(strategy.selection || {})
    drafts[`strategies.${name}.position`] = pretty(strategy.position || {})
  }
  return drafts
}

function pretty(value: unknown) {
  return JSON.stringify(value || {}, null, 2)
}

function strategyConfigSummary(strategy: StrategySettings) {
  const parts = [
    `universe ${objectSize(strategy.universe)}`,
    `filters ${objectSize(strategy.filters)}`,
    `selection ${objectSize(strategy.selection)}`,
    `position ${objectSize(strategy.position)}`
  ]
  return parts.join(' / ')
}

function objectSize(value: unknown) {
  return value && typeof value === 'object' && !Array.isArray(value) ? Object.keys(value as Record<string, unknown>).length : 0
}

function orderedStrategyNames(strategies: Record<string, StrategySettings>) {
  const seen = new Set<string>()
  const ordered = strategyOrder.filter((name) => {
    const exists = Boolean(strategies[name])
    if (exists) seen.add(name)
    return exists
  })
  const extras = Object.keys(strategies).filter((name) => !seen.has(name)).sort()
  return [...ordered, ...extras]
}

function findIssue(issues: ValidationIssue[], field: string) {
  return issues.find((issue) => issue.field === field)
}

function numberSetting(value: unknown, fallback: number) {
  const num = Number(value)
  return Number.isFinite(num) ? num : fallback
}

function statusLabel(status: string) {
  return ({ active: '生效', promotable: '可生效', research: '研究中', paper: '模拟中', rejected: '拒绝' } as Record<string, string>)[status] || status || '研究中'
}

function formatScore(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : '—'
}

function diffVersionConfig(item: StrategyVersion, active?: StrategyVersion) {
  if (!active || active.version === item.version) {
    return prettyCompact(item.config)
  }
  const keys = ['enabled', 'weight', 'rebalance', 'universe', 'filters', 'selection', 'position']
  const lines: string[] = []
  for (const key of keys) {
    const current = (item.config || {})[key]
    const base = (active.config || {})[key]
    if (JSON.stringify(current ?? null) !== JSON.stringify(base ?? null)) {
      lines.push(`${key}:`)
      lines.push(`  当前版本: ${prettyInline(current)}`)
      lines.push(`  生效版本: ${prettyInline(base)}`)
    }
  }
  return lines.length ? lines.join('\n') : '与当前生效版本一致'
}

function prettyCompact(value: unknown) {
  return JSON.stringify(value || {}, null, 2)
}

function prettyInline(value: unknown) {
  if (value === undefined) return '未设置'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value || {})
}

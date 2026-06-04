import { useEffect, useMemo, useState } from 'react'
import { activateStrategyVersion, getSettings, listStrategyVersions, reviewStrategyVersion, saveSettings, type Settings, type StrategySettings, type StrategyVersion, type ValidationIssue } from '../services/app'
import { Field } from '../components/Field'

const strategyOrder = ['market_regime_timing', 'multi_factor_composite', 'small_cap_quality', 'trend_pullback', 'dividend_quality', 'earnings_revision', 'industry_prosperity', 'low_crowding_reversal', 'event_enhanced', 'beijing_satellite']

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
      exit_rules: settings.exit_rules || {}
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

  const strategyNames = strategyOrder.filter((name) => settings.strategies?.[name])

  return (
    <div className="settingsPage">
      <div className="formCard">
        <div className="formTitle">本地运行配置</div>
        <div className="runtimeConfigGrid">
          <Field label="数据目录" issue={findIssue(issues, 'data_path')} className="runtimeField runtimeFieldWide">
            <input value={settings.data_path} onChange={(event) => update('data_path', event.target.value)} />
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
        </div>
      </div>

      <div className="formCard">
        <div className="formHeader">
          <div>
            <div className="formTitle">策略配置</div>
            <div className="formHint">启用权重合计：{enabledWeight.toFixed(2)}</div>
          </div>
        </div>
        <div className="strategyConfigGrid">
          {strategyNames.map((name) => {
            const strategy = settings.strategies[name]
            return (
              <div className="strategyConfigCard" key={name}>
                <div className="strategyConfigHead">
                  <label className="toggleLine">
                    <input type="checkbox" checked={strategy.enabled} onChange={(event) => updateStrategy(name, { enabled: event.target.checked })} />
                    <span>{strategy.label || name}</span>
                  </label>
                  <span className="mono">{name}</span>
                </div>
                <div className="formGrid">
                  <Field label="权重" issue={findIssue(issues, `strategies.${name}.weight`)}>
                    <input type="number" step="0.01" value={strategy.weight} onChange={(event) => updateStrategy(name, { weight: Number(event.target.value) })} />
                  </Field>
                  <Field label="调仓">
                    <select value={strategy.rebalance} onChange={(event) => updateStrategy(name, { rebalance: event.target.value })}>
                      <option value="daily">daily</option>
                      <option value="weekly">weekly</option>
                      <option value="monthly">monthly</option>
                      <option value="quarterly">quarterly</option>
                      <option value="event">event</option>
                    </select>
                  </Field>
                </div>
                {(['universe', 'filters', 'selection', 'position'] as const).map((section) => (
                  <JsonField
                    key={section}
                    label={section}
                    path={`strategies.${name}.${section}`}
                    drafts={jsonDrafts}
                    errors={jsonErrors}
                    onChange={updateJsonDraft}
                  />
                ))}
                <div className="strategyVersionPanel">
                  <button className="secondaryButton quietButton" onClick={() => openVersions[name] ? setOpenVersions({ ...openVersions, [name]: false }) : loadVersions(name)}>
                    {openVersions[name] ? '收起版本' : '版本'}
                  </button>
                  {openVersions[name] && (
                    <div className="versionList">
                      {(versions[name] || []).map((item) => (
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
                            <button className="secondaryButton quietButton" disabled={versionBusy !== ''} onClick={() => reviewVersion(name, item.version)}>复核</button>
                            <button className="secondaryButton startButton" disabled={item.is_active || versionBusy !== ''} onClick={() => activateVersion(name, item.version)}>设为生效</button>
                          </div>
                        </div>
                      ))}
                      {versionBusy === name && <div className="mutedText">加载版本中...</div>}
                      {(versions[name] || []).length === 0 && versionBusy !== name && <div className="mutedText">暂无版本记录，保存配置后生成</div>}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <div className="formCard">
        <div className="formTitle">组合风控与卖出规则</div>
        <div className="configJsonGrid">
          <JsonField label="portfolio_risk" path="portfolio_risk" drafts={jsonDrafts} errors={jsonErrors} onChange={updateJsonDraft} />
          <JsonField label="exit_rules" path="exit_rules" drafts={jsonDrafts} errors={jsonErrors} onChange={updateJsonDraft} />
        </div>
        <button className="primaryButton" onClick={onSave}>保存配置</button>
        {saved && <div className="saveHint">配置已保存到 SQLite，Python 策略会直接读取配置表。</div>}
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

function makeDrafts(settings: Settings): JsonDrafts {
  const drafts: JsonDrafts = {
    portfolio_risk: pretty(settings.portfolio_risk || {}),
    exit_rules: pretty(settings.exit_rules || {})
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

function findIssue(issues: ValidationIssue[], field: string) {
  return issues.find((issue) => issue.field === field)
}

function statusLabel(status: string) {
  return ({ active: '生效', promotable: '可生效', research: '研究中', rejected: '拒绝' } as Record<string, string>)[status] || status || '研究中'
}

function formatScore(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : '—'
}

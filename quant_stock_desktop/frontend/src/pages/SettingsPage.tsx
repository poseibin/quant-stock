import { useEffect, useMemo, useState } from 'react'
import { getSettings, saveSettings, type Settings, type StrategySettings, type ValidationIssue } from '../services/app'
import { Field } from '../components/Field'

const strategyOrder = ['forecast_revision', 'dividend_low_vol', 'trend_quality', 'garp_quality', 'moneyflow_pullback', 'small_cap_quality', 'reversal', 'insider_buy', 'lhb_follow', 'industry_rotation', 'beijing_se']

type JsonDrafts = Record<string, string>

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [saved, setSaved] = useState(false)
  const [jsonDrafts, setJsonDrafts] = useState<JsonDrafts>({})
  const [jsonErrors, setJsonErrors] = useState<Record<string, string>>({})

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
  }

  const strategyNames = strategyOrder.filter((name) => settings.strategies?.[name]).concat(
    Object.keys(settings.strategies || {}).filter((name) => !strategyOrder.includes(name))
  )

  return (
    <div className="settingsPage">
      <div className="formCard">
        <div className="formTitle">本地运行配置</div>
        <div className="runtimeConfigGrid">
          <Field label="Workspace 路径" issue={findIssue(issues, 'workspace_path')}>
            <input value={settings.workspace_path} onChange={(event) => update('workspace_path', event.target.value)} />
          </Field>
          <Field label="数据目录" issue={findIssue(issues, 'data_path')}>
            <input value={settings.data_path} onChange={(event) => update('data_path', event.target.value)} />
          </Field>
          <Field label="Tushare Token" issue={findIssue(issues, 'tushare_token')}>
            <input
              type="password"
              placeholder="请输入 Tushare Token"
              value={settings.tushare_token || ''}
              onChange={(event) => update('tushare_token', event.target.value)}
            />
          </Field>
          <Field label="默认初始资金" issue={findIssue(issues, 'default_initial_cash')}>
            <input type="number" value={settings.default_initial_cash} onChange={(event) => update('default_initial_cash', Number(event.target.value))} />
          </Field>
          <Field label="默认调仓频率" issue={findIssue(issues, 'default_rebalance_freq')}>
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

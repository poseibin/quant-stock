import { useEffect, useState } from 'react'
import { getSettings, saveSettings, type Settings, type ValidationIssue } from '../services/app'
import { Field } from '../components/Field'

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
  }

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

function findIssue(issues: ValidationIssue[], field: string) {
  return issues.find((issue) => issue.field === field)
}

function numberSetting(value: unknown, fallback: number) {
  const num = Number(value)
  return Number.isFinite(num) ? num : fallback
}

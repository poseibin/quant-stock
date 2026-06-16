import { useEffect, useState } from 'react'
import {
  getSettings,
  saveSettings,
  type Settings,
  type ValidationIssue
} from '../services/app'
import { Field } from '../components/Field'

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getSettings().then((response) => {
      setSettings(response.settings)
      setIssues(response.issues || [])
    })
  }, [])

  if (!settings) {
    return <div className="emptyState">正在加载配置...</div>
  }

  const update = (key: keyof Settings, value: string | number) => {
    setSaved(false)
    setSettings({ ...settings, [key]: value })
  }

  const updateSchedule = (patch: Partial<Settings['strategy_schedule']>) => {
    const current = settings.strategy_schedule || defaultSchedule()
    setSaved(false)
    setSettings({ ...settings, strategy_schedule: { ...current, ...patch } })
  }

  const updateScheduleTarget = (target: string, checked: boolean) => {
    const current = settings.strategy_schedule || defaultSchedule()
    updateSchedule({ targets: { ...(current.targets || {}), [target]: checked } })
  }

  const updateScheduleWeekday = (weekday: number, checked: boolean) => {
    const current = settings.strategy_schedule || defaultSchedule()
    const days = new Set(current.weekdays || [])
    if (checked) {
      days.add(weekday)
    } else {
      days.delete(weekday)
    }
    updateSchedule({ weekdays: Array.from(days).sort((a, b) => a - b) })
  }

  const onSave = async () => {
    const response = await saveSettings(settings)
    setSettings(response.settings)
    setIssues(response.issues || [])
    setSaved(true)
  }

  const schedule = settings.strategy_schedule || defaultSchedule()
  const selectedTargets = scheduleTargets.filter((target) => schedule.targets?.[target.key]).map((target) => target.label)
  const selectedWeekdays = weekdays.filter((day) => schedule.weekdays?.includes(day.value)).map((day) => day.label)

  return (
    <div className="settingsPage">
      <div className="formCard">
        <div className="formTitle">运行偏好</div>
        <div className="runtimeConfigGrid">
          <Field label="默认初始资金" issue={findIssue(issues, 'default_initial_cash')} className="runtimeField runtimeFieldCompact">
            <input type="number" value={settings.default_initial_cash} onChange={(event) => update('default_initial_cash', Number(event.target.value))} />
          </Field>
          <Field label="默认调仓频率" issue={findIssue(issues, 'default_rebalance_freq')} className="runtimeField runtimeFieldCompact">
            <input type="number" value={settings.default_rebalance_freq} onChange={(event) => update('default_rebalance_freq', Number(event.target.value))} />
          </Field>
          <Field label="任务并发数" issue={findIssue(issues, 'task_concurrency')} className="runtimeField runtimeFieldCompact">
            <input type="number" min={1} max={8} value={settings.task_concurrency || 2} onChange={(event) => update('task_concurrency', Number(event.target.value))} />
          </Field>
        </div>
        <div className="settingsActions configCardActions">
          <button className="primaryButton settingsButton" onClick={onSave}>保存配置</button>
        </div>
      </div>

      <div className="formCard schedulerCard">
        <div className="schedulerCardHeader">
          <div>
            <div className="formTitle">策略推荐定时器</div>
            <p className="recommendationMeta">收盘后自动刷新推荐，并把一键调仓清单推送到企业微信。</p>
          </div>
          <label className="schedulerToggle">
            <input
              type="checkbox"
              checked={Boolean(schedule.enabled)}
              onChange={(event) => updateSchedule({ enabled: event.target.checked })}
            />
            <span>{schedule.enabled ? '已启用' : '未启用'}</span>
          </label>
        </div>

        <div className="schedulerSummaryBar">
          <div>
            <span>触发时间（北京时间）</span>
            <b>{schedule.time_of_day || '22:00'}</b>
          </div>
          <div>
            <span>交易日</span>
            <b>{selectedWeekdays.length ? selectedWeekdays.join(' / ') : '未选择'}</b>
          </div>
          <div>
            <span>策略模块</span>
            <b>{selectedTargets.length ? selectedTargets.join(' / ') : '未选择'}</b>
          </div>
          <div>
            <span>通知</span>
            <b>{schedule.wechat_webhook ? '企业微信' : '配置文件未填'}</b>
          </div>
        </div>

        <div className="schedulerEditorGrid schedulerEditorGridSingle">
          <div className="schedulerPanel">
            <div className="schedulerPanelTitle">执行计划</div>
            <div className="schedulerInlineGrid">
              <Field label="触发时间（北京时间）" className="runtimeField runtimeFieldCompact schedulerTimeField">
                <input
                  type="time"
                  value={schedule.time_of_day || '22:00'}
                  onChange={(event) => updateSchedule({ time_of_day: event.target.value })}
                />
              </Field>
              <div className="schedulerChoiceBlock">
                <div className="formSubTitle">交易日</div>
                <div className="chipGrid weekdayGrid">
                  {weekdays.map((day) => (
                    <label className="schedulerChip" key={day.value}>
                      <input
                        type="checkbox"
                        checked={(schedule.weekdays || []).includes(day.value)}
                        onChange={(event) => updateScheduleWeekday(day.value, event.target.checked)}
                      />
                      <span>{day.label}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>

            <div className="schedulerPanelTitle">策略模块</div>
            <div className="chipGrid strategyChipGrid">
              {scheduleTargets.map((target) => (
                <label className="schedulerChip strategyChip" key={target.key}>
                  <input
                    type="checkbox"
                    checked={Boolean(schedule.targets?.[target.key])}
                    onChange={(event) => updateScheduleTarget(target.key, event.target.checked)}
                  />
                  <span>{target.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="settingsActions">
          <button className="primaryButton settingsButton" onClick={onSave}>保存定时器</button>
        </div>
        {saved && <div className="saveHint">配置已保存，Python 策略会直接读取配置表。</div>}
      </div>
    </div>
  )
}

const scheduleTargets = [
  { key: 'arena', label: '收益擂台' }
]

const weekdays = [
  { value: 1, label: '周一' },
  { value: 2, label: '周二' },
  { value: 3, label: '周三' },
  { value: 4, label: '周四' },
  { value: 5, label: '周五' }
]

function defaultSchedule(): Settings['strategy_schedule'] {
  return {
    enabled: false,
    time_of_day: '22:00',
    weekdays: [1, 2, 3, 4, 5],
    targets: { arena: true },
    wechat_webhook: '',
    wechat_users: []
  }
}

function findIssue(issues: ValidationIssue[], field: string) {
  return issues.find((issue) => issue.field === field)
}

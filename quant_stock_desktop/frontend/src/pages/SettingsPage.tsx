import { useEffect, useState } from 'react'
import {
  getProductionDiagnostics,
  getSettings,
  saveSettings,
  type Settings,
  type ValidationIssue
} from '../services/app'
import { Field } from '../components/Field'

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown>>({})
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getSettings().then((response) => {
      setSettings(response.settings)
      setIssues(response.issues || [])
      setError(response.issues?.find((issue) => issue.field === 'backend')?.message || '')
    }).catch((err) => {
      setError(err instanceof Error ? err.message : '加载配置失败')
    })
    getProductionDiagnostics().then(setDiagnostics).catch(() => {})
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

  const readOnlySettings = issues.some((issue) => issue.field === 'backend')
  const readOnlyTitle = readOnlySettings ? '桌面后端未连接，当前配置为只读安全视图' : undefined

  const onSave = async () => {
    if (readOnlySettings) {
      setSaved(false)
      setError('桌面后端未连接，当前配置为只读安全视图，不能保存或触发生产任务')
      return
    }
    setError('')
    try {
      const response = await saveSettings({
        ...settings,
        strategy_schedule: {
          ...(settings.strategy_schedule || defaultSchedule()),
          targets: { arena: true }
        }
      })
      setSettings(response.settings)
      setIssues(response.issues || [])
      setSaved(true)
    } catch (err) {
      setSaved(false)
      setError(err instanceof Error ? err.message : '保存配置失败')
    }
  }

  const schedule = settings.strategy_schedule || defaultSchedule()
  const selectedTargets = scheduleTargets.map((target) => target.label)
  const selectedWeekdays = weekdays.filter((day) => schedule.weekdays?.includes(day.value)).map((day) => day.label)
  const runtime = readRuntimeDiagnostics(diagnostics)

  return (
    <div className="settingsPage">
      {error ? <div className="errorBox">{error}</div> : null}
      {readOnlySettings ? (
        <div className="productionReadinessBanner blocked">
          <div>
            <span>配置安全模式</span>
            <b>只读安全视图</b>
            <em>运行时服务未连接，已禁用保存、定时器修改和生产任务触发。</em>
          </div>
        </div>
      ) : null}
      <div className="formCard">
        <div className="formTitle">运行身份</div>
        <div className="schedulerSummaryBar">
          <div>
            <span>当前工作台</span>
            <b>{runtime.appName}</b>
          </div>
          <div>
            <span>生产身份</span>
            <b>{runtime.productionApp ? '正式生产包' : '非正式运行'}</b>
          </div>
          <div>
            <span>包名校验</span>
            <b>{runtime.expectedBundle ? '通过' : runtime.bundleName ? '异常' : '开发模式'}</b>
          </div>
          <div>
            <span>Bundle ID</span>
            <b>{runtime.expectedBundleIdentifier ? '通过' : runtime.bundleIdentifier ? '异常' : '未获取'}</b>
          </div>
          <div>
            <span>数据库</span>
            <b>{String(diagnostics.database_backend || '未连接')}</b>
          </div>
          <div>
            <span>旧状态库</span>
            <b>{diagnostics.legacy_user_sqlite_state ? '存在' : '已隔离'}</b>
          </div>
          <div>
            <span>旧策略版本</span>
            <b>{Number(diagnostics.retired_strategy_version_count || 0)} / {Number(diagnostics.retired_strategy_task_count || 0)} / {Number(diagnostics.retired_strategy_status_count || 0)} / {Number(diagnostics.retired_active_model_count || 0)} / {Number(diagnostics.retired_validation_result_count || 0)} / {Number(diagnostics.retired_observation_count || 0)} / {Number(diagnostics.retired_mysql_table_count || 0)} / {Number(diagnostics.retired_data_artifact_count || 0)}</b>
          </div>
          <div>
            <span>冠军版本对齐</span>
            <b>{diagnostics.profit_arena_active_matches_champion && diagnostics.profit_arena_active_matches_latest_prediction ? '通过' : '异常'}</b>
          </div>
          <div>
            <span>最新预测</span>
            <b>{String(diagnostics.profit_arena_latest_prediction_date || '无')} / {Number(diagnostics.profit_arena_latest_prediction_count || 0)}</b>
          </div>
          <div>
            <span>Worker</span>
            <b>{runtime.workerMode}</b>
          </div>
          <div>
            <span>进程</span>
            <b>{runtime.processPid ? `PID ${runtime.processPid}` : '未获取'}</b>
          </div>
          <div>
            <span>启动时间</span>
            <b>{runtime.processStartedAt ? runtime.processStartedAt.replace(/^\d{4}-/, '').replace('T', ' ').slice(0, 16) : '未获取'}</b>
          </div>
          <div>
            <span>实例新鲜度</span>
            <b>{runtime.binaryNewerThanProcess ? '需重启' : '当前实例'}</b>
          </div>
        </div>
        {runtime.binaryNewerThanProcess ? (
          <div className="productionReadinessBanner blocked">
            <div>
              <span>实例已落后</span>
              <b>磁盘上的正式包比当前进程更新</b>
              <em>请退出当前窗口后重新打开正式 app，避免继续使用旧实例。</em>
            </div>
          </div>
        ) : null}
        <div className="runtimeConfigGrid">
          <ReadOnlyRuntimeField label="App 包" value={runtime.bundlePath || runtime.bundleName || '开发模式 / 未打包'} />
          <ReadOnlyRuntimeField label="Bundle ID" value={runtime.bundleIdentifier || '未获取'} />
          <ReadOnlyRuntimeField label="数据库后端" value={String(diagnostics.database_backend || '未连接')} />
          <ReadOnlyRuntimeField label="MySQL DSN" value={String(diagnostics.mysql_dsn || '未获取')} />
          <ReadOnlyRuntimeField label="旧策略版本残留" value={`${Number(diagnostics.retired_strategy_version_count || 0)} 条`} />
          <ReadOnlyRuntimeField label="旧策略任务残留" value={`${Number(diagnostics.retired_strategy_task_count || 0)} 条`} />
          <ReadOnlyRuntimeField label="旧策略状态残留" value={`${Number(diagnostics.retired_strategy_status_count || 0)} 条`} />
          <ReadOnlyRuntimeField label="旧模型激活指针" value={`${Number(diagnostics.retired_active_model_count || 0)} 条`} />
          <ReadOnlyRuntimeField label="旧模型验证结果" value={`${Number(diagnostics.retired_validation_result_count || 0)} 条`} />
          <ReadOnlyRuntimeField label="旧观察池残留" value={`${Number(diagnostics.retired_observation_count || 0)} 条`} />
          <ReadOnlyRuntimeField label="旧 MySQL 表残留" value={`${Number(diagnostics.retired_mysql_table_count || 0)} 张`} />
          <ReadOnlyRuntimeField label="旧 data_store 产物" value={`${Number(diagnostics.retired_data_artifact_count || 0)} 个`} />
          <ReadOnlyRuntimeField label="通用策略 active" value={String(diagnostics.profit_arena_active_run_id || '未获取')} />
          <ReadOnlyRuntimeField label="通用策略 champion" value={String(diagnostics.profit_arena_champion_run_id || '未获取')} />
          <ReadOnlyRuntimeField label="最新预测 run" value={String(diagnostics.profit_arena_latest_prediction_run_id || '未获取')} />
          <ReadOnlyRuntimeField label="通用策略 runs" value={`${Number(diagnostics.profit_arena_run_count || 0)} 条`} />
          <ReadOnlyRuntimeField label="执行文件" value={runtime.executablePath || '未获取'} />
          <ReadOnlyRuntimeField label="执行文件修改时间" value={runtime.executableModifiedAt ? runtime.executableModifiedAt.replace(/^\d{4}-/, '').replace('T', ' ').slice(0, 16) : '未获取'} />
          <ReadOnlyRuntimeField label="工作目录" value={runtime.workingDir || '未获取'} />
          <ReadOnlyRuntimeField label="数据目录来源" value={String(diagnostics.data_path_source || '未获取')} />
          <ReadOnlyRuntimeField label="数据目录" value={String(diagnostics.data_path || settings.data_path || '未获取')} />
        </div>
      </div>

      <div className="formCard">
        <div className="formTitle">运行偏好</div>
        <div className="runtimeConfigGrid">
          <Field label="默认初始资金" issue={findIssue(issues, 'default_initial_cash')} className="runtimeField runtimeFieldCompact">
            <input type="number" value={settings.default_initial_cash} disabled={readOnlySettings} onChange={(event) => update('default_initial_cash', Number(event.target.value))} />
          </Field>
          <Field label="默认调仓频率" issue={findIssue(issues, 'default_rebalance_freq')} className="runtimeField runtimeFieldCompact">
            <input type="number" value={settings.default_rebalance_freq} disabled={readOnlySettings} onChange={(event) => update('default_rebalance_freq', Number(event.target.value))} />
          </Field>
          <Field label="任务并发数" issue={findIssue(issues, 'task_concurrency')} className="runtimeField runtimeFieldCompact">
            <input type="number" min={1} max={8} value={settings.task_concurrency || 2} disabled={readOnlySettings} onChange={(event) => update('task_concurrency', Number(event.target.value))} />
          </Field>
        </div>
        <div className="settingsActions configCardActions">
          <button className="primaryButton settingsButton" onClick={onSave} disabled={readOnlySettings} title={readOnlyTitle}>保存配置</button>
        </div>
      </div>

      <div className="formCard schedulerCard">
        <div className="schedulerCardHeader">
          <div>
            <div className="formTitle">通用策略定时器</div>
            <p className="recommendationMeta">收盘后自动刷新通用策略买入清单，并把一键调仓计划推送到企业微信。</p>
          </div>
          <label className="schedulerToggle">
            <input
              type="checkbox"
              checked={Boolean(schedule.enabled)}
              disabled={readOnlySettings}
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
            <span>生产模块</span>
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
                  disabled={readOnlySettings}
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
                        disabled={readOnlySettings}
                        onChange={(event) => updateScheduleWeekday(day.value, event.target.checked)}
                      />
                      <span>{day.label}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>

            <div className="schedulerPanelTitle">生产模块</div>
            <p className="schedulerTinyHelp">当前桌面生产链路固定为：数据更新 {'->'} 因子快照 {'->'} 通用策略买入清单 {'->'} 调仓计划 {'->'} 企业微信通知。</p>
            <div className="chipGrid strategyChipGrid">
              {scheduleTargets.map((target) => (
                <label className="schedulerChip strategyChip" key={target.key}>
                  <input
                    type="checkbox"
                    checked
                    disabled
                    readOnly
                  />
                  <span>{target.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="settingsActions">
          <button className="primaryButton settingsButton" onClick={onSave} disabled={readOnlySettings} title={readOnlyTitle}>保存定时器</button>
        </div>
        {saved && <div className="saveHint">配置已保存，Python 任务会直接读取配置表。</div>}
      </div>
    </div>
  )
}

const scheduleTargets = [
  { key: 'arena', label: '通用策略' }
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

function ReadOnlyRuntimeField({ label, value }: { label: string; value: string }) {
  return (
    <Field label={label} className="runtimeField">
      <input value={value} readOnly />
    </Field>
  )
}

function readRuntimeDiagnostics(diagnostics: Record<string, unknown>) {
  const runtime = isRecord(diagnostics.runtime) ? diagnostics.runtime : {}
  const processStartedAt = stringValue(runtime.process_started_at)
  const executableModifiedAt = stringValue(runtime.real_executable_modified_at) || stringValue(runtime.executable_modified_at)
  return {
    appName: stringValue(runtime.app_name) || 'Quant Stock 生产工作台',
    productionApp: Boolean(runtime.production_app),
    expectedBundle: Boolean(runtime.expected_bundle),
    expectedBundleIdentifier: Boolean(runtime.expected_bundle_identifier),
    bundleName: stringValue(runtime.bundle_name),
    bundlePath: stringValue(runtime.bundle_path),
    bundleIdentifier: stringValue(runtime.bundle_identifier),
    executablePath: stringValue(runtime.real_executable_path) || stringValue(runtime.executable_path),
    executableModifiedAt,
    workingDir: stringValue(runtime.working_dir),
    workerMode: stringValue(runtime.worker_mode) || 'unknown',
    processPid: numberValue(runtime.process_pid),
    processStartedAt,
    binaryNewerThanProcess: isAfter(executableModifiedAt, processStartedAt)
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function stringValue(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function numberValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function isAfter(left: string, right: string) {
  const leftTime = Date.parse(left)
  const rightTime = Date.parse(right)
  return Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime > rightTime + 1000
}

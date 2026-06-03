import type { ReactNode } from 'react'
import type { ValidationIssue } from '../services/app'

export function Field(props: { label: string; issue?: ValidationIssue; children: ReactNode }) {
  const { label, issue, children } = props

  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {issue && <em>{issue.message}</em>}
    </label>
  )
}

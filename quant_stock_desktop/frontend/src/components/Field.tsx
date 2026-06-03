import type { ReactNode } from 'react'
import type { ValidationIssue } from '../services/app'

export function Field(props: { label: string; issue?: ValidationIssue; className?: string; children: ReactNode }) {
  const { label, issue, className = '', children } = props

  return (
    <label className={className ? `field ${className}` : 'field'} data-invalid={issue ? 'true' : undefined}>
      <span>{label}</span>
      {children}
      <em>{issue?.message || '\u00a0'}</em>
    </label>
  )
}

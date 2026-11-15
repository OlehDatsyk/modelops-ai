import clsx from 'clsx'
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import type { ReactNode } from 'react'
import { percentChange } from '../lib/format'

export function StatCard({
  label,
  value,
  current,
  previous,
  icon,
  sub,
  invert = false,
}: {
  label: string
  value: ReactNode
  current?: number
  previous?: number
  icon?: ReactNode
  sub?: ReactNode
  /** When true, an increase is bad (e.g. cost, errors, latency). */
  invert?: boolean
}) {
  const change = current !== undefined && previous !== undefined ? percentChange(current, previous) : null
  const up = (change ?? 0) > 0
  const good = change === null || change === 0 ? null : invert ? !up : up
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between text-xs text-muted">
        <span className="font-medium">{label}</span>
        {icon && <span className="text-faint">{icon}</span>}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight text-ink tabular-nums">{value}</div>
      <div className="mt-1.5 flex min-h-5 items-center gap-2 text-xs">
        {change !== null ? (
          <span
            className={clsx(
              'inline-flex items-center gap-0.5 font-medium',
              good === null ? 'text-muted' : good ? 'text-ok' : 'text-bad',
            )}
            title="Change versus the previous period of equal length"
          >
            {change === 0 ? <Minus className="size-3" /> : up ? <ArrowUpRight className="size-3.5" /> : <ArrowDownRight className="size-3.5" />}
            {Math.abs(change).toFixed(1)}%
          </span>
        ) : current !== undefined && previous === 0 && current > 0 ? (
          <span className="text-muted">new this period</span>
        ) : null}
        {sub && <span className="truncate text-muted">{sub}</span>}
      </div>
    </div>
  )
}

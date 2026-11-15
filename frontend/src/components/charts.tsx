import type { ReactNode } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from 'recharts'
import { CHART_COLORS, formatCompact } from '../lib/format'

const AXIS = { stroke: '#5d6a8f', fontSize: 11, tickLine: false, axisLine: false } as const
const GRID = { stroke: '#222d52', strokeDasharray: '3 3', vertical: false } as const

export interface SeriesDef {
  key: string
  label: string
  color: string
  stack?: string
}

function ChartTooltip({
  active,
  payload,
  label,
  valueFormatter,
}: TooltipProps<number, string> & { valueFormatter: (v: number) => string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-line-strong bg-surface/95 px-3 py-2 text-xs shadow-xl backdrop-blur">
      <div className="mb-1.5 font-medium text-ink">{label}</div>
      {payload.map((p) => (
        <div key={String(p.dataKey)} className="flex items-center gap-2 text-ink-2">
          <span className="size-2 rounded-full" style={{ background: p.color }} />
          <span className="text-muted">{p.name}</span>
          <span className="ml-auto pl-4 font-medium text-ink tabular-nums">{valueFormatter(Number(p.value ?? 0))}</span>
        </div>
      ))}
    </div>
  )
}

interface TimeChartProps {
  data: Record<string, unknown>[]
  xKey: string
  series: SeriesDef[]
  valueFormatter?: (v: number) => string
  height?: number
  kind?: 'area' | 'bar' | 'line'
}

export function TimeChart({
  data,
  xKey,
  series,
  valueFormatter = formatCompact,
  height = 240,
  kind = 'area',
}: TimeChartProps) {
  const common = {
    data,
    margin: { top: 8, right: 8, bottom: 0, left: -8 },
  }
  const axes = (
    <>
      <CartesianGrid {...GRID} />
      <XAxis dataKey={xKey} {...AXIS} minTickGap={24} />
      <YAxis {...AXIS} width={56} tickFormatter={(v: number) => valueFormatter(v)} />
      <Tooltip
        cursor={{ fill: 'rgb(79 140 255 / 0.06)', stroke: '#2e3b68' }}
        content={<ChartTooltip valueFormatter={valueFormatter} />}
      />
      {series.length > 1 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: '#b8c1dc' }} />}
    </>
  )
  return (
    <ResponsiveContainer width="100%" height={height}>
      {kind === 'bar' ? (
        <BarChart {...common}>
          {axes}
          {series.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} stackId={s.stack} radius={[3, 3, 0, 0]} maxBarSize={28} />
          ))}
        </BarChart>
      ) : kind === 'line' ? (
        <LineChart {...common}>
          {axes}
          {series.map((s) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} dot={false} />
          ))}
        </LineChart>
      ) : (
        <AreaChart {...common}>
          <defs>
            {series.map((s) => (
              <linearGradient key={s.key} id={`grad-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={s.color} stopOpacity={0.35} />
                <stop offset="100%" stopColor={s.color} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          {axes}
          {series.map((s) => (
            <Area
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={2}
              fill={`url(#grad-${s.key})`}
              stackId={s.stack}
            />
          ))}
        </AreaChart>
      )}
    </ResponsiveContainer>
  )
}

export function DonutChart({
  data,
  valueFormatter = formatCompact,
  height = 220,
  center,
}: {
  data: { name: string; value: number; color?: string }[]
  valueFormatter?: (v: number) => string
  height?: number
  center?: ReactNode
}) {
  return (
    <div className="relative" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="88%" paddingAngle={2} stroke="none">
            {data.map((d, i) => (
              <Cell key={d.name} fill={d.color ?? CHART_COLORS[i % CHART_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip content={<ChartTooltip valueFormatter={valueFormatter} />} />
        </PieChart>
      </ResponsiveContainer>
      {center && <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">{center}</div>}
    </div>
  )
}

/** Simple horizontal bar list (no chart library needed), used for ranked breakdowns. */
export function BarList({
  rows,
  valueFormatter,
}: {
  rows: { label: ReactNode; value: number; sub?: ReactNode; color?: string }[]
  valueFormatter: (v: number) => string
}) {
  const max = Math.max(...rows.map((r) => r.value), 0) || 1
  return (
    <ul className="space-y-3">
      {rows.map((r, i) => (
        <li key={i}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate text-ink-2">{r.label}</span>
            <span className="shrink-0 font-medium text-ink tabular-nums">{valueFormatter(r.value)}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
            <div
              className="h-full rounded-full"
              style={{ width: `${(r.value / max) * 100}%`, background: r.color ?? CHART_COLORS[i % CHART_COLORS.length] }}
            />
          </div>
          {r.sub && <div className="mt-1 text-xs text-muted">{r.sub}</div>}
        </li>
      ))}
    </ul>
  )
}

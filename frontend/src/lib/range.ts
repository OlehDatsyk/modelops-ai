export type RangeKey = '24h' | '7d' | '30d' | '90d' | 'custom'

export interface RangeValue {
  range: RangeKey
  start?: string // YYYY-MM-DD (custom only, inclusive)
  end?: string // YYYY-MM-DD (custom only, inclusive)
}

export const RANGE_OPTIONS: { key: RangeKey; label: string }[] = [
  { key: '24h', label: '24h' },
  { key: '7d', label: '7d' },
  { key: '30d', label: '30d' },
  { key: '90d', label: '90d' },
  { key: 'custom', label: 'Custom' },
]

/** Convert a range selection to API query params. Custom dates are interpreted in the user's local time. */
export function rangeToQuery(value: RangeValue): Record<string, string | undefined> {
  if (value.range !== 'custom') return { range: value.range }
  if (!value.start || !value.end) return { range: '30d' }
  const start = new Date(`${value.start}T00:00:00`)
  const end = new Date(`${value.end}T00:00:00`)
  end.setDate(end.getDate() + 1) // inclusive end date
  return { range: 'custom', start: start.toISOString(), end: end.toISOString() }
}

export function isValidCustomRange(start?: string, end?: string): boolean {
  if (!start || !end) return false
  const s = new Date(start).getTime()
  const e = new Date(end).getTime()
  return Number.isFinite(s) && Number.isFinite(e) && e >= s && e - s <= 365 * 86_400_000
}

export function todayIso(offsetDays = 0): string {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

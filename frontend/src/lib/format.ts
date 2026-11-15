import type { Provider } from './types'

export function formatUsd(value: number | string | null | undefined, opts: { precise?: boolean } = {}): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = typeof value === 'string' ? Number(value) : value
  if (!Number.isFinite(n)) return '—'
  if (n === 0) return '$0.00'
  const abs = Math.abs(n)
  let digits = 2
  if (opts.precise || abs < 0.01) digits = abs < 0.0001 ? 6 : 4
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n)
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat('en-US').format(value)
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value >= 10_000) return `${(value / 1000).toFixed(1)} s`
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`
  return `${Math.round(value)} ms`
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(digits)}%`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return 'never'
  const seconds = Math.round((now.getTime() - new Date(iso).getTime()) / 1000)
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days} d ago`
  return formatDate(iso)
}

/** Label for a chart bucket given the bucket granularity. */
export function formatBucket(iso: string, granularity: 'hour' | 'day'): string {
  const d = new Date(iso)
  return granularity === 'hour'
    ? d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/** Percentage change from previous to current; null when there is no baseline. */
export function percentChange(current: number, previous: number): number | null {
  if (!previous) return null
  return ((current - previous) / previous) * 100
}

export const PROVIDER_LABEL: Record<Provider, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  gemini: 'Gemini',
}

export const PROVIDER_COLOR: Record<Provider, string> = {
  openai: '#2fbf71',
  anthropic: '#e8885a',
  gemini: '#4f8cff',
}

export const CHART_COLORS = ['#4f8cff', '#8b5cf6', '#2dd4bf', '#f2a93b', '#f0566a', '#38bdf8', '#c084fc', '#a3e635']

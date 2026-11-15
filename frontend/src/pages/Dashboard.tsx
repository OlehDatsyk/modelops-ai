import { useQuery } from '@tanstack/react-query'
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, Coins, Gauge, LogIn, LogOut, Rocket } from 'lucide-react'
import { Link } from 'react-router-dom'
import { BarList, DonutChart, TimeChart } from '../components/charts'
import { ProjectSelect, ProviderSelect, RangePicker } from '../components/filters'
import { StatCard } from '../components/StatCard'
import { Alert, Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton } from '../components/ui'
import { api } from '../lib/api'
import {
  PROVIDER_COLOR,
  PROVIDER_LABEL,
  formatBucket,
  formatCompact,
  formatMs,
  formatNumber,
  formatPercent,
  formatUsd,
} from '../lib/format'
import { rangeToQuery } from '../lib/range'
import type { Overview } from '../lib/types'
import { useFilters } from '../lib/useFilters'

function DashboardSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-[104px]" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
      </div>
    </div>
  )
}

export default function Dashboard() {
  const f = useFilters('7d')
  const query = useQuery({
    queryKey: ['overview', f.range, f.projectId, f.provider],
    queryFn: () =>
      api<Overview>('/analytics/overview', {
        query: { ...rangeToQuery(f.range), project_id: f.projectId, provider: f.provider },
      }),
  })
  const data = query.data
  const cur = data?.summary.current
  const prev = data?.summary.previous
  const g = data?.range.granularity ?? 'day'
  const series = (data?.timeseries ?? []).map((p) => ({ ...p, label: formatBucket(p.bucket, g) }))
  const hasAnyData = !!cur && (cur.total_requests > 0 || prev!.total_requests > 0)

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Requests, tokens, latency, failures and estimated spend across all connected providers."
        actions={
          <>
            <ProjectSelect value={f.projectId} onChange={f.setProjectId} />
            <ProviderSelect value={f.provider} onChange={f.setProvider} />
            <RangePicker value={f.range} onChange={f.setRange} />
          </>
        }
      />

      {query.isLoading ? (
        <DashboardSkeleton />
      ) : query.isError ? (
        <Card>
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        </Card>
      ) : !hasAnyData && !f.projectId && !f.provider ? (
        <Card>
          <EmptyState
            icon={<Rocket className="size-5" />}
            title="No requests recorded in this period"
            description="Analytics are computed from requests that pass through your ModelOps gateway. Connect a provider, create a project key and send your first request."
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <Link to="/providers" className="inline-flex h-9 items-center rounded-lg border border-line-strong bg-surface-2 px-4 text-sm hover:bg-surface-3">
                  1. Add a provider key
                </Link>
                <Link to="/projects" className="inline-flex h-9 items-center rounded-lg border border-line-strong bg-surface-2 px-4 text-sm hover:bg-surface-3">
                  2. Create a project
                </Link>
                <Link to="/gateway" className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-accent px-4 text-sm font-medium text-white hover:brightness-110">
                  3. Send a request <ArrowRight className="size-4" />
                </Link>
              </div>
            }
          />
        </Card>
      ) : (
        cur &&
        prev && (
          <div className="space-y-4">
            {cur.unpriced_requests > 0 && (
              <Alert tone="warn">
                {formatNumber(cur.unpriced_requests)} request(s) used models without a pricing entry, so their cost is unknown
                and excluded from totals.{' '}
                <Link to="/costs?tab=pricing" className="underline">
                  Add pricing
                </Link>
              </Alert>
            )}
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard label="Total requests" value={formatNumber(cur.total_requests)} current={cur.total_requests} previous={prev.total_requests} icon={<Activity className="size-4" />} />
              <StatCard label="Estimated spend" value={formatUsd(cur.estimated_cost_usd)} current={cur.estimated_cost_usd} previous={prev.estimated_cost_usd} invert icon={<Coins className="size-4" />} />
              <StatCard label="Input tokens" value={formatCompact(cur.input_tokens)} current={cur.input_tokens} previous={prev.input_tokens} invert icon={<LogIn className="size-4" />} />
              <StatCard label="Output tokens" value={formatCompact(cur.output_tokens)} current={cur.output_tokens} previous={prev.output_tokens} invert icon={<LogOut className="size-4" />} />
              <StatCard label="Avg response time" value={formatMs(cur.avg_latency_ms)} current={cur.avg_latency_ms ?? undefined} previous={prev.avg_latency_ms ?? undefined} invert icon={<Gauge className="size-4" />} />
              <StatCard label="Successful" value={formatNumber(cur.successful_requests)} current={cur.successful_requests} previous={prev.successful_requests} icon={<CheckCircle2 className="size-4" />} />
              <StatCard label="Failed" value={formatNumber(cur.failed_requests)} current={cur.failed_requests} previous={prev.failed_requests} invert icon={<AlertTriangle className="size-4" />} />
              <StatCard label="Error rate" value={formatPercent(cur.error_rate)} current={cur.error_rate} previous={prev.error_rate} invert icon={<AlertTriangle className="size-4" />} />
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
              <Card>
                <CardHeader title="Estimated spend" subtitle={`USD per ${g}`} />
                <div className="p-4">
                  <TimeChart data={series} xKey="label" series={[{ key: 'cost_usd', label: 'Spend', color: '#8b5cf6' }]} valueFormatter={(v) => formatUsd(v)} />
                </div>
              </Card>
              <Card>
                <CardHeader title="Request volume" subtitle="Successful and failed requests" />
                <div className="p-4">
                  <TimeChart
                    kind="bar"
                    data={series.map((p) => ({ ...p, ok: p.requests - p.errors }))}
                    xKey="label"
                    series={[
                      { key: 'ok', label: 'Successful', color: '#4f8cff', stack: 'r' },
                      { key: 'errors', label: 'Failed', color: '#f0566a', stack: 'r' },
                    ]}
                    valueFormatter={formatNumber}
                  />
                </div>
              </Card>
              <Card>
                <CardHeader title="Token consumption" subtitle="Input and output tokens" />
                <div className="p-4">
                  <TimeChart
                    data={series}
                    xKey="label"
                    series={[
                      { key: 'input_tokens', label: 'Input', color: '#2dd4bf', stack: 't' },
                      { key: 'output_tokens', label: 'Output', color: '#4f8cff', stack: 't' },
                    ]}
                  />
                </div>
              </Card>
              <Card>
                <CardHeader title="Error rate" subtitle="Failed requests as a percentage of all requests" />
                <div className="p-4">
                  <TimeChart kind="line" data={series} xKey="label" series={[{ key: 'error_rate', label: 'Error rate', color: '#f0566a' }]} valueFormatter={(v) => `${v.toFixed(1)}%`} />
                </div>
              </Card>
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
              <Card>
                <CardHeader title="Provider distribution" subtitle="Share of requests" />
                <div className="p-4">
                  {data.by_provider.length ? (
                    <>
                      <DonutChart
                        data={data.by_provider.map((r) => ({ name: PROVIDER_LABEL[r.provider!], value: r.requests, color: PROVIDER_COLOR[r.provider!] }))}
                        valueFormatter={formatNumber}
                        center={
                          <div>
                            <div className="text-xl font-semibold">{formatCompact(cur.total_requests)}</div>
                            <div className="text-xs text-muted">requests</div>
                          </div>
                        }
                      />
                      <ul className="mt-3 space-y-1.5 text-sm">
                        {data.by_provider.map((r) => (
                          <li key={r.provider} className="flex items-center gap-2">
                            <span className="size-2.5 rounded-full" style={{ background: PROVIDER_COLOR[r.provider!] }} />
                            <span className="text-ink-2">{PROVIDER_LABEL[r.provider!]}</span>
                            <span className="ml-auto text-muted tabular-nums">{formatPercent(r.request_share)}</span>
                            <span className="w-20 text-right text-ink tabular-nums">{formatUsd(r.estimated_cost_usd)}</span>
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <p className="py-10 text-center text-sm text-muted">No requests in this period.</p>
                  )}
                </div>
              </Card>
              <Card className="lg:col-span-2">
                <CardHeader title="Model usage" subtitle="Top models by estimated spend" action={<Link to="/costs" className="text-xs text-accent hover:underline">Cost details →</Link>} />
                <div className="overflow-x-auto">
                  {data.by_model.length ? (
                    <table className="w-full min-w-[560px]">
                      <thead className="border-b border-line/70">
                        <tr>
                          <th className="th">Model</th>
                          <th className="th text-right">Requests</th>
                          <th className="th text-right">Tokens</th>
                          <th className="th text-right">Errors</th>
                          <th className="th text-right">Avg latency</th>
                          <th className="th text-right">Est. spend</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.by_model.map((m) => (
                          <tr key={`${m.provider}/${m.model}`} className="border-b border-line/40 last:border-0">
                            <td className="td">
                              <div className="flex items-center gap-2">
                                <span className="size-2 rounded-full" style={{ background: PROVIDER_COLOR[m.provider!] }} />
                                <span className="mono whitespace-nowrap text-ink">{m.model}</span>
                              </div>
                            </td>
                            <td className="td text-right tabular-nums">{formatNumber(m.requests)}</td>
                            <td className="td text-right tabular-nums">{formatCompact(m.total_tokens)}</td>
                            <td className="td text-right tabular-nums">{formatPercent(m.error_rate)}</td>
                            <td className="td text-right tabular-nums">{formatMs(m.avg_latency_ms)}</td>
                            <td className="td text-right text-ink tabular-nums">
                              {m.unpriced_requests && !m.estimated_cost_usd ? <span className="text-muted">unknown</span> : formatUsd(m.estimated_cost_usd)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="py-10 text-center text-sm text-muted">No model usage in this period.</p>
                  )}
                </div>
              </Card>
            </div>

            {data.by_project.length > 0 && (
              <Card>
                <CardHeader title="Projects" subtitle="Estimated spend by project" />
                <div className="p-5">
                  <BarList
                    rows={data.by_project.map((p) => ({
                      label: p.project_id ? <Link to={`/projects/${p.project_id}`} className="hover:text-accent">{p.project_name}</Link> : p.project_name,
                      value: p.estimated_cost_usd,
                      sub: `${formatNumber(p.requests)} requests · ${formatCompact(p.total_tokens)} tokens · ${formatPercent(p.error_rate)} errors`,
                    }))}
                    valueFormatter={(v) => formatUsd(v)}
                  />
                </div>
              </Card>
            )}
          </div>
        )
      )}
    </>
  )
}

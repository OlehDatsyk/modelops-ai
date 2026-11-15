import { keepPreviousData, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ListTree, Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { ProjectSelect, ProviderSelect, RangePicker } from '../components/filters'
import { Badge, Button, Card, CopyButton, EmptyState, ErrorState, LoadingBlock, PageHeader } from '../components/ui'
import { api } from '../lib/api'
import { PROVIDER_COLOR, PROVIDER_LABEL, formatDateTime, formatMs, formatNumber, formatUsd } from '../lib/format'
import { rangeToQuery } from '../lib/range'
import type { Page, RequestDetail, RequestRow } from '../lib/types'
import { useFilters } from '../lib/useFilters'

type SortKey = 'created_at' | 'latency_ms' | 'cost' | 'total_tokens'

function StatusBadge({ row }: { row: Pick<RequestRow, 'status' | 'http_status'> }) {
  return row.status === 'success' ? <Badge tone="ok">{row.http_status}</Badge> : <Badge tone="bad">{row.http_status}</Badge>
}

function DetailDrawer({ requestRef, onClose }: { requestRef: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['request', requestRef], queryFn: () => api<RequestDetail>(`/requests/${requestRef}`) })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  const r = q.data
  const rows: [string, React.ReactNode][] = r
    ? [
        ['Request ID', <span className="mono">{r.request_id}</span>],
        ['Time', formatDateTime(r.created_at)],
        ['Provider', PROVIDER_LABEL[r.provider]],
        ['Model', <span className="mono">{r.model || '—'}</span>],
        ['Endpoint', <span className="mono">{r.endpoint}</span>],
        ['Project', r.project_id ? <Link className="text-accent hover:underline" to={`/projects/${r.project_id}`}>{r.project_name}</Link> : '—'],
        ['Streaming', r.streamed ? 'Yes' : 'No'],
        ['HTTP status', <StatusBadge row={r} />],
        ['Response time', formatMs(r.latency_ms)],
        ['Input tokens', formatNumber(r.input_tokens)],
        ['Output tokens', formatNumber(r.output_tokens)],
        ['Total tokens', formatNumber(r.total_tokens)],
      ]
    : []
  return createPortal(
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 animate-fade-in bg-black/50" onClick={onClose} />
      <aside className="absolute inset-y-0 right-0 flex w-full max-w-md animate-slide-in flex-col border-l border-line bg-surface" role="dialog" aria-label="Request details">
        <div className="flex items-center justify-between border-b border-line/70 px-5 py-4">
          <h2 className="text-base font-semibold">Request details</h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-ink" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {q.isLoading ? (
            <LoadingBlock />
          ) : q.isError ? (
            <ErrorState error={q.error} onRetry={() => q.refetch()} />
          ) : r ? (
            <div className="space-y-5">
              <div className="flex justify-end">
                <CopyButton value={r.request_id} label="Copy request ID" />
              </div>
              <dl className="divide-y divide-line/50 rounded-lg border border-line">
                {rows.map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between gap-4 px-3.5 py-2.5 text-sm">
                    <dt className="text-muted">{k}</dt>
                    <dd className="text-right text-ink">{v}</dd>
                  </div>
                ))}
              </dl>
              <section>
                <h3 className="mb-2 text-xs font-semibold tracking-wider text-muted uppercase">Cost estimate</h3>
                {r.cost_status === 'estimated' ? (
                  <div className="rounded-lg border border-line p-3.5 text-sm">
                    <div className="flex justify-between"><span className="text-muted">Input</span><span>{formatUsd(r.cost_input_usd, { precise: true })}</span></div>
                    <div className="mt-1 flex justify-between"><span className="text-muted">Output</span><span>{formatUsd(r.cost_output_usd, { precise: true })}</span></div>
                    <div className="mt-2 flex justify-between border-t border-line/60 pt-2 font-medium"><span>Total</span><span>{formatUsd(r.cost_total_usd, { precise: true })}</span></div>
                    <p className="mt-3 text-xs text-muted">
                      Priced with <span className="mono text-ink-2">{r.pricing_model_key}</span> at ${Number(r.input_price_per_mtok)}/1M input and $
                      {Number(r.output_price_per_mtok)}/1M output tokens (snapshot at request time,{' '}
                      {r.pricing_verified ? 'verified price' : 'unverified reference price'}).
                    </p>
                  </div>
                ) : (
                  <p className="rounded-lg border border-line p-3.5 text-sm text-muted">
                    {r.total_tokens ? 'No pricing entry matched this model, so the cost is unknown.' : 'No tokens were consumed.'}{' '}
                    {r.total_tokens > 0 && <Link to="/costs?tab=pricing" className="text-accent hover:underline">Add pricing</Link>}
                  </p>
                )}
              </section>
              {r.status === 'error' && (
                <section>
                  <h3 className="mb-2 text-xs font-semibold tracking-wider text-muted uppercase">Error</h3>
                  <div className="rounded-lg border border-bad/30 bg-bad/5 p-3.5 text-sm">
                    <Badge tone="bad">{r.error_type}</Badge>
                    <p className="mt-2 break-words text-ink-2">{r.error_message || 'No message returned.'}</p>
                  </div>
                </section>
              )}
              <p className="text-xs text-faint">Prompts and responses are not stored — only the metadata above.</p>
            </div>
          ) : null}
        </div>
      </aside>
    </div>,
    document.body,
  )
}

export default function Requests() {
  const f = useFilters('7d')
  const p = f.params
  const [search, setSearch] = useState(p.get('q') ?? '')
  const page = Number(p.get('page') ?? 1) || 1
  const sort = (p.get('sort') as SortKey) || 'created_at'
  const order = (p.get('order') as 'asc' | 'desc') || 'desc'
  const status = p.get('status') ?? ''
  const model = p.get('model') ?? ''
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => setSearch(p.get('q') ?? ''), [p])

  const models = useQuery({ queryKey: ['request-models'], queryFn: () => api<string[]>('/requests/models') })
  const timeQuery = rangeToQuery(f.range)
  const range = f.range.range === 'custom' ? timeQuery : (() => {
    const hours = { '24h': 24, '7d': 168, '30d': 720, '90d': 2160 }[f.range.range] ?? 168
    return { start: new Date(Date.now() - hours * 3600_000).toISOString() }
  })()
  const query = useQuery({
    queryKey: ['requests', p.toString()],
    placeholderData: keepPreviousData,
    queryFn: () =>
      api<Page<RequestRow>>('/requests', {
        query: {
          q: p.get('q') ?? undefined,
          provider: f.provider,
          status,
          project_id: f.projectId,
          model,
          start: range.start,
          end: 'end' in range ? range.end : undefined,
          sort,
          order,
          page,
          page_size: 25,
        },
      }),
  })

  const toggleSort = (key: SortKey) => {
    f.update({ sort: key, order: sort === key && order === 'desc' ? 'asc' : 'desc', page: undefined })
  }
  const SortHeader = ({ k, label, className }: { k: SortKey; label: string; className?: string }) => (
    <th className={clsx('th', className)}>
      <button onClick={() => toggleSort(k)} className="inline-flex items-center gap-1 uppercase hover:text-ink" aria-label={`Sort by ${label}`}>
        {label}
        {sort === k && (order === 'desc' ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />)}
      </button>
    </th>
  )

  const data = query.data
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1
  const filtersActive = !!(p.get('q') || f.provider || status || f.projectId || model)

  return (
    <>
      <PageHeader title="Request logs" description="Every gateway request with its status, tokens, latency and estimated cost. Click a row for details." actions={<RangePicker value={f.range} onChange={f.setRange} />} />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line/70 p-3">
          <form
            className="relative min-w-[200px] flex-1"
            onSubmit={(e) => {
              e.preventDefault()
              f.update({ q: search.trim() || undefined, page: undefined })
            }}
          >
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" />
            <input className="input pl-9" placeholder="Search request ID, model or error" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search" />
          </form>
          <ProviderSelect value={f.provider} onChange={f.setProvider} />
          <select className="input h-9 w-auto appearance-none pr-8" value={status} onChange={(e) => f.update({ status: e.target.value, page: undefined })} aria-label="Status">
            <option value="">All statuses</option>
            <option value="success">Successful</option>
            <option value="error">Failed</option>
          </select>
          <select className="input h-9 w-auto max-w-[12rem] appearance-none pr-8" value={model} onChange={(e) => f.update({ model: e.target.value, page: undefined })} aria-label="Model">
            <option value="">All models</option>
            {models.data?.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <ProjectSelect value={f.projectId} onChange={f.setProjectId} />
          {filtersActive && (
            <Button variant="ghost" size="sm" onClick={() => { setSearch(''); f.update({ q: undefined, provider: undefined, status: undefined, project_id: undefined, model: undefined, page: undefined }) }}>
              Clear filters
            </Button>
          )}
        </div>
        {query.isLoading ? (
          <LoadingBlock />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : !data?.items.length ? (
          <EmptyState
            icon={<ListTree className="size-5" />}
            title={filtersActive ? 'No requests match these filters' : 'No requests in this period'}
            description={filtersActive ? 'Try widening the date range or clearing filters.' : <>Requests appear here once traffic flows through the gateway. See the <Link to="/gateway" className="text-accent hover:underline">quickstart</Link>.</>}
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px]">
                <thead className="border-b border-line/70">
                  <tr>
                    <SortHeader k="created_at" label="Time" />
                    <th className="th">Request ID</th>
                    <th className="th">Provider / model</th>
                    <th className="th">Project</th>
                    <th className="th">Status</th>
                    <th className="th text-right">Input</th>
                    <th className="th text-right">Output</th>
                    <SortHeader k="cost" label="Est. cost" className="text-right" />
                    <SortHeader k="latency_ms" label="Latency" className="text-right" />
                  </tr>
                </thead>
                <tbody className={clsx(query.isFetching && 'opacity-70')}>
                  {data.items.map((r) => (
                    <tr
                      key={r.id}
                      onClick={() => setSelected(r.request_id)}
                      onKeyDown={(e) => e.key === 'Enter' && setSelected(r.request_id)}
                      tabIndex={0}
                      className="cursor-pointer border-b border-line/40 transition-colors last:border-0 hover:bg-surface-2/60 focus:bg-surface-2/60 focus:outline-none"
                    >
                      <td className="td whitespace-nowrap">{formatDateTime(r.created_at)}</td>
                      <td className="td mono text-muted">{r.request_id.slice(0, 16)}…</td>
                      <td className="td">
                        <div className="flex items-center gap-2">
                          <span className="size-2 shrink-0 rounded-full" style={{ background: PROVIDER_COLOR[r.provider] }} title={PROVIDER_LABEL[r.provider]} />
                          <span className="mono max-w-[220px] truncate text-ink">{r.model || '—'}</span>
                          {r.streamed && <Badge tone="info">stream</Badge>}
                        </div>
                      </td>
                      <td className="td max-w-[140px] truncate">{r.project_name ?? '—'}</td>
                      <td className="td">
                        <div className="flex items-center gap-1.5">
                          <StatusBadge row={r} />
                          {r.error_type && <span className="max-w-[140px] truncate text-xs text-bad">{r.error_type}</span>}
                        </div>
                      </td>
                      <td className="td text-right tabular-nums">{formatNumber(r.input_tokens)}</td>
                      <td className="td text-right tabular-nums">{formatNumber(r.output_tokens)}</td>
                      <td className="td text-right tabular-nums">{r.cost_status === 'unknown' && r.total_tokens ? <span className="text-muted">unknown</span> : formatUsd(r.cost_total_usd)}</td>
                      <td className="td text-right tabular-nums">{formatMs(r.latency_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line/70 px-4 py-3 text-sm text-muted">
              <span>
                {formatNumber((page - 1) * data.page_size + 1)}–{formatNumber(Math.min(page * data.page_size, data.total))} of {formatNumber(data.total)}
              </span>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => f.update({ page: String(page - 1) })} icon={<ChevronLeft className="size-4" />}>
                  Previous
                </Button>
                <span className="tabular-nums">Page {page} / {pages}</span>
                <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => f.update({ page: String(page + 1) })}>
                  Next <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
      {selected && <DetailDrawer requestRef={selected} onClose={() => setSelected(null)} />}
    </>
  )
}

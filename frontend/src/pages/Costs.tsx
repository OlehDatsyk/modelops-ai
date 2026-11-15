import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Calculator, Coins, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BarList, DonutChart, TimeChart } from '../components/charts'
import { ProjectSelect, RangePicker } from '../components/filters'
import { StatCard } from '../components/StatCard'
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingBlock,
  Modal,
  PageHeader,
  SelectField,
  Tabs,
  TextField,
  Toggle,
} from '../components/ui'
import { api, errorMessage } from '../lib/api'
import { PROVIDER_COLOR, PROVIDER_LABEL, formatBucket, formatCompact, formatDate, formatNumber, formatPercent, formatUsd } from '../lib/format'
import { rangeToQuery } from '../lib/range'
import { PROVIDERS, type CostPreview, type CostReport, type Pricing, type Provider } from '../lib/types'
import { useFilters } from '../lib/useFilters'

function SpendTab() {
  const f = useFilters('30d')
  const q = useQuery({
    queryKey: ['costs', f.range, f.projectId],
    queryFn: () => api<CostReport>('/analytics/costs', { query: { ...rangeToQuery(f.range), project_id: f.projectId } }),
  })
  const d = q.data
  return (
    <>
      <div className="mb-5 flex flex-wrap justify-end gap-2">
        <ProjectSelect value={f.projectId} onChange={f.setProjectId} />
        <RangePicker value={f.range} onChange={f.setRange} />
      </div>
      {q.isLoading ? (
        <LoadingBlock />
      ) : q.isError ? (
        <Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card>
      ) : d ? (
        <div className="space-y-4">
          <Alert tone="info">
            All amounts are <strong>estimates</strong> computed from token counts and the pricing table below. They are not provider invoices.
            {d.unpriced_requests > 0 && <> {formatNumber(d.unpriced_requests)} request(s) in this range had no matching price and are excluded.</>}
          </Alert>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard label="Spend in range" value={formatUsd(d.total_usd)} current={d.total_usd} previous={d.previous_total_usd} invert icon={<Coins className="size-4" />} />
            <StatCard label="Previous period" value={formatUsd(d.previous_total_usd)} />
            <StatCard label="Today (UTC)" value={formatUsd(d.summaries.today_usd)} />
            <StatCard label="Month to date (UTC)" value={formatUsd(d.summaries.month_to_date_usd)} />
          </div>
          {d.total_usd === 0 && d.by_model.length === 0 ? (
            <Card><EmptyState icon={<Coins className="size-5" />} title="No spend recorded in this range" description="Costs appear once priced requests flow through the gateway." /></Card>
          ) : (
            <>
              <div className="grid gap-4 lg:grid-cols-3">
                <Card className="lg:col-span-2">
                  <CardHeader title="Spending trend" subtitle={`Estimated USD per ${d.range.granularity}`} />
                  <div className="p-4">
                    <TimeChart data={d.trend.map((p) => ({ ...p, label: formatBucket(p.bucket, d.range.granularity) }))} xKey="label" series={[{ key: 'cost_usd', label: 'Spend', color: '#8b5cf6' }]} valueFormatter={(v) => formatUsd(v)} />
                  </div>
                </Card>
                <Card>
                  <CardHeader title="By provider" />
                  <div className="p-4">
                    <DonutChart
                      data={d.by_provider.map((r) => ({ name: PROVIDER_LABEL[r.provider!], value: r.estimated_cost_usd, color: PROVIDER_COLOR[r.provider!] }))}
                      valueFormatter={(v) => formatUsd(v)}
                      center={<div><div className="text-lg font-semibold">{formatUsd(d.total_usd)}</div><div className="text-xs text-muted">total</div></div>}
                    />
                    <ul className="mt-3 space-y-1.5 text-sm">
                      {d.by_provider.map((r) => (
                        <li key={r.provider} className="flex items-center gap-2">
                          <span className="size-2.5 rounded-full" style={{ background: PROVIDER_COLOR[r.provider!] }} />
                          {PROVIDER_LABEL[r.provider!]}
                          <span className="ml-auto text-muted">{formatPercent(r.cost_share)}</span>
                          <span className="w-20 text-right tabular-nums">{formatUsd(r.estimated_cost_usd)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </Card>
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                <Card>
                  <CardHeader title="By model" />
                  <div className="p-5">
                    <BarList rows={d.by_model.slice(0, 10).map((m) => ({ label: <span className="mono">{m.model}</span>, value: m.estimated_cost_usd, color: PROVIDER_COLOR[m.provider!], sub: `${formatNumber(m.requests)} req · ${formatCompact(m.input_tokens)} in / ${formatCompact(m.output_tokens)} out${m.unpriced_requests ? ` · ${m.unpriced_requests} unpriced` : ''}` }))} valueFormatter={(v) => formatUsd(v)} />
                  </div>
                </Card>
                <Card>
                  <CardHeader title="By project" />
                  <div className="p-5">
                    <BarList rows={d.by_project.map((p) => ({ label: p.project_name, value: p.estimated_cost_usd, sub: `${formatNumber(p.requests)} requests · ${formatCompact(p.total_tokens)} tokens` }))} valueFormatter={(v) => formatUsd(v)} />
                  </div>
                </Card>
              </div>
            </>
          )}
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Daily summary" subtitle="Last 30 days (UTC)" />
              <div className="p-4">
                <TimeChart kind="bar" data={d.summaries.daily.map((x) => ({ ...x, label: formatDate(`${x.day}T12:00:00`) }))} xKey="label" series={[{ key: 'cost_usd', label: 'Spend', color: '#4f8cff' }]} valueFormatter={(v) => formatUsd(v)} height={200} />
              </div>
            </Card>
            <Card>
              <CardHeader title="Monthly summary" subtitle="Last 12 months" />
              {d.summaries.monthly.length ? (
                <table className="w-full">
                  <thead className="border-b border-line/70"><tr><th className="th">Month</th><th className="th text-right">Requests</th><th className="th text-right">Spend</th></tr></thead>
                  <tbody>
                    {[...d.summaries.monthly].reverse().map((m) => (
                      <tr key={m.month} className="border-b border-line/40 last:border-0">
                        <td className="td">{m.month}</td>
                        <td className="td text-right tabular-nums">{formatNumber(m.requests)}</td>
                        <td className="td text-right text-ink tabular-nums">{formatUsd(m.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="py-10 text-center text-sm text-muted">No usage yet.</p>
              )}
            </Card>
          </div>
        </div>
      ) : null}
    </>
  )
}

interface PricingDraft {
  provider: Provider
  model: string
  input_price_per_mtok: string
  output_price_per_mtok: string
  verified: boolean
  notes: string
}

function PricingModal({ initial, onClose }: { initial?: Pricing; onClose: () => void }) {
  const qc = useQueryClient()
  const [d, setD] = useState<PricingDraft>(
    initial
      ? { provider: initial.provider, model: initial.model, input_price_per_mtok: String(Number(initial.input_price_per_mtok)), output_price_per_mtok: String(Number(initial.output_price_per_mtok)), verified: initial.verified, notes: initial.notes }
      : { provider: 'openai', model: '', input_price_per_mtok: '', output_price_per_mtok: '', verified: false, notes: '' },
  )
  const editingCustom = initial?.scope === 'custom'
  const save = useMutation({
    mutationFn: () =>
      editingCustom
        ? api(`/pricing/${initial!.id}`, { method: 'PATCH', body: { input_price_per_mtok: d.input_price_per_mtok, output_price_per_mtok: d.output_price_per_mtok, verified: d.verified, notes: d.notes } })
        : api('/pricing', { method: 'POST', body: d }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pricing'] })
      onClose()
    },
  })
  const valid = d.model.trim() && d.input_price_per_mtok !== '' && d.output_price_per_mtok !== '' && Number(d.input_price_per_mtok) >= 0 && Number(d.output_price_per_mtok) >= 0
  return (
    <Modal
      open
      onClose={onClose}
      title={editingCustom ? 'Edit custom price' : initial ? 'Override reference price' : 'Add model price'}
      description="Prices are USD per 1 million tokens. Custom prices apply only to your account and take precedence over the reference catalogue."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" form="pricing-form" loading={save.isPending} disabled={!valid}>Save</Button></>}
    >
      <form id="pricing-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate() }}>
        <SelectField label="Provider" value={d.provider} disabled={!!initial} onChange={(e) => setD({ ...d, provider: e.target.value as Provider })}>
          {PROVIDERS.map((p) => <option key={p} value={p}>{PROVIDER_LABEL[p]}</option>)}
        </SelectField>
        <TextField label="Model" value={d.model} disabled={!!initial} onChange={(e) => setD({ ...d, model: e.target.value })} placeholder="e.g. gpt-4o" hint="Also matches dated variants, e.g. gpt-4o-2024-08-06." />
        <TextField label="Input $ / 1M tokens" type="number" min={0} step="0.000001" value={d.input_price_per_mtok} onChange={(e) => setD({ ...d, input_price_per_mtok: e.target.value })} />
        <TextField label="Output $ / 1M tokens" type="number" min={0} step="0.000001" value={d.output_price_per_mtok} onChange={(e) => setD({ ...d, output_price_per_mtok: e.target.value })} />
        <TextField className="sm:col-span-2" label="Notes" maxLength={300} value={d.notes} onChange={(e) => setD({ ...d, notes: e.target.value })} placeholder="Source of this price, contract terms…" />
        <div className="sm:col-span-2">
          <Toggle checked={d.verified} onChange={(v) => setD({ ...d, verified: v })} label="I have verified this price" description="Mark only when confirmed against the provider's pricing page or your contract." />
        </div>
        {save.isError && <Alert tone="bad" className="sm:col-span-2">{errorMessage(save.error)}</Alert>}
      </form>
    </Modal>
  )
}

function CostCalculator() {
  const [provider, setProvider] = useState<Provider>('openai')
  const [model, setModel] = useState('gpt-4o-mini')
  const [inp, setInp] = useState('1000000')
  const [out, setOut] = useState('250000')
  const q = useQuery({
    queryKey: ['pricing-preview', provider, model, inp, out],
    queryFn: () => api<CostPreview>('/pricing/preview', { query: { provider, model, input_tokens: inp || 0, output_tokens: out || 0 } }),
    enabled: model.trim().length > 0,
  })
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Calculator className="size-4 text-accent" /> Cost calculator</span>} subtitle="Check which price entry applies to a model and estimate the cost of a workload." />
      <div className="grid gap-3 p-5 sm:grid-cols-4">
        <SelectField label="Provider" value={provider} onChange={(e) => setProvider(e.target.value as Provider)}>
          {PROVIDERS.map((p) => <option key={p} value={p}>{PROVIDER_LABEL[p]}</option>)}
        </SelectField>
        <TextField label="Model" value={model} onChange={(e) => setModel(e.target.value)} />
        <TextField label="Input tokens" type="number" min={0} value={inp} onChange={(e) => setInp(e.target.value)} />
        <TextField label="Output tokens" type="number" min={0} value={out} onChange={(e) => setOut(e.target.value)} />
      </div>
      <div className="border-t border-line/70 px-5 py-4 text-sm">
        {q.isError ? (
          <span className="text-bad">{errorMessage(q.error)}</span>
        ) : q.data ? (
          q.data.status === 'estimated' ? (
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
              <span className="text-2xl font-semibold text-ink">{formatUsd(q.data.total_cost_usd, { precise: true })}</span>
              <span className="text-muted">input {formatUsd(q.data.input_cost_usd, { precise: true })} · output {formatUsd(q.data.output_cost_usd, { precise: true })}</span>
              <span className="text-muted">using <span className="mono text-ink-2">{q.data.matched_pricing?.model}</span> ({q.data.matched_pricing?.scope}, {q.data.matched_pricing?.verified ? 'verified' : 'unverified'})</span>
            </div>
          ) : (
            <span className="text-warn">No price entry matches this model — requests to it will show an unknown cost.</span>
          )
        ) : (
          <span className="text-muted">Enter a model name.</span>
        )}
      </div>
    </Card>
  )
}

function PricingTab() {
  const [provider, setProvider] = useState<'' | Provider>('')
  const [editing, setEditing] = useState<Pricing | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Pricing | null>(null)
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['pricing', provider], queryFn: () => api<Pricing[]>('/pricing', { query: { provider } }) })
  const remove = useMutation({
    mutationFn: (p: Pricing) => api(`/pricing/${p.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      setDeleting(null)
      qc.invalidateQueries({ queryKey: ['pricing'] })
    },
  })
  return (
    <div className="space-y-4">
      <CostCalculator />
      <Card>
        <CardHeader
          title="Model pricing"
          subtitle="Reference prices are seeded for convenience and marked unverified. Add a custom entry to override a price or price a model that is missing."
          action={
            <div className="flex gap-2">
              <select className="input h-8 w-auto appearance-none pr-8 text-xs" value={provider} onChange={(e) => setProvider(e.target.value as Provider | '')} aria-label="Filter by provider">
                <option value="">All providers</option>
                {PROVIDERS.map((p) => <option key={p} value={p}>{PROVIDER_LABEL[p]}</option>)}
              </select>
              <Button size="sm" variant="primary" icon={<Plus className="size-3.5" />} onClick={() => setEditing('new')}>Add price</Button>
            </div>
          }
        />
        {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px]">
              <thead className="border-b border-line/70">
                <tr><th className="th">Provider</th><th className="th">Model</th><th className="th text-right">Input / 1M</th><th className="th text-right">Output / 1M</th><th className="th">Source</th><th className="th">Status</th><th className="th" /></tr>
              </thead>
              <tbody>
                {q.data!.map((p) => (
                  <tr key={p.id} className="border-b border-line/40 last:border-0">
                    <td className="td">{PROVIDER_LABEL[p.provider]}</td>
                    <td className="td mono text-ink" title={p.notes}>{p.model}</td>
                    <td className="td text-right tabular-nums">${Number(p.input_price_per_mtok)}</td>
                    <td className="td text-right tabular-nums">${Number(p.output_price_per_mtok)}</td>
                    <td className="td">{p.scope === 'custom' ? <Badge tone="accent">custom</Badge> : <Badge>reference</Badge>}</td>
                    <td className="td">{p.verified ? <Badge tone="ok">verified</Badge> : <Badge tone="warn">unverified</Badge>}</td>
                    <td className="td text-right whitespace-nowrap">
                      <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(p)}>{p.scope === 'custom' ? 'Edit' : 'Override'}</Button>
                      {p.scope === 'custom' && <Button size="sm" variant="ghost" className="text-bad" icon={<Trash2 className="size-3.5" />} onClick={() => setDeleting(p)} aria-label="Delete" />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {editing && <PricingModal initial={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} onConfirm={() => deleting && remove.mutate(deleting)} loading={remove.isPending} error={remove.error} title="Delete custom price?" confirmLabel="Delete" message={<>Future requests to <span className="mono">{deleting?.model}</span> will use the reference price (if any). Past estimates keep their original pricing snapshot.</>} />
    </div>
  )
}

export default function Costs() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'pricing' ? 'pricing' : 'spend'
  return (
    <>
      <PageHeader title="Costs & pricing" description="Estimated spend by provider, model and project, and the pricing table used to compute it." />
      <Tabs
        tabs={[{ key: 'spend', label: 'Spending' }, { key: 'pricing', label: 'Pricing table' }]}
        value={tab}
        onChange={(k) => setParams(k === 'pricing' ? { tab: 'pricing' } : {}, { replace: true })}
      />
      {tab === 'spend' ? <SpendTab /> : <PricingTab />}
    </>
  )
}

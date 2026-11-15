import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BellRing, Pencil, Plus, Trash2, Wallet } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useProjects } from '../lib/queries'
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
  ProgressBar,
  SelectField,
  Tabs,
  TextField,
  Toggle,
} from '../components/ui'
import { api, errorMessage } from '../lib/api'
import { formatDateTime, formatRelative, formatUsd } from '../lib/format'
import type { AlertMetric, AlertRule, Budget, NotificationList } from '../lib/types'

const METRICS: Record<AlertMetric, { label: string; unit: string; help: string }> = {
  error_rate: { label: 'Error rate', unit: '%', help: 'Percentage of failed requests in the window' },
  request_volume: { label: 'Request volume', unit: 'requests', help: 'Number of requests in the window' },
  token_usage: { label: 'Token usage', unit: 'tokens', help: 'Input + output tokens in the window' },
  spend: { label: 'Estimated spend', unit: 'USD', help: 'Estimated cost in the window' },
}

function ProjectPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const projects = useProjects()
  return (
    <SelectField label="Scope" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Whole account</option>
      {projects.data?.map((p) => <option key={p.id} value={p.id}>Project: {p.name}</option>)}
    </SelectField>
  )
}

function useProjectName() {
  const projects = useProjects()
  return (id: string | null) => (id ? projects.data?.find((p) => p.id === id)?.name ?? 'Project' : 'Whole account')
}

/* ------------------------------------------------------------------ Budgets */
function BudgetModal({ initial, onClose }: { initial?: Budget; onClose: () => void }) {
  const qc = useQueryClient()
  const [v, setV] = useState({
    name: initial?.name ?? 'Monthly budget',
    project_id: initial?.project_id ?? '',
    period: initial?.period ?? 'monthly',
    limit_usd: initial ? String(Number(initial.limit_usd)) : '100',
    thresholds: (initial?.warning_thresholds ?? [50, 80, 100]).join(', '),
    enforce_limit: initial?.enforce_limit ?? false,
    enabled: initial?.enabled ?? true,
  })
  const thresholds = v.thresholds.split(/[,\s]+/).filter(Boolean).map(Number)
  const thresholdsValid = thresholds.length > 0 && thresholds.every((t) => Number.isInteger(t) && t >= 1 && t <= 500)
  const save = useMutation({
    mutationFn: () => {
      const body = { name: v.name, project_id: v.project_id || null, period: v.period, limit_usd: v.limit_usd, warning_thresholds: thresholds, enforce_limit: v.enforce_limit, enabled: v.enabled }
      return initial ? api(`/budgets/${initial.id}`, { method: 'PUT', body }) : api('/budgets', { method: 'POST', body })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['budgets'] })
      qc.invalidateQueries({ queryKey: ['notifications'] })
      onClose()
    },
  })
  return (
    <Modal open onClose={onClose} title={initial ? 'Edit budget' : 'New budget'} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" form="budget-form" loading={save.isPending} disabled={!v.name.trim() || !(Number(v.limit_usd) > 0) || !thresholdsValid}>Save budget</Button></>}>
      <form id="budget-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate() }}>
        <TextField className="sm:col-span-2" label="Name" value={v.name} maxLength={100} onChange={(e) => setV({ ...v, name: e.target.value })} />
        <ProjectPicker value={v.project_id} onChange={(id) => setV({ ...v, project_id: id })} />
        <SelectField label="Period (UTC)" value={v.period} onChange={(e) => setV({ ...v, period: e.target.value as 'daily' | 'monthly' })}>
          <option value="monthly">Monthly</option>
          <option value="daily">Daily</option>
        </SelectField>
        <TextField label="Limit (USD)" type="number" min={0.01} step="0.01" value={v.limit_usd} onChange={(e) => setV({ ...v, limit_usd: e.target.value })} />
        <TextField label="Warning thresholds (%)" value={v.thresholds} onChange={(e) => setV({ ...v, thresholds: e.target.value })} error={thresholdsValid ? null : 'Comma-separated whole numbers from 1 to 500'} hint="An in-app notification is created when each threshold is crossed." />
        <div className="space-y-3 sm:col-span-2">
          <Toggle checked={v.enforce_limit} onChange={(x) => setV({ ...v, enforce_limit: x })} label="Enforce limit" description="Block gateway requests (HTTP 402) in this scope once 100% of the limit is reached for the period." />
          <Toggle checked={v.enabled} onChange={(x) => setV({ ...v, enabled: x })} label="Enabled" />
        </div>
        {save.isError && <Alert tone="bad" className="sm:col-span-2">{errorMessage(save.error)}</Alert>}
      </form>
    </Modal>
  )
}

function BudgetsTab() {
  const q = useQuery({ queryKey: ['budgets'], queryFn: () => api<Budget[]>('/budgets') })
  const [editing, setEditing] = useState<Budget | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Budget | null>(null)
  const qc = useQueryClient()
  const projectName = useProjectName()
  const remove = useMutation({ mutationFn: (b: Budget) => api(`/budgets/${b.id}`, { method: 'DELETE' }), onSuccess: () => { setDeleting(null); qc.invalidateQueries({ queryKey: ['budgets'] }) } })
  return (
    <>
      <div className="mb-4 flex justify-end"><Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setEditing('new')}>New budget</Button></div>
      {q.isLoading ? <LoadingBlock /> : q.isError ? <Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card> : !q.data!.length ? (
        <Card><EmptyState icon={<Wallet className="size-5" />} title="No budgets" description="Set daily or monthly spending budgets for your account or for individual projects, with warning thresholds and optional enforcement." action={<Button variant="primary" onClick={() => setEditing('new')}>Create a budget</Button>} /></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {q.data!.map((b) => (
            <Card key={b.id} className="p-5">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="truncate font-semibold">{b.name}</h3>
                  <p className="text-xs text-muted">{projectName(b.project_id)} · {b.period} · since {b.period_start}</p>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(b)} aria-label="Edit budget" />
                  <Button size="sm" variant="ghost" className="text-bad" icon={<Trash2 className="size-3.5" />} onClick={() => setDeleting(b)} aria-label="Delete budget" />
                </div>
              </div>
              <div className="mt-4 flex items-baseline justify-between">
                <span className="text-2xl font-semibold tabular-nums">{formatUsd(b.current_spend_usd)}</span>
                <span className="text-sm text-muted">of {formatUsd(b.limit_usd)}</span>
              </div>
              <div className="mt-2"><ProgressBar value={b.percent_used} /></div>
              <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
                <span className="text-muted">{b.percent_used.toFixed(1)}% used ·</span>
                {b.warning_thresholds.map((t) => <Badge key={t} tone={b.percent_used >= t ? 'warn' : 'neutral'}>{t}%</Badge>)}
                {b.enforce_limit && <Badge tone="bad">enforced</Badge>}
                {!b.enabled && <Badge>disabled</Badge>}
              </div>
            </Card>
          ))}
        </div>
      )}
      {editing && <BudgetModal initial={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} onConfirm={() => deleting && remove.mutate(deleting)} loading={remove.isPending} error={remove.error} title="Delete budget?" confirmLabel="Delete" message={`“${deleting?.name}” will stop tracking spend${deleting?.enforce_limit ? ' and will no longer block requests' : ''}.`} />
    </>
  )
}

/* ------------------------------------------------------------------ Alert rules */
function RuleModal({ initial, onClose }: { initial?: AlertRule; onClose: () => void }) {
  const qc = useQueryClient()
  const [v, setV] = useState({
    name: initial?.name ?? 'High error rate',
    project_id: initial?.project_id ?? '',
    metric: initial?.metric ?? ('error_rate' as AlertMetric),
    threshold: initial ? String(Number(initial.threshold)) : '10',
    window_minutes: String(initial?.window_minutes ?? 60),
    min_requests: String(initial?.min_requests ?? 10),
    cooldown_minutes: String(initial?.cooldown_minutes ?? 60),
    enabled: initial?.enabled ?? true,
  })
  const save = useMutation({
    mutationFn: () => {
      const body = { ...v, project_id: v.project_id || null, window_minutes: Number(v.window_minutes), min_requests: Number(v.min_requests), cooldown_minutes: Number(v.cooldown_minutes) }
      return initial ? api(`/alert-rules/${initial.id}`, { method: 'PUT', body }) : api('/alert-rules', { method: 'POST', body })
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['alert-rules'] }); onClose() },
  })
  const m = METRICS[v.metric]
  return (
    <Modal open onClose={onClose} title={initial ? 'Edit alert rule' : 'New alert rule'} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" form="rule-form" loading={save.isPending} disabled={!v.name.trim() || !(Number(v.threshold) > 0)}>Save rule</Button></>}>
      <form id="rule-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate() }}>
        <TextField className="sm:col-span-2" label="Name" value={v.name} maxLength={100} onChange={(e) => setV({ ...v, name: e.target.value })} />
        <SelectField label="Metric" value={v.metric} onChange={(e) => setV({ ...v, metric: e.target.value as AlertMetric })} hint={m.help}>
          {(Object.keys(METRICS) as AlertMetric[]).map((k) => <option key={k} value={k}>{METRICS[k].label}</option>)}
        </SelectField>
        <TextField label={`Threshold (${m.unit})`} type="number" min={0} step="any" value={v.threshold} onChange={(e) => setV({ ...v, threshold: e.target.value })} />
        <ProjectPicker value={v.project_id} onChange={(id) => setV({ ...v, project_id: id })} />
        <TextField label="Window (minutes)" type="number" min={5} max={10080} value={v.window_minutes} onChange={(e) => setV({ ...v, window_minutes: e.target.value })} />
        {v.metric === 'error_rate' && <TextField label="Minimum requests" type="number" min={1} value={v.min_requests} onChange={(e) => setV({ ...v, min_requests: e.target.value })} hint="Avoids alerts on tiny samples." />}
        <TextField label="Cooldown (minutes)" type="number" min={5} max={10080} value={v.cooldown_minutes} onChange={(e) => setV({ ...v, cooldown_minutes: e.target.value })} hint="Minimum time between notifications." />
        <div className="sm:col-span-2"><Toggle checked={v.enabled} onChange={(x) => setV({ ...v, enabled: x })} label="Enabled" /></div>
        {save.isError && <Alert tone="bad" className="sm:col-span-2">{errorMessage(save.error)}</Alert>}
      </form>
    </Modal>
  )
}

function RulesTab() {
  const q = useQuery({ queryKey: ['alert-rules'], queryFn: () => api<AlertRule[]>('/alert-rules') })
  const [editing, setEditing] = useState<AlertRule | 'new' | null>(null)
  const [deleting, setDeleting] = useState<AlertRule | null>(null)
  const qc = useQueryClient()
  const projectName = useProjectName()
  const remove = useMutation({ mutationFn: (r: AlertRule) => api(`/alert-rules/${r.id}`, { method: 'DELETE' }), onSuccess: () => { setDeleting(null); qc.invalidateQueries({ queryKey: ['alert-rules'] }) } })
  return (
    <>
      <div className="mb-4 flex justify-end"><Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setEditing('new')}>New rule</Button></div>
      <Card>
        {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !q.data!.length ? (
          <EmptyState icon={<BellRing className="size-5" />} title="No alert rules" description="Get notified when error rates spike or usage exceeds a threshold. Rules are evaluated after every gateway request." action={<Button variant="primary" onClick={() => setEditing('new')}>Create a rule</Button>} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px]">
              <thead className="border-b border-line/70"><tr><th className="th">Rule</th><th className="th">Condition</th><th className="th">Scope</th><th className="th">Last triggered</th><th className="th">Status</th><th className="th" /></tr></thead>
              <tbody>
                {q.data!.map((r) => (
                  <tr key={r.id} className="border-b border-line/40 last:border-0">
                    <td className="td text-ink">{r.name}</td>
                    <td className="td">{METRICS[r.metric].label} ≥ {Number(r.threshold)} {METRICS[r.metric].unit} in {r.window_minutes} min</td>
                    <td className="td">{projectName(r.project_id)}</td>
                    <td className="td">{formatRelative(r.last_triggered_at)}</td>
                    <td className="td">{r.enabled ? <Badge tone="ok">enabled</Badge> : <Badge>disabled</Badge>}</td>
                    <td className="td text-right whitespace-nowrap">
                      <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(r)} aria-label="Edit rule" />
                      <Button size="sm" variant="ghost" className="text-bad" icon={<Trash2 className="size-3.5" />} onClick={() => setDeleting(r)} aria-label="Delete rule" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {editing && <RuleModal initial={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} onConfirm={() => deleting && remove.mutate(deleting)} loading={remove.isPending} error={remove.error} title="Delete alert rule?" confirmLabel="Delete" message={`“${deleting?.name}” will no longer be evaluated.`} />
    </>
  )
}

/* ------------------------------------------------------------------ Notifications */
function NotificationsTab() {
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [limit, setLimit] = useState(25)
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['notifications', 'history', unreadOnly, limit], queryFn: () => api<NotificationList>('/notifications', { query: { unread_only: unreadOnly, limit } }) })
  const invalidate = () => qc.invalidateQueries({ queryKey: ['notifications'] })
  const markRead = useMutation({ mutationFn: (id: string) => api(`/notifications/${id}/read`, { method: 'POST' }), onSuccess: invalidate })
  const remove = useMutation({ mutationFn: (id: string) => api(`/notifications/${id}`, { method: 'DELETE' }), onSuccess: invalidate })
  const readAll = useMutation({ mutationFn: () => api('/notifications/read-all', { method: 'POST' }), onSuccess: invalidate })
  return (
    <Card>
      <CardHeader
        title="Notification history"
        subtitle="Notifications are delivered in-app only. No email, SMS or chat integration is configured."
        action={<div className="flex items-center gap-3"><Toggle checked={unreadOnly} onChange={setUnreadOnly} label="Unread only" /><Button size="sm" onClick={() => readAll.mutate()} disabled={!q.data?.unread}>Mark all read</Button></div>}
      />
      {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !q.data!.items.length ? (
        <EmptyState icon={<BellRing className="size-5" />} title={unreadOnly ? 'No unread notifications' : 'No notifications yet'} description="Budget warnings and triggered alert rules appear here." />
      ) : (
        <>
          <ul>
            {q.data!.items.map((n) => (
              <li key={n.id} className={`flex flex-wrap items-start gap-3 border-b border-line/40 px-5 py-4 last:border-0 ${n.read_at ? '' : 'bg-accent/5'}`}>
                <Badge tone={n.severity === 'critical' ? 'bad' : n.severity === 'warning' ? 'warn' : 'info'}>{n.severity}</Badge>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-ink">{n.title}</p>
                  <p className="mt-0.5 text-sm text-muted">{n.message}</p>
                  <p className="mt-1 text-xs text-faint">{formatDateTime(n.created_at)} · {n.kind}</p>
                </div>
                <div className="flex gap-1">
                  {!n.read_at && <Button size="sm" variant="ghost" onClick={() => markRead.mutate(n.id)}>Mark read</Button>}
                  <Button size="sm" variant="ghost" className="text-bad" icon={<Trash2 className="size-3.5" />} onClick={() => remove.mutate(n.id)} aria-label="Delete notification" />
                </div>
              </li>
            ))}
          </ul>
          {q.data!.total > q.data!.items.length && (
            <div className="border-t border-line/70 p-3 text-center"><Button size="sm" variant="ghost" onClick={() => setLimit((l) => Math.min(l + 25, 100))} disabled={limit >= 100}>Load more</Button></div>
          )}
        </>
      )}
    </Card>
  )
}

type TabKey = 'budgets' | 'rules' | 'notifications'

export default function Alerts() {
  const [params, setParams] = useSearchParams()
  const t = params.get('tab')
  const tab: TabKey = t === 'rules' || t === 'notifications' ? t : 'budgets'
  return (
    <>
      <PageHeader title="Budgets & alerts" description="Spending budgets, usage and error-rate alert rules, and the in-app notification history." />
      <Tabs<TabKey>
        tabs={[{ key: 'budgets', label: 'Budgets' }, { key: 'rules', label: 'Alert rules' }, { key: 'notifications', label: 'Notifications' }]}
        value={tab}
        onChange={(k) => setParams({ tab: k }, { replace: true })}
      />
      {tab === 'budgets' ? <BudgetsTab /> : tab === 'rules' ? <RulesTab /> : <NotificationsTab />}
    </>
  )
}

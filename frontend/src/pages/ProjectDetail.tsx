import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, KeyRound, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ProjectFormModal, type ProjectFormValues } from '../components/ProjectForm'
import { StatCard } from '../components/StatCard'
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  CopyButton,
  EmptyState,
  ErrorState,
  LoadingBlock,
  Modal,
  PageHeader,
  TextField,
} from '../components/ui'
import { api, errorMessage } from '../lib/api'
import { PROVIDER_LABEL, formatCompact, formatDate, formatDateTime, formatNumber, formatPercent, formatRelative, formatUsd } from '../lib/format'
import type { ApiKey, ApiKeyCreated, Project } from '../lib/types'

function NewKeyModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const [name, setName] = useState('Production')
  const qc = useQueryClient()
  const create = useMutation({
    mutationFn: () => api<ApiKeyCreated>(`/projects/${projectId}/keys`, { method: 'POST', body: { name } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project-keys', projectId] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
  const created = create.data
  return (
    <Modal
      open
      onClose={onClose}
      title={created ? 'Copy your new API key' : 'Create API key'}
      description={created ? 'This is the only time the full key is shown. Store it in a secret manager.' : 'Keys authenticate requests to the gateway for this project.'}
      footer={
        created ? (
          <Button variant="primary" onClick={onClose}>I have stored the key</Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="primary" type="submit" form="key-form" loading={create.isPending} disabled={!name.trim()}>Create key</Button>
          </>
        )
      }
    >
      {created ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2 rounded-lg border border-line bg-bg-2 p-3">
            <code className="mono flex-1 break-all text-ink">{created.key}</code>
            <CopyButton value={created.key} />
          </div>
          <Alert tone="warn">ModelOps stores only a SHA-256 hash of this key. If you lose it, revoke it and create a new one.</Alert>
        </div>
      ) : (
        <form
          id="key-form"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            create.mutate()
          }}
        >
          <TextField label="Key name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} hint="A label to recognise where this key is used." />
          {create.isError && <Alert tone="bad" className="mt-3">{errorMessage(create.error)}</Alert>}
        </form>
      )}
    </Modal>
  )
}

export default function ProjectDetail() {
  const { projectId = '' } = useParams()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [newKey, setNewKey] = useState(search.get('new') === '1')
  const [revoking, setRevoking] = useState<ApiKey | null>(null)
  const [deleting, setDeleting] = useState(false)

  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api<Project>(`/projects/${projectId}`) })
  const keys = useQuery({ queryKey: ['project-keys', projectId], queryFn: () => api<ApiKey[]>(`/projects/${projectId}/keys`) })

  const update = useMutation({
    mutationFn: (v: ProjectFormValues) => api<Project>(`/projects/${projectId}`, { method: 'PATCH', body: v }),
    onSuccess: (p) => {
      qc.setQueryData(['project', projectId], p)
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
  const revoke = useMutation({
    mutationFn: (k: ApiKey) => api(`/projects/${projectId}/keys/${k.id}/revoke`, { method: 'POST' }),
    onSuccess: () => {
      setRevoking(null)
      qc.invalidateQueries({ queryKey: ['project-keys', projectId] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
  const remove = useMutation({
    mutationFn: () => api(`/projects/${projectId}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      navigate('/projects')
    },
  })

  if (project.isLoading) return <LoadingBlock />
  if (project.isError) return <Card><ErrorState error={project.error} onRetry={() => project.refetch()} /></Card>
  const p = project.data!
  const s = p.stats

  return (
    <>
      <Link to="/projects" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-ink"><ArrowLeft className="size-4" /> Projects</Link>
      <PageHeader
        title={p.name}
        description={p.description || 'No description'}
        actions={
          <>
            <Link to={`/requests?project_id=${p.id}`} className="inline-flex h-9 items-center rounded-lg border border-line-strong bg-surface-2 px-4 text-sm hover:bg-surface-3">View requests</Link>
            <Link to={`/?project_id=${p.id}&range=30d`} className="inline-flex h-9 items-center rounded-lg border border-line-strong bg-surface-2 px-4 text-sm hover:bg-surface-3">Analytics</Link>
            <Button icon={<Pencil className="size-4" />} onClick={() => setEditing(true)}>Edit</Button>
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted">
        <span>Created {formatDate(p.created_at)}</span>·<span>Providers:</span>
        {p.allowed_providers.length ? p.allowed_providers.map((x) => <Badge key={x}>{PROVIDER_LABEL[x]}</Badge>) : <Badge tone="warn">none</Badge>}
      </div>
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Requests (30d)" value={formatNumber(s?.requests_30d ?? 0)} />
        <StatCard label="Error rate (30d)" value={formatPercent(s?.requests_30d ? (s.errors_30d / s.requests_30d) * 100 : 0)} />
        <StatCard label="Tokens (30d)" value={formatCompact(s?.tokens_30d ?? 0)} />
        <StatCard label="Est. spend (30d)" value={formatUsd(s?.cost_30d_usd ?? 0)} sub={`last request ${formatRelative(s?.last_request_at)}`} />
      </div>

      <Card>
        <CardHeader
          title="API keys"
          subtitle="Use a key as the bearer token (or x-api-key / x-goog-api-key header) when calling the gateway."
          action={<Button size="sm" variant="primary" icon={<Plus className="size-3.5" />} onClick={() => setNewKey(true)}>Create key</Button>}
        />
        {keys.isLoading ? (
          <LoadingBlock />
        ) : keys.isError ? (
          <ErrorState error={keys.error} onRetry={() => keys.refetch()} />
        ) : !keys.data?.length ? (
          <EmptyState icon={<KeyRound className="size-5" />} title="No API keys" description="Create a key to start sending requests through the gateway." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px]">
              <thead className="border-b border-line/70">
                <tr><th className="th">Name</th><th className="th">Key</th><th className="th">Created</th><th className="th">Last used</th><th className="th">Status</th><th className="th" /></tr>
              </thead>
              <tbody>
                {keys.data.map((k) => (
                  <tr key={k.id} className="border-b border-line/40 last:border-0">
                    <td className="td text-ink">{k.name}</td>
                    <td className="td mono">{k.prefix}…</td>
                    <td className="td">{formatDateTime(k.created_at)}</td>
                    <td className="td">{formatRelative(k.last_used_at)}</td>
                    <td className="td">{k.revoked_at ? <Badge tone="bad">revoked</Badge> : <Badge tone="ok">active</Badge>}</td>
                    <td className="td text-right">{!k.revoked_at && <Button size="sm" variant="danger" onClick={() => setRevoking(k)}>Revoke</Button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="mt-6 border-bad/30">
        <CardHeader title="Delete project" subtitle="Removes the project and its API keys. Historical request records are kept but no longer linked to a project." action={<Button variant="danger" icon={<Trash2 className="size-4" />} onClick={() => setDeleting(true)}>Delete project</Button>} />
      </Card>

      {editing && (
        <ProjectFormModal open onClose={() => setEditing(false)} title="Edit project" submitLabel="Save changes" initial={{ name: p.name, description: p.description, allowed_providers: p.allowed_providers }} onSubmit={(v) => update.mutateAsync(v)} />
      )}
      {newKey && (
        <NewKeyModal
          projectId={p.id}
          onClose={() => {
            setNewKey(false)
            if (search.has('new')) navigate(`/projects/${p.id}`, { replace: true })
          }}
        />
      )}
      <ConfirmDialog
        open={!!revoking}
        onClose={() => setRevoking(null)}
        onConfirm={() => revoking && revoke.mutate(revoking)}
        loading={revoke.isPending}
        error={revoke.error}
        title="Revoke API key?"
        confirmLabel="Revoke key"
        message={<>Applications using <span className="mono text-ink">{revoking?.prefix}…</span> ({revoking?.name}) will immediately receive 401 errors. This cannot be undone.</>}
      />
      <ConfirmDialog
        open={deleting}
        onClose={() => setDeleting(false)}
        onConfirm={() => remove.mutate()}
        loading={remove.isPending}
        error={remove.error}
        title={`Delete “${p.name}”?`}
        confirmLabel="Delete project"
        message="All API keys for this project stop working immediately. This cannot be undone."
      />
    </>
  )
}

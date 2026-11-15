import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FolderKanban, KeyRound, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useProjects } from '../lib/queries'
import { ProjectFormModal, type ProjectFormValues } from '../components/ProjectForm'
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton } from '../components/ui'
import { api } from '../lib/api'
import { PROVIDER_LABEL, formatCompact, formatDate, formatNumber, formatRelative, formatUsd } from '../lib/format'
import type { Project } from '../lib/types'

export default function Projects() {
  const query = useProjects()
  const [creating, setCreating] = useState(false)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const create = useMutation({
    mutationFn: (v: ProjectFormValues) => api<Project>('/projects', { method: 'POST', body: v }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${p.id}?new=1`)
    },
  })

  return (
    <>
      <PageHeader
        title="Projects"
        description="Group gateway traffic by application. Each project has its own API keys, allowed providers and usage statistics."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>New project</Button>}
      />
      {query.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-48" />)}</div>
      ) : query.isError ? (
        <Card><ErrorState error={query.error} onRetry={() => query.refetch()} /></Card>
      ) : !query.data?.length ? (
        <Card>
          <EmptyState
            icon={<FolderKanban className="size-5" />}
            title="No projects yet"
            description="Create a project for each AI application you want to monitor, e.g. “Customer Support AI” or “Research Assistant”."
            action={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>Create your first project</Button>}
          />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {query.data.map((p) => (
            <Link key={p.id} to={`/projects/${p.id}`} className="card group flex flex-col p-5 transition-colors hover:border-line-strong">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate font-semibold text-ink group-hover:text-accent">{p.name}</h3>
                  <p className="mt-1 line-clamp-2 min-h-10 text-sm text-muted">{p.description || 'No description'}</p>
                </div>
                <Badge tone={p.active_keys ? 'ok' : 'neutral'}><KeyRound className="size-3" />{p.active_keys}</Badge>
              </div>
              <div className="mt-4 flex flex-wrap gap-1.5">
                {p.allowed_providers.length ? p.allowed_providers.map((pr) => <Badge key={pr}>{PROVIDER_LABEL[pr]}</Badge>) : <Badge tone="warn">No providers allowed</Badge>}
              </div>
              <dl className="mt-5 grid grid-cols-3 gap-3 border-t border-line/60 pt-4 text-sm">
                <div><dt className="text-xs text-muted">Requests (30d)</dt><dd className="mt-0.5 font-medium tabular-nums">{formatNumber(p.stats?.requests_30d ?? 0)}</dd></div>
                <div><dt className="text-xs text-muted">Tokens</dt><dd className="mt-0.5 font-medium tabular-nums">{formatCompact(p.stats?.tokens_30d ?? 0)}</dd></div>
                <div><dt className="text-xs text-muted">Est. spend</dt><dd className="mt-0.5 font-medium tabular-nums">{formatUsd(p.stats?.cost_30d_usd ?? 0)}</dd></div>
              </dl>
              <p className="mt-4 text-xs text-faint">Created {formatDate(p.created_at)} · last request {formatRelative(p.stats?.last_request_at)}</p>
            </Link>
          ))}
        </div>
      )}
      {creating && (
        <ProjectFormModal open onClose={() => setCreating(false)} title="New project" submitLabel="Create project" onSubmit={(v) => create.mutateAsync(v)} />
      )}
    </>
  )
}

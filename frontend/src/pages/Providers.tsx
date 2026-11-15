import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, CircleDashed, KeyRound, RefreshCw, ShieldCheck, Trash2, XCircle } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Alert, Badge, Button, Card, ConfirmDialog, ErrorState, Modal, PageHeader, Skeleton, TextField, Toggle } from '../components/ui'
import { api, errorMessage } from '../lib/api'
import { PROVIDER_COLOR, formatRelative } from '../lib/format'
import type { Credential, Provider, ProviderStatus } from '../lib/types'

const HELP: Record<Provider, { url: string; placeholder: string }> = {
  openai: { url: 'https://platform.openai.com/api-keys', placeholder: 'sk-...' },
  anthropic: { url: 'https://console.anthropic.com/settings/keys', placeholder: 'sk-ant-...' },
  gemini: { url: 'https://aistudio.google.com/app/apikey', placeholder: 'AIza...' },
}

const STATUS: Record<Credential['status'], { tone: 'ok' | 'bad' | 'warn' | 'neutral'; label: string; icon: typeof CheckCircle2 }> = {
  valid: { tone: 'ok', label: 'Connected', icon: CheckCircle2 },
  invalid: { tone: 'bad', label: 'Invalid key', icon: XCircle },
  error: { tone: 'warn', label: 'Check failed', icon: CircleAlert },
  unverified: { tone: 'neutral', label: 'Not verified', icon: CircleDashed },
}

function KeyModal({ provider, name, onClose }: { provider: Provider; name: string; onClose: () => void }) {
  const [key, setKey] = useState('')
  const [validateNow, setValidateNow] = useState(true)
  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: () => api<Credential>(`/providers/${provider}`, { method: 'PUT', body: { api_key: key.trim(), validate_now: validateNow } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['providers'] })
      onClose()
    },
  })
  return (
    <Modal
      open
      onClose={onClose}
      title={`${name} API key`}
      description="The key is encrypted before it is stored and is never shown again in full."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="key-modal-form" loading={save.isPending} disabled={key.trim().length < 8}>
            Save key
          </Button>
        </>
      }
    >
      <form id="key-modal-form" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate() }}>
        <TextField
          label="API key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder={HELP[provider].placeholder}
          hint={<>Create one in the <a href={HELP[provider].url} target="_blank" rel="noreferrer noopener" className="text-accent hover:underline">provider console</a>.</>}
        />
        <Toggle checked={validateNow} onChange={setValidateNow} label="Validate now" description="Makes a free model-list request to the provider to confirm the key works." />
        {save.isError && <Alert tone="bad">{errorMessage(save.error)}</Alert>}
      </form>
    </Modal>
  )
}

function ProviderCard({ item }: { item: ProviderStatus }) {
  const [editing, setEditing] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [showModels, setShowModels] = useState(false)
  const qc = useQueryClient()
  const validate = useMutation({
    mutationFn: () => api<Credential>(`/providers/${item.provider}/validate`, { method: 'POST' }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['providers'] }),
  })
  const remove = useMutation({
    mutationFn: () => api(`/providers/${item.provider}`, { method: 'DELETE' }),
    onSuccess: () => {
      setRemoving(false)
      qc.invalidateQueries({ queryKey: ['providers'] })
    },
  })
  const c = item.credential
  const st = c ? STATUS[c.status] : null

  return (
    <Card className="flex flex-col">
      <div className="flex items-start gap-3 p-5">
        <div className="grid size-10 shrink-0 place-items-center rounded-lg border border-line bg-bg-2">
          <span className="size-3 rounded-full" style={{ background: PROVIDER_COLOR[item.provider] }} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-ink">{item.display_name}</h3>
            {st ? <Badge tone={st.tone}><st.icon className="size-3" />{st.label}</Badge> : <Badge>Not configured</Badge>}
          </div>
          {c ? (
            <p className="mt-1 text-sm text-muted">
              Key <span className="mono text-ink-2">{c.key_hint}</span> · checked {formatRelative(c.last_validated_at)}
            </p>
          ) : (
            <p className="mt-1 text-sm text-muted">Add an API key to route {item.display_name} requests through the gateway.</p>
          )}
        </div>
      </div>
      {c && (
        <div className="space-y-3 px-5 pb-4">
          <p className="text-sm text-ink-2">{c.status_message}</p>
          {c.available_models.length > 0 && (
            <div>
              <button className="text-xs text-accent hover:underline" onClick={() => setShowModels((v) => !v)}>
                {showModels ? 'Hide' : 'Show'} {c.available_models.length} available models
              </button>
              {showModels && (
                <div className="mt-2 flex max-h-40 flex-wrap gap-1.5 overflow-y-auto rounded-lg border border-line bg-bg-2 p-2.5">
                  {c.available_models.map((m) => <span key={m} className="mono rounded bg-surface-2 px-1.5 py-0.5 text-ink-2">{m}</span>)}
                </div>
              )}
            </div>
          )}
          {validate.isError && <Alert tone="bad">{errorMessage(validate.error)}</Alert>}
        </div>
      )}
      <div className="mt-auto flex flex-wrap gap-2 border-t border-line/70 px-5 py-3">
        <Button size="sm" variant={c ? 'secondary' : 'primary'} icon={<KeyRound className="size-3.5" />} onClick={() => setEditing(true)}>
          {c ? 'Replace key' : 'Add key'}
        </Button>
        {c && (
          <>
            <Button size="sm" icon={<RefreshCw className="size-3.5" />} loading={validate.isPending} onClick={() => validate.mutate()}>Validate</Button>
            <Button size="sm" variant="ghost" className="ml-auto text-bad hover:text-bad" icon={<Trash2 className="size-3.5" />} onClick={() => setRemoving(true)}>Remove</Button>
          </>
        )}
      </div>
      {editing && <KeyModal provider={item.provider} name={item.display_name} onClose={() => setEditing(false)} />}
      <ConfirmDialog
        open={removing}
        onClose={() => setRemoving(false)}
        onConfirm={() => remove.mutate()}
        loading={remove.isPending}
        error={remove.error}
        title={`Remove ${item.display_name} key?`}
        confirmLabel="Remove key"
        message="Gateway requests to this provider will fail with “provider_not_configured” until a new key is added."
      />
    </Card>
  )
}

export default function Providers() {
  const query = useQuery({ queryKey: ['providers'], queryFn: () => api<ProviderStatus[]>('/providers') })
  return (
    <>
      <PageHeader title="Providers" description="Connect the AI providers your applications use. Keys belong to your account and are shared by all of your projects." />
      <Alert tone="info" className="mb-5 flex items-start gap-2">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" />
        <span>Keys are encrypted at rest with the server's master key, never returned to the browser in full, and never written to logs.</span>
      </Alert>
      {query.isLoading ? (
        <div className="grid gap-4 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-52" />)}</div>
      ) : query.isError ? (
        <Card><ErrorState error={query.error} onRetry={() => query.refetch()} /></Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">{query.data!.map((item) => <ProviderCard key={item.provider} item={item} />)}</div>
      )}
    </>
  )
}

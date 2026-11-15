import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Laptop, LogOut, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Alert, Badge, Button, Card, CardHeader, ErrorState, LoadingBlock, Modal, PageHeader, TextField } from '../components/ui'
import { api, errorMessage } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatDate, formatDateTime, formatRelative } from '../lib/format'
import type { SessionInfo, User } from '../lib/types'
import { passwordIssues } from '../lib/password'

function describeAgent(ua: string): string {
  if (!ua) return 'Unknown device'
  const browser = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : 'Client'
  const os = /Windows/.test(ua) ? 'Windows' : /Mac OS X/.test(ua) ? 'macOS' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Linux/.test(ua) ? 'Linux' : ''
  return os ? `${browser} on ${os}` : browser
}

function ProfileCard() {
  const { user, setUser } = useAuth()
  const [name, setName] = useState(user?.full_name ?? '')
  const save = useMutation({
    mutationFn: () => api<User>('/auth/me', { method: 'PATCH', body: { full_name: name } }),
    onSuccess: setUser,
  })
  return (
    <Card>
      <CardHeader title="Profile" subtitle={`Member since ${formatDate(user?.created_at)}`} />
      <form className="grid gap-4 p-5 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate() }}>
        <TextField label="Full name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
        <TextField label="Email" value={user?.email ?? ''} disabled hint="Email changes are not supported yet." />
        <div className="flex items-center gap-3 sm:col-span-2">
          <Button type="submit" variant="primary" loading={save.isPending} disabled={name === user?.full_name}>Save profile</Button>
          {save.isSuccess && <span className="text-sm text-ok">Saved.</span>}
          {save.isError && <span className="text-sm text-bad">{errorMessage(save.error)}</span>}
        </div>
      </form>
    </Card>
  )
}

function PasswordCard() {
  const { clearSession, user } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const issues = next ? passwordIssues(next) : []
  const change = useMutation({
    mutationFn: () => api('/auth/change-password', { method: 'POST', body: { current_password: current, new_password: next } }),
    onSuccess: () => clearSession(), // all sessions are revoked server-side; sign in again
  })
  const valid = current && next && !issues.length && next === confirm
  return (
    <Card>
      <CardHeader title="Change password" subtitle={`Last changed ${formatRelative(user?.password_changed_at)}. Changing it signs out every session.`} />
      <form className="grid gap-4 p-5 sm:grid-cols-3" onSubmit={(e: FormEvent) => { e.preventDefault(); change.mutate() }}>
        <TextField label="Current password" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        <TextField label="New password" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} error={issues.length ? `Needs ${issues.join(' and ')}` : null} />
        <TextField label="Confirm new password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} error={confirm && confirm !== next ? 'Passwords do not match' : null} />
        <div className="sm:col-span-3">
          <Button type="submit" variant="primary" loading={change.isPending} disabled={!valid}>Update password</Button>
          {change.isError && <Alert tone="bad" className="mt-3">{errorMessage(change.error)}</Alert>}
        </div>
      </form>
    </Card>
  )
}

function SessionsCard() {
  const qc = useQueryClient()
  const { clearSession } = useAuth()
  const q = useQuery({ queryKey: ['sessions'], queryFn: () => api<SessionInfo[]>('/auth/sessions') })
  const revoke = useMutation({ mutationFn: (id: string) => api(`/auth/sessions/${id}`, { method: 'DELETE' }), onSuccess: () => qc.invalidateQueries({ queryKey: ['sessions'] }) })
  const all = useMutation({ mutationFn: () => api('/auth/logout-all', { method: 'POST' }), onSuccess: () => clearSession() })
  return (
    <Card>
      <CardHeader title="Active sessions" subtitle="Devices currently signed in to your account." action={<Button size="sm" variant="danger" icon={<LogOut className="size-3.5" />} loading={all.isPending} onClick={() => all.mutate()}>Sign out everywhere</Button>} />
      {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : (
        <ul>
          {q.data!.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-3 border-b border-line/40 px-5 py-3 last:border-0">
              <Laptop className="size-4 text-muted" />
              <div className="min-w-0 flex-1">
                <p className="text-sm text-ink">{describeAgent(s.user_agent)} {s.current && <Badge tone="ok" className="ml-1">this device</Badge>}</p>
                <p className="text-xs text-muted">Signed in {formatDateTime(s.created_at)} · expires {formatDate(s.expires_at)}</p>
              </div>
              {!s.current && <Button size="sm" variant="ghost" onClick={() => revoke.mutate(s.id)}>Revoke</Button>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function DangerCard() {
  const { clearSession } = useAuth()
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const del = useMutation({
    mutationFn: () => api('/auth/me', { method: 'DELETE', body: { password, confirm } }),
    onSuccess: () => clearSession(),
  })
  return (
    <Card className="border-bad/30">
      <CardHeader title="Delete account" subtitle="Permanently deletes your account, projects, keys, credentials, request history, budgets and conversations." action={<Button variant="danger" icon={<Trash2 className="size-4" />} onClick={() => setOpen(true)}>Delete account</Button>} />
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Delete your account?"
        description="This cannot be undone."
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button variant="danger" loading={del.isPending} disabled={!password || confirm !== 'DELETE'} onClick={() => del.mutate()}>Permanently delete</Button></>}
      >
        <div className="space-y-4">
          <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <TextField label='Type "DELETE" to confirm' value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          {del.isError && <Alert tone="bad">{errorMessage(del.error)}</Alert>}
        </div>
      </Modal>
    </Card>
  )
}

export default function Settings() {
  return (
    <>
      <PageHeader title="Settings" description="Manage your profile, password, sessions and account." />
      <div className="space-y-5">
        <ProfileCard />
        <PasswordCard />
        <SessionsCard />
        <DangerCard />
      </div>
    </>
  )
}

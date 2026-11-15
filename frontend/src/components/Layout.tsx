import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Bell,
  Bot,
  BookOpen,
  ChevronDown,
  CircleDollarSign,
  FolderKanban,
  KeyRound,
  LayoutDashboard,
  ListTree,
  LogOut,
  Menu,
  Search,
  Settings,
  ShieldAlert,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatRelative } from '../lib/format'
import type { NotificationList } from '../lib/types'
import { Badge } from './ui'

const NAV: { to: string; label: string; icon: typeof LayoutDashboard; section?: string }[] = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, section: 'Monitor' },
  { to: '/requests', label: 'Request logs', icon: ListTree },
  { to: '/costs', label: 'Costs & pricing', icon: CircleDollarSign },
  { to: '/analyst', label: 'AI Analyst', icon: Bot },
  { to: '/projects', label: 'Projects', icon: FolderKanban, section: 'Configure' },
  { to: '/providers', label: 'Providers', icon: KeyRound },
  { to: '/alerts', label: 'Budgets & alerts', icon: ShieldAlert },
  { to: '/gateway', label: 'Gateway quickstart', icon: BookOpen },
]

export function Logo({ className }: { className?: string }) {
  return (
    <div className={clsx('flex items-center gap-2.5', className)}>
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <defs>
          <linearGradient id="logo-g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#4f8cff" />
            <stop offset="1" stopColor="#8b5cf6" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="8" fill="#141c38" stroke="#2e3b68" />
        <path d="M7 22V10l5 7 4-5 4 5 5-7v12" fill="none" stroke="url(#logo-g)" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight text-ink">ModelOps AI</div>
        <div className="text-[10.5px] text-muted">Observability & cost intelligence</div>
      </div>
    </div>
  )
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex h-full flex-col gap-1 px-3 py-4" aria-label="Main">
      <Link to="/" onClick={onNavigate} className="mb-5 px-2">
        <Logo />
      </Link>
      {NAV.map((item) => (
        <div key={item.to}>
          {item.section && (
            <div className="mt-3 mb-1.5 px-2.5 text-[10.5px] font-semibold tracking-wider text-faint uppercase">
              {item.section}
            </div>
          )}
          <NavLink
            to={item.to}
            end={item.to === '/'}
            onClick={onNavigate}
            className={({ isActive }) =>
              clsx(
                'group flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors',
                isActive
                  ? 'bg-gradient-to-r from-accent/15 to-accent-2/5 text-ink shadow-[inset_2px_0_0_0_var(--color-accent)]'
                  : 'text-ink-2 hover:bg-surface-2 hover:text-ink',
              )
            }
          >
            <item.icon className="size-4 shrink-0 opacity-80" />
            {item.label}
          </NavLink>
        </div>
      ))}
      <div className="mt-auto">
        <NavLink
          to="/settings"
          onClick={onNavigate}
          className={({ isActive }) =>
            clsx(
              'flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors',
              isActive ? 'bg-surface-2 text-ink' : 'text-ink-2 hover:bg-surface-2 hover:text-ink',
            )
          }
        >
          <Settings className="size-4 opacity-80" /> Settings
        </NavLink>
      </div>
    </nav>
  )
}

function useClickOutside(ref: React.RefObject<HTMLElement | null>, onOutside: () => void, active: boolean) {
  useEffect(() => {
    if (!active) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOutside()
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onOutside()
    document.addEventListener('mousedown', handler)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', handler)
      document.removeEventListener('keydown', onKey)
    }
  }, [ref, onOutside, active])
}

function Dropdown({
  trigger,
  children,
  open,
  setOpen,
  width = 'w-80',
}: {
  trigger: ReactNode
  children: ReactNode
  open: boolean
  setOpen: (v: boolean) => void
  width?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  useClickOutside(ref, () => setOpen(false), open)
  return (
    <div className="relative" ref={ref}>
      {trigger}
      {open && (
        <div className={clsx('card absolute right-0 z-40 mt-2 animate-slide-up overflow-hidden bg-surface', width, 'max-w-[calc(100vw-1.5rem)]')}>
          {children}
        </div>
      )}
    </div>
  )
}

const SEVERITY_TONE = { info: 'info', warning: 'warn', critical: 'bad' } as const

function NotificationsMenu() {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['notifications', 'menu'],
    queryFn: () => api<NotificationList>('/notifications', { query: { limit: 8 } }),
    refetchInterval: 60_000,
  })
  const readAll = useMutation({
    mutationFn: () => api('/notifications/read-all', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
  const unread = data?.unread ?? 0
  return (
    <Dropdown
      open={open}
      setOpen={setOpen}
      trigger={
        <button
          onClick={() => setOpen(!open)}
          className="relative grid size-9 place-items-center rounded-lg text-ink-2 hover:bg-surface-2 hover:text-ink"
          aria-label={`Notifications${unread ? ` (${unread} unread)` : ''}`}
        >
          <Bell className="size-[18px]" />
          {unread > 0 && (
            <span className="absolute top-1 right-1 grid min-w-4 place-items-center rounded-full bg-bad px-1 text-[10px] font-semibold text-white">
              {unread > 9 ? '9+' : unread}
            </span>
          )}
        </button>
      }
    >
      <div className="flex items-center justify-between border-b border-line/70 px-4 py-3">
        <span className="text-sm font-semibold">Notifications</span>
        {unread > 0 && (
          <button className="text-xs text-accent hover:underline" onClick={() => readAll.mutate()}>
            Mark all read
          </button>
        )}
      </div>
      <div className="max-h-96 overflow-y-auto">
        {!data?.items.length ? (
          <p className="px-4 py-8 text-center text-sm text-muted">No notifications yet.</p>
        ) : (
          data.items.map((n) => (
            <div key={n.id} className={clsx('border-b border-line/50 px-4 py-3 last:border-0', !n.read_at && 'bg-accent/5')}>
              <div className="flex items-center gap-2">
                <Badge tone={SEVERITY_TONE[n.severity]}>{n.severity}</Badge>
                <span className="ml-auto text-[11px] text-faint">{formatRelative(n.created_at)}</span>
              </div>
              <p className="mt-1.5 text-sm font-medium text-ink">{n.title}</p>
              <p className="mt-0.5 line-clamp-2 text-xs text-muted">{n.message}</p>
            </div>
          ))
        )}
      </div>
      <Link
        to="/alerts?tab=notifications"
        onClick={() => setOpen(false)}
        className="block border-t border-line/70 px-4 py-2.5 text-center text-xs text-accent hover:bg-surface-2"
      >
        View notification history
      </Link>
    </Dropdown>
  )
}

function ProfileMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const initials = (user?.full_name || user?.email || '?')
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]!.toUpperCase())
    .join('')
  return (
    <Dropdown
      open={open}
      setOpen={setOpen}
      width="w-64"
      trigger={
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 rounded-lg py-1 pr-2 pl-1 hover:bg-surface-2"
          aria-label="Account menu"
        >
          <span className="grid size-7 place-items-center rounded-full bg-gradient-to-br from-accent to-accent-2 text-[11px] font-semibold text-white">
            {initials}
          </span>
          <ChevronDown className="hidden size-3.5 text-muted sm:block" />
        </button>
      }
    >
      <div className="border-b border-line/70 px-4 py-3">
        <p className="truncate text-sm font-medium text-ink">{user?.full_name || 'Your account'}</p>
        <p className="truncate text-xs text-muted">{user?.email}</p>
      </div>
      <div className="p-1.5">
        <button
          onClick={() => {
            setOpen(false)
            navigate('/settings')
          }}
          className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink"
        >
          <Settings className="size-4" /> Account settings
        </button>
        <button
          onClick={() => logout()}
          className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink"
        >
          <LogOut className="size-4" /> Sign out
        </button>
      </div>
    </Dropdown>
  )
}

function GlobalSearch() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const term = q.trim()
    navigate(term ? `/requests?q=${encodeURIComponent(term)}` : '/requests')
    setQ('')
  }
  return (
    <form onSubmit={submit} className="relative hidden w-full max-w-sm md:block" role="search">
      <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" />
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search requests by ID, model or error…"
        className="input pl-9"
        aria-label="Search requests"
      />
    </form>
  )
}

export function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  useEffect(() => setMobileOpen(false), [location.pathname])

  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 border-r border-line/70 bg-bg-2/80 backdrop-blur lg:block">
        <Sidebar />
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 animate-fade-in bg-black/60" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 animate-slide-in border-r border-line bg-bg-2">
            <button
              className="absolute top-4 right-3 rounded-md p-1.5 text-muted hover:bg-surface-2"
              onClick={() => setMobileOpen(false)}
              aria-label="Close menu"
            >
              <X className="size-4" />
            </button>
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line/70 bg-bg/80 px-4 backdrop-blur sm:px-6">
          <button
            className="rounded-md p-1.5 text-ink-2 hover:bg-surface-2 lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open menu"
          >
            <Menu className="size-5" />
          </button>
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-1">
            <Link
              to="/requests"
              className="grid size-9 place-items-center rounded-lg text-ink-2 hover:bg-surface-2 md:hidden"
              aria-label="Search requests"
            >
              <Search className="size-[18px]" />
            </Link>
            <NotificationsMenu />
            <ProfileMenu />
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

import { Activity, Coins, ShieldCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Logo } from '../components/Layout'
import { Alert, Button, TextField } from '../components/ui'
import { errorMessage } from '../lib/api'
import { useAuth } from '../lib/auth'
import { passwordIssues } from '../lib/password'

const FEATURES = [
  { icon: Activity, title: 'One gateway, three providers', text: 'Route OpenAI, Anthropic and Gemini traffic through a single monitored endpoint.' },
  { icon: Coins, title: 'Cost intelligence', text: 'Token-level cost estimates from a pricing table you control, with budgets and alerts.' },
  { icon: ShieldCheck, title: 'Private by design', text: 'Keys encrypted at rest. Prompts and responses are never stored.' },
]

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const { login, register } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const issues = mode === 'register' && password ? passwordIssues(password) : []

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (mode === 'register' && passwordIssues(password).length) {
      setError(`Password needs ${passwordIssues(password).join(' and ')}.`)
      return
    }
    setLoading(true)
    try {
      if (mode === 'login') await login(email, password)
      else await register(email, password, name)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden border-r border-line/70 bg-bg-2 p-12 lg:flex lg:flex-col">
        <div className="absolute -top-32 -right-32 size-96 rounded-full bg-accent/10 blur-3xl" />
        <div className="absolute -bottom-40 -left-24 size-96 rounded-full bg-accent-2/10 blur-3xl" />
        <Logo />
        <div className="relative my-auto max-w-md">
          <h1 className="text-3xl leading-tight font-semibold tracking-tight">
            Observability and cost control for your{' '}
            <span className="bg-gradient-to-r from-accent to-accent-2 bg-clip-text text-transparent">AI APIs</span>
          </h1>
          <p className="mt-4 text-muted">
            Monitor requests, tokens, latency, failures and spend across OpenAI, Anthropic Claude and Google Gemini — from
            one dashboard.
          </p>
          <ul className="mt-10 space-y-5">
            {FEATURES.map((f) => (
              <li key={f.title} className="flex gap-4">
                <div className="grid size-10 shrink-0 place-items-center rounded-lg border border-line bg-surface text-accent">
                  <f.icon className="size-5" />
                </div>
                <div>
                  <p className="text-sm font-medium text-ink">{f.title}</p>
                  <p className="text-sm text-muted">{f.text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          <Logo className="mb-8 lg:hidden" />
          <h2 className="text-xl font-semibold tracking-tight">{mode === 'login' ? 'Sign in' : 'Create your account'}</h2>
          <p className="mt-1 text-sm text-muted">
            {mode === 'login' ? 'Welcome back. Sign in to your workspace.' : 'Start monitoring your AI API usage in minutes.'}
          </p>
          <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
            {mode === 'register' && (
              <TextField label="Full name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={120} />
            )}
            <TextField
              label="Email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
            <TextField
              label="Password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              hint={mode === 'register' ? (issues.length ? `Needs ${issues.join(' and ')}.` : password ? 'Strong enough.' : 'At least 10 characters, mixing character types.') : undefined}
            />
            {error && <Alert tone="bad">{error}</Alert>}
            <Button type="submit" variant="primary" className="w-full" loading={loading} disabled={!email || !password}>
              {mode === 'login' ? 'Sign in' : 'Create account'}
            </Button>
          </form>
          <p className="mt-6 text-center text-sm text-muted">
            {mode === 'login' ? (
              <>
                New to ModelOps AI?{' '}
                <Link to="/register" className="text-accent hover:underline">
                  Create an account
                </Link>
              </>
            ) : (
              <>
                Already have an account?{' '}
                <Link to="/login" className="text-accent hover:underline">
                  Sign in
                </Link>
              </>
            )}
          </p>
        </div>
      </section>
    </div>
  )
}

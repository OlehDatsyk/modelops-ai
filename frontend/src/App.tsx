import { lazy, Suspense, type ReactNode } from 'react'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppLayout, Logo } from './components/Layout'
import { EmptyState, LoadingBlock } from './components/ui'
import { useAuth } from './lib/auth'
import { AuthPage } from './pages/Auth'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Requests = lazy(() => import('./pages/Requests'))
const Costs = lazy(() => import('./pages/Costs'))
const Analyst = lazy(() => import('./pages/Analyst'))
const Projects = lazy(() => import('./pages/Projects'))
const ProjectDetail = lazy(() => import('./pages/ProjectDetail'))
const Providers = lazy(() => import('./pages/Providers'))
const Alerts = lazy(() => import('./pages/Alerts'))
const Gateway = lazy(() => import('./pages/Gateway'))
const Settings = lazy(() => import('./pages/Settings'))

function FullScreenLoader() {
  return (
    <div className="grid min-h-full place-items-center">
      <div className="flex flex-col items-center gap-4">
        <Logo />
        <LoadingBlock label="Restoring your session…" className="py-0" />
      </div>
    </div>
  )
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <FullScreenLoader />
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  return <>{children}</>
}

function PublicOnly({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <FullScreenLoader />
  if (status === 'authenticated') {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from && from !== '/login' ? from : '/'} replace />
  }
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<PublicOnly><AuthPage mode="login" /></PublicOnly>} />
      <Route path="/register" element={<PublicOnly><AuthPage mode="register" /></PublicOnly>} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        {(
          [
            ['/', Dashboard],
            ['/requests', Requests],
            ['/costs', Costs],
            ['/analyst', Analyst],
            ['/projects', Projects],
            ['/projects/:projectId', ProjectDetail],
            ['/providers', Providers],
            ['/alerts', Alerts],
            ['/gateway', Gateway],
            ['/settings', Settings],
          ] as const
        ).map(([path, Page]) => (
          <Route
            key={path}
            path={path}
            element={
              <Suspense fallback={<LoadingBlock />}>
                <Page />
              </Suspense>
            }
          />
        ))}
        <Route
          path="*"
          element={
            <EmptyState
              title="Page not found"
              description="The page you are looking for does not exist."
              action={<Link className="text-sm text-accent hover:underline" to="/">Back to dashboard</Link>}
            />
          }
        />
      </Route>
    </Routes>
  )
}

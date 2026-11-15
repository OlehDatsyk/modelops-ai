import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, refreshAccessToken, setAccessToken, setSessionExpiredHandler } from './api'
import type { TokenResponse, User } from './types'

type Status = 'loading' | 'authenticated' | 'anonymous'

interface AuthContextValue {
  status: Status
  user: User | null
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, fullName: string) => Promise<void>
  logout: () => Promise<void>
  setUser: (user: User) => void
  clearSession: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [user, setUserState] = useState<User | null>(null)
  const queryClient = useQueryClient()

  const clearSession = useCallback(() => {
    setAccessToken(null)
    setUserState(null)
    setStatus('anonymous')
    queryClient.clear()
  }, [queryClient])

  const accept = useCallback((data: TokenResponse) => {
    setAccessToken(data.access_token)
    setUserState(data.user)
    setStatus('authenticated')
  }, [])

  // Restore the session from the httpOnly refresh cookie on first load.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const token = await refreshAccessToken()
      if (cancelled) return
      if (!token) {
        setStatus('anonymous')
        return
      }
      try {
        const me = await api<User>('/auth/me')
        if (!cancelled) {
          setUserState(me)
          setStatus('authenticated')
        }
      } catch {
        if (!cancelled) setStatus('anonymous')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    setSessionExpiredHandler(clearSession)
    return () => setSessionExpiredHandler(null)
  }, [clearSession])

  const login = useCallback(
    async (email: string, password: string) => {
      accept(await api<TokenResponse>('/auth/login', { method: 'POST', body: { email, password }, auth: false }))
    },
    [accept],
  )

  const register = useCallback(
    async (email: string, password: string, fullName: string) => {
      accept(
        await api<TokenResponse>('/auth/register', {
          method: 'POST',
          body: { email, password, full_name: fullName },
          auth: false,
        }),
      )
    },
    [accept],
  )

  const logout = useCallback(async () => {
    try {
      await api('/auth/logout', { method: 'POST', auth: false })
    } finally {
      clearSession()
    }
  }, [clearSession])

  const value = useMemo(
    () => ({ status, user, login, register, logout, setUser: setUserState, clearSession }),
    [status, user, login, register, logout, clearSession],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

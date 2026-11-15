/**
 * API client. The access token lives in memory only; the refresh token is an httpOnly cookie
 * scoped to /api/v1/auth, so JavaScript never sees it. On a 401 the client refreshes once and retries.
 */

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''

export class ApiError extends Error {
  status: number
  code: string
  requestId?: string
  details?: { loc: string[]; msg: string }[]

  constructor(status: number, code: string, message: string, requestId?: string, details?: ApiError['details']) {
    super(message)
    this.status = status
    this.code = code
    this.requestId = requestId
    this.details = details
  }
}

type Query = Record<string, string | number | boolean | null | undefined>

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  query?: Query
  auth?: boolean
  signal?: AbortSignal
}

let accessToken: string | null = null
let refreshing: Promise<string | null> | null = null
let onSessionExpired: (() => void) | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function getAccessToken() {
  return accessToken
}

export function setSessionExpiredHandler(handler: (() => void) | null) {
  onSessionExpired = handler
}

export function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return `${API_BASE}/api/v1${path}${qs ? `?${qs}` : ''}`
}

async function parseError(res: Response): Promise<ApiError> {
  let body: { error?: { code?: string; message?: string; request_id?: string; details?: ApiError['details'] } } = {}
  try {
    body = await res.json()
  } catch {
    /* non-JSON error body */
  }
  const err = body.error ?? {}
  const fallback = res.status >= 500 ? 'The server encountered an error. Please try again.' : `Request failed (${res.status})`
  return new ApiError(res.status, err.code ?? 'http_error', err.message ?? fallback, err.request_id, err.details)
}

/** Refresh the access token using the httpOnly cookie. Concurrent callers share one request. */
export function refreshAccessToken(): Promise<string | null> {
  if (!refreshing) {
    refreshing = fetch(buildUrl('/auth/refresh'), { method: 'POST', credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) return null
        const data = (await res.json()) as { access_token: string }
        accessToken = data.access_token
        return accessToken
      })
      .catch(() => null)
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

export async function api<T>(path: string, opts: RequestOptions = {}, retried = false): Promise<T> {
  const { method = 'GET', body, query, auth = true, signal } = opts
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (auth && accessToken) headers.Authorization = `Bearer ${accessToken}`

  let res: Response
  try {
    res = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: 'include',
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, 'network_error', 'Cannot reach the server. Check your connection and try again.')
  }

  if (res.status === 401 && auth && !retried) {
    const token = await refreshAccessToken()
    if (token) return api<T>(path, opts, true)
    accessToken = null
    onSessionExpired?.()
  }
  if (!res.ok) throw await parseError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.details?.length) return error.details.map((d) => `${d.loc.slice(-1)[0]}: ${d.msg}`).join('; ')
    return error.message
  }
  if (error instanceof Error) return error.message
  return 'Something went wrong'
}

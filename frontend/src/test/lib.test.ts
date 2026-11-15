import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, buildUrl, errorMessage, getAccessToken, setAccessToken, setSessionExpiredHandler } from '../lib/api'
import { formatMs, formatNumber, formatRelative, formatUsd, percentChange } from '../lib/format'
import { isValidCustomRange, rangeToQuery } from '../lib/range'
import { passwordIssues } from '../lib/password'

describe('format', () => {
  it('formats currency with precision for tiny values and placeholders for unknown', () => {
    expect(formatUsd(0)).toBe('$0.00')
    expect(formatUsd(12.345)).toBe('$12.35')
    expect(formatUsd('0.00045')).toBe('$0.0005')
    expect(formatUsd(0.0000123)).toBe('$0.000012')
    expect(formatUsd(null)).toBe('—')
    expect(formatUsd('not-a-number')).toBe('—')
  })

  it('formats durations, numbers and changes', () => {
    expect(formatMs(250)).toBe('250 ms')
    expect(formatMs(1500)).toBe('1.50 s')
    expect(formatMs(null)).toBe('—')
    expect(formatNumber(1234567)).toBe('1,234,567')
    expect(percentChange(150, 100)).toBe(50)
    expect(percentChange(5, 0)).toBeNull()
  })

  it('formats relative times', () => {
    const now = new Date('2026-01-01T12:00:00Z')
    expect(formatRelative('2026-01-01T11:59:50Z', now)).toBe('just now')
    expect(formatRelative('2026-01-01T11:30:00Z', now)).toBe('30 min ago')
    expect(formatRelative('2026-01-01T09:00:00Z', now)).toBe('3 h ago')
    expect(formatRelative(null, now)).toBe('never')
  })
})

describe('range', () => {
  it('passes presets through and converts custom dates to an inclusive ISO range', () => {
    expect(rangeToQuery({ range: '7d' })).toEqual({ range: '7d' })
    const q = rangeToQuery({ range: 'custom', start: '2026-03-01', end: '2026-03-03' })
    expect(q.range).toBe('custom')
    const days = (new Date(q.end!).getTime() - new Date(q.start!).getTime()) / 86_400_000
    expect(Math.round(days)).toBe(3)
    expect(rangeToQuery({ range: 'custom' })).toEqual({ range: '30d' })
  })

  it('validates custom ranges', () => {
    expect(isValidCustomRange('2026-03-01', '2026-03-02')).toBe(true)
    expect(isValidCustomRange('2026-03-02', '2026-03-01')).toBe(false)
    expect(isValidCustomRange('2025-01-01', '2026-06-01')).toBe(false)
    expect(isValidCustomRange(undefined, '2026-03-01')).toBe(false)
  })
})

describe('password rules', () => {
  it('mirrors the backend policy', () => {
    expect(passwordIssues('short')).toHaveLength(2)
    expect(passwordIssues('alllowercaseletters')).toEqual(['three of: lowercase, uppercase, digit, symbol'])
    expect(passwordIssues('Good-Passw0rd')).toEqual([])
  })
})

describe('api client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    setAccessToken(null)
    setSessionExpiredHandler(null)
  })

  const json = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  it('builds URLs and skips empty query values', () => {
    expect(buildUrl('/requests', { q: 'abc', provider: '', page: 2, model: undefined })).toBe('/api/v1/requests?q=abc&page=2')
  })

  it('sends the bearer token and returns JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    setAccessToken('tok-1')
    await expect(api('/projects')).resolves.toEqual({ ok: true })
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer tok-1')
    expect(fetchMock.mock.calls[0][1].credentials).toBe('include')
  })

  it('refreshes once on 401 and retries with the new token', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401, { error: { code: 'invalid_token', message: 'expired' } }))
      .mockResolvedValueOnce(json(200, { access_token: 'tok-2' }))
      .mockResolvedValueOnce(json(200, { items: [] }))
    vi.stubGlobal('fetch', fetchMock)
    setAccessToken('tok-old')
    await expect(api('/projects')).resolves.toEqual({ items: [] })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/auth/refresh')
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe('Bearer tok-2')
    expect(getAccessToken()).toBe('tok-2')
  })

  it('signals session expiry when refresh fails and surfaces structured errors', async () => {
    const expired = vi.fn()
    setSessionExpiredHandler(expired)
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401, { error: { code: 'invalid_token', message: 'expired', request_id: 'req_1' } }))
      .mockResolvedValueOnce(json(401, { error: { code: 'no_session', message: 'No active session' } }))
    vi.stubGlobal('fetch', fetchMock)
    const err = (await api('/projects').catch((e) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(401)
    expect(err.requestId).toBe('req_1')
    expect(expired).toHaveBeenCalledOnce()
  })

  it('maps network failures and validation details to readable messages', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const err = (await api('/projects').catch((e) => e)) as ApiError
    expect(err.code).toBe('network_error')
    const validation = new ApiError(422, 'validation_error', 'Invalid request', undefined, [
      { loc: ['body', 'name'], msg: 'Field required' },
    ])
    expect(errorMessage(validation)).toBe('name: Field required')
  })
})

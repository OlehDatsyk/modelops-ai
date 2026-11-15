import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { RangeKey, RangeValue } from './range'

const RANGE_KEYS: RangeKey[] = ['24h', '7d', '30d', '90d', 'custom']

/** Range + project/provider filters stored in the URL so views are shareable and survive reloads. */
export function useFilters(defaultRange: RangeKey = '7d') {
  const [params, setParams] = useSearchParams()

  const range: RangeValue = useMemo(() => {
    const key = params.get('range') as RangeKey | null
    const r = key && RANGE_KEYS.includes(key) ? key : defaultRange
    return r === 'custom'
      ? { range: r, start: params.get('start') ?? undefined, end: params.get('end') ?? undefined }
      : { range: r }
  }, [params, defaultRange])

  const update = useCallback(
    (changes: Record<string, string | undefined>) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          for (const [k, v] of Object.entries(changes)) {
            if (v) next.set(k, v)
            else next.delete(k)
          }
          return next
        },
        { replace: true },
      )
    },
    [setParams],
  )

  const setRange = useCallback(
    (v: RangeValue) => update({ range: v.range, start: v.start, end: v.end, page: undefined }),
    [update],
  )

  return {
    params,
    range,
    setRange,
    projectId: params.get('project_id') ?? '',
    provider: params.get('provider') ?? '',
    setProjectId: (id: string) => update({ project_id: id, page: undefined }),
    setProvider: (p: string) => update({ provider: p, page: undefined }),
    update,
  }
}

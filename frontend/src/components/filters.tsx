import clsx from 'clsx'
import { CalendarRange } from 'lucide-react'
import { useState } from 'react'
import { PROVIDER_LABEL } from '../lib/format'
import { RANGE_OPTIONS, isValidCustomRange, todayIso, type RangeValue } from '../lib/range'
import { useProjects } from '../lib/queries'
import { PROVIDERS } from '../lib/types'
import { Button } from './ui'

export function RangePicker({ value, onChange }: { value: RangeValue; onChange: (v: RangeValue) => void }) {
  const [draft, setDraft] = useState({ start: value.start ?? todayIso(-13), end: value.end ?? todayIso() })
  const [open, setOpen] = useState(false)
  const valid = isValidCustomRange(draft.start, draft.end)

  return (
    <div className="relative">
      <div className="inline-flex rounded-lg border border-line bg-bg-2 p-0.5" role="group" aria-label="Date range">
        {RANGE_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            onClick={() => (opt.key === 'custom' ? setOpen((o) => !o) : (setOpen(false), onChange({ range: opt.key })))}
            className={clsx(
              'flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors sm:px-3',
              value.range === opt.key ? 'bg-surface-3 text-ink shadow-sm' : 'text-muted hover:text-ink',
            )}
            aria-pressed={value.range === opt.key}
          >
            {opt.key === 'custom' && <CalendarRange className="size-3.5" />}
            {opt.key === 'custom' && value.range === 'custom' && value.start
              ? `${value.start} → ${value.end}`
              : opt.label}
          </button>
        ))}
      </div>
      {open && (
        <div className="card absolute right-0 z-30 mt-2 w-72 animate-slide-up bg-surface p-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="range-start">
                From
              </label>
              <input
                id="range-start"
                type="date"
                className="input px-2"
                value={draft.start}
                max={draft.end}
                onChange={(e) => setDraft((d) => ({ ...d, start: e.target.value }))}
              />
            </div>
            <div>
              <label className="label" htmlFor="range-end">
                To
              </label>
              <input
                id="range-end"
                type="date"
                className="input px-2"
                value={draft.end}
                min={draft.start}
                max={todayIso()}
                onChange={(e) => setDraft((d) => ({ ...d, end: e.target.value }))}
              />
            </div>
          </div>
          {!valid && <p className="mt-2 text-xs text-bad">Choose a valid range of up to 366 days.</p>}
          <div className="mt-4 flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="primary"
              disabled={!valid}
              onClick={() => {
                onChange({ range: 'custom', ...draft })
                setOpen(false)
              }}
            >
              Apply
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export function ProjectSelect({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const { data } = useProjects()
  return (
    <select
      aria-label="Project"
      className="input h-9 w-auto max-w-[12rem] appearance-none pr-8"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">All projects</option>
      {data?.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  )
}

export function ProviderSelect({ value, onChange }: { value: string; onChange: (p: string) => void }) {
  return (
    <select
      aria-label="Provider"
      className="input h-9 w-auto appearance-none pr-8"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">All providers</option>
      {PROVIDERS.map((p) => (
        <option key={p} value={p}>
          {PROVIDER_LABEL[p]}
        </option>
      ))}
    </select>
  )
}

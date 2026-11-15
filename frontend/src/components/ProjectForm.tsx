import { useState, type FormEvent } from 'react'
import { errorMessage } from '../lib/api'
import { PROVIDER_LABEL } from '../lib/format'
import { PROVIDERS, type Provider } from '../lib/types'
import { Alert, Button, Modal, TextField } from './ui'

export interface ProjectFormValues {
  name: string
  description: string
  allowed_providers: Provider[]
}

export function ProjectFormModal({
  open,
  onClose,
  onSubmit,
  initial,
  title,
  submitLabel,
}: {
  open: boolean
  onClose: () => void
  onSubmit: (v: ProjectFormValues) => Promise<unknown>
  initial?: ProjectFormValues
  title: string
  submitLabel: string
}) {
  const [values, setValues] = useState<ProjectFormValues>(initial ?? { name: '', description: '', allowed_providers: [...PROVIDERS] })
  const [error, setError] = useState<unknown>(null)
  const [saving, setSaving] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      await onSubmit({ ...values, name: values.name.trim() })
      onClose()
    } catch (err) {
      setError(err)
    } finally {
      setSaving(false)
    }
  }

  const toggle = (p: Provider) =>
    setValues((v) => ({
      ...v,
      allowed_providers: v.allowed_providers.includes(p) ? v.allowed_providers.filter((x) => x !== p) : [...v.allowed_providers, p],
    }))

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="project-form" loading={saving} disabled={!values.name.trim()}>
            {submitLabel}
          </Button>
        </>
      }
    >
      <form id="project-form" onSubmit={submit} className="space-y-4">
        <TextField label="Name" required maxLength={100} value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} placeholder="e.g. Customer Support AI" />
        <div>
          <label className="label" htmlFor="project-description">Description</label>
          <textarea
            id="project-description"
            className="input h-auto min-h-20 py-2"
            maxLength={2000}
            value={values.description}
            onChange={(e) => setValues({ ...values, description: e.target.value })}
            placeholder="What does this application do?"
          />
        </div>
        <fieldset>
          <legend className="label">Allowed providers</legend>
          <div className="flex flex-wrap gap-2">
            {PROVIDERS.map((p) => (
              <label key={p} className="flex cursor-pointer items-center gap-2 rounded-lg border border-line bg-bg-2 px-3 py-2 text-sm has-[:checked]:border-accent/60 has-[:checked]:bg-accent/10">
                <input type="checkbox" className="accent-[#4f8cff]" checked={values.allowed_providers.includes(p)} onChange={() => toggle(p)} />
                {PROVIDER_LABEL[p]}
              </label>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-muted">Gateway requests to other providers are rejected for this project.</p>
        </fieldset>
        {error ? <Alert tone="bad">{errorMessage(error)}</Alert> : null}
      </form>
    </Modal>
  )
}

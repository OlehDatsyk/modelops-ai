import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { StatCard } from '../components/StatCard'
import { ConfirmDialog, EmptyState, ProgressBar } from '../components/ui'

describe('StatCard', () => {
  it('shows a cost increase as bad (inverted metric)', () => {
    render(<StatCard label="Estimated spend" value="$15.00" current={15} previous={10} invert />)
    const change = screen.getByText('50.0%')
    expect(change.className).toContain('text-bad')
  })

  it('shows request growth as good and handles a zero baseline', () => {
    const { rerender } = render(<StatCard label="Requests" value="20" current={20} previous={10} />)
    expect(screen.getByText('100.0%').className).toContain('text-ok')
    rerender(<StatCard label="Requests" value="5" current={5} previous={0} />)
    expect(screen.getByText('new this period')).toBeInTheDocument()
  })
})

describe('ui primitives', () => {
  it('renders empty states with actions', () => {
    render(<EmptyState title="No projects yet" description="Create one" action={<button>Create</button>} />)
    expect(screen.getByRole('heading', { name: 'No projects yet' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create' })).toBeInTheDocument()
  })

  it('caps progress bars at 100% and colours by level', () => {
    const { container } = render(<ProgressBar value={140} />)
    const bar = container.querySelector('[style]') as HTMLElement
    expect(bar.style.width).toBe('100%')
    expect(bar.className).toContain('bg-bad')
  })

  it('confirm dialog calls handlers and closes on Escape', () => {
    const onConfirm = vi.fn()
    const onClose = vi.fn()
    render(<ConfirmDialog open onClose={onClose} onConfirm={onConfirm} title="Delete?" message="Sure?" confirmLabel="Delete it" />)
    fireEvent.click(screen.getByRole('button', { name: 'Delete it' }))
    expect(onConfirm).toHaveBeenCalledOnce()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })
})

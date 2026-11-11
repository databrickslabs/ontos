import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SizeToggle } from './size-toggle'

const twoOptions = [
  { value: 'small', label: 'S', title: 'Small View' },
  { value: 'large', label: 'L', title: 'Large View' },
] as const

const threeOptions = [
  { value: 'small', label: 'S', title: 'Small View' },
  { value: 'medium', label: 'M', title: 'Medium View' },
  { value: 'large', label: 'L', title: 'Large View' },
] as const

describe('SizeToggle', () => {
  it('renders two options in a labelled group with the compact styling', () => {
    render(
      <SizeToggle
        options={[...twoOptions]}
        value="small"
        onChange={() => {}}
        aria-label="View size"
      />
    )
    const group = screen.getByRole('group', { name: 'View size' })
    expect(group).toHaveClass('inline-flex', 'h-8', 'border', 'rounded-md')
    const small = screen.getByRole('button', { name: 'Small View' })
    const large = screen.getByRole('button', { name: 'Large View' })
    expect(small).toHaveTextContent('S')
    expect(large).toHaveTextContent('L')
    expect(small).toHaveAttribute('title', 'Small View')
    for (const btn of [small, large]) {
      expect(btn).toHaveClass('h-full', 'w-8', 'p-0', 'text-xs', 'rounded-none')
    }
  })

  it('marks only the active option as pressed', () => {
    render(<SizeToggle options={[...twoOptions]} value="large" onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'Large View' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Small View' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'Large View' })).toHaveClass('bg-primary')
    expect(screen.getByRole('button', { name: 'Small View' })).not.toHaveClass('bg-primary')
  })

  it('supports three options and calls onChange with the clicked value', () => {
    const onChange = vi.fn()
    render(<SizeToggle options={[...threeOptions]} value="small" onChange={onChange} />)
    expect(screen.getAllByRole('button')).toHaveLength(3)
    fireEvent.click(screen.getByRole('button', { name: 'Medium View' }))
    expect(onChange).toHaveBeenCalledWith('medium')
    fireEvent.click(screen.getByRole('button', { name: 'Large View' }))
    expect(onChange).toHaveBeenLastCalledWith('large')
  })

  it('does not render tab roles', () => {
    render(<SizeToggle options={[...twoOptions]} value="small" onChange={() => {}} />)
    expect(screen.queryAllByRole('tab')).toHaveLength(0)
  })
})

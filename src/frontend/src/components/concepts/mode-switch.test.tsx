import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, defaultValue?: string) => defaultValue || key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

import { ConceptModeSwitch } from './mode-switch'

describe('ConceptModeSwitch', () => {
  it('renders a compact S | L toggle instead of the wide Simple/Advanced tabs', () => {
    render(<ConceptModeSwitch tipLeft />)
    const group = screen.getByRole('group', { name: 'View mode' })
    expect(group).toHaveClass('h-8')
    const small = screen.getByRole('button', { name: 'Small View' })
    const large = screen.getByRole('button', { name: /^Large View: Advanced view reveals/ })
    expect(small).toHaveTextContent('S')
    expect(large).toHaveTextContent('L')
    expect(small).toHaveClass('w-8', 'text-xs')
    // The old wide tabs, their labels and the info tooltip trigger are gone.
    expect(screen.queryAllByRole('tab')).toHaveLength(0)
    expect(screen.queryByText('Simple')).not.toBeInTheDocument()
    expect(screen.queryByText('Advanced view')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Advanced view reveals the ontology layer' })
    ).not.toBeInTheDocument()
  })

  it('toggles the mode, persists it and reflects it on the document', () => {
    render(<ConceptModeSwitch />)
    const small = screen.getByRole('button', { name: 'Small View' })
    const large = screen.getByRole('button', { name: /^Large View/ })
    fireEvent.click(large)
    expect(large).toHaveAttribute('aria-pressed', 'true')
    expect(small).toHaveAttribute('aria-pressed', 'false')
    expect(document.documentElement.getAttribute('data-mode')).toBe('advanced')
    expect(localStorage.getItem('ontosConceptMode')).toBe('advanced')
    fireEvent.click(small)
    expect(small).toHaveAttribute('aria-pressed', 'true')
    expect(document.documentElement.getAttribute('data-mode')).toBe('simple')
    expect(localStorage.getItem('ontosConceptMode')).toBe('simple')
  })

  it('keeps every rendered instance in sync through the shared store', () => {
    render(
      <>
        <ConceptModeSwitch />
        <ConceptModeSwitch />
      </>
    )
    fireEvent.click(screen.getAllByRole('button', { name: /^Large View/ })[0])
    for (const btn of screen.getAllByRole('button', { name: /^Large View/ })) {
      expect(btn).toHaveAttribute('aria-pressed', 'true')
    }
    // Reset the shared module-level store so later tests start in simple mode.
    fireEvent.click(screen.getAllByRole('button', { name: 'Small View' })[1])
    expect(screen.getAllByRole('button', { name: 'Small View' })[0]).toHaveAttribute('aria-pressed', 'true')
  })
})

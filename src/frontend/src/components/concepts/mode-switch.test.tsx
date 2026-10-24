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
  it('renders larger tab buttons and an aligned info trigger', () => {
    render(<ConceptModeSwitch />)
    const simple = screen.getByRole('tab', { name: 'Simple' })
    const advanced = screen.getByRole('tab', { name: 'Advanced view' })
    for (const tab of [simple, advanced]) {
      expect(tab).toHaveClass('text-sm', 'px-4', 'py-2')
    }
    const info = screen.getByRole('button', { name: 'Advanced view reveals the ontology layer' })
    expect(info).toHaveClass('h-5', 'w-5')
  })

  it('toggles the mode and reflects it on the document', () => {
    render(<ConceptModeSwitch />)
    fireEvent.click(screen.getByRole('tab', { name: 'Advanced view' }))
    expect(screen.getByRole('tab', { name: 'Advanced view' })).toHaveAttribute('aria-selected', 'true')
    expect(document.documentElement.getAttribute('data-mode')).toBe('advanced')
    fireEvent.click(screen.getByRole('tab', { name: 'Simple' }))
    expect(document.documentElement.getAttribute('data-mode')).toBe('simple')
  })
})

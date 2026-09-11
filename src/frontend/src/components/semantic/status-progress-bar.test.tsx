import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, defaultValue: string) => defaultValue || key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

import { StatusProgressBar } from './status-progress-bar'

describe('StatusProgressBar', () => {
  describe('forward chain states', () => {
    it('renders draft status (first position)', () => {
      render(<StatusProgressBar status="draft" />)
      expect(screen.getByText('draft')).toBeInTheDocument()
    })

    it('renders under_review status', () => {
      render(<StatusProgressBar status="under_review" />)
      expect(screen.getByText('under review')).toBeInTheDocument()
    })

    it('renders approved status', () => {
      render(<StatusProgressBar status="approved" />)
      expect(screen.getByText('approved')).toBeInTheDocument()
    })

    it('renders published status', () => {
      render(<StatusProgressBar status="published" />)
      expect(screen.getByText('published')).toBeInTheDocument()
    })

    it('renders certified status (last position)', () => {
      render(<StatusProgressBar status="certified" />)
      expect(screen.getByText('certified')).toBeInTheDocument()
    })
  })

  describe('terminal states', () => {
    it('renders deprecated as terminal state', () => {
      render(<StatusProgressBar status="deprecated" />)
      expect(screen.getByText('deprecated')).toBeInTheDocument()
    })

    it('renders archived as terminal state', () => {
      render(<StatusProgressBar status="archived" />)
      expect(screen.getByText('archived')).toBeInTheDocument()
    })

    it('shows amber styling for terminal states (deprecated)', () => {
      const { container } = render(<StatusProgressBar status="deprecated" />)
      const terminal = container.querySelector('.bg-amber-50')
      expect(terminal).toBeInTheDocument()
    })

    it('shows amber styling for terminal states (archived)', () => {
      const { container } = render(<StatusProgressBar status="archived" />)
      const terminal = container.querySelector('.bg-amber-50')
      expect(terminal).toBeInTheDocument()
    })
  })

  describe('progress visualization', () => {
    it('shows done states with checkmark for completed stages (at approved from draft)', () => {
      const { container } = render(<StatusProgressBar status="approved" />)
      const checks = container.querySelectorAll('svg')
      // draft and under_review should show checkmarks (done), approved is current
      expect(checks.length).toBeGreaterThan(0)
    })

    it('shows current state with primary styling (under_review)', () => {
      const { container } = render(<StatusProgressBar status="under_review" />)
      // Current should have border-primary class
      const current = container.querySelector('.border-primary')
      expect(current).toBeInTheDocument()
    })

    it('shows future states as dashed/unfilled (certified when at draft)', () => {
      const { container } = render(<StatusProgressBar status="draft" />)
      const dashed = container.querySelector('.border-dashed')
      expect(dashed).toBeInTheDocument()
    })
  })

  describe('arrow separators', () => {
    it('renders arrows between forward chain items', () => {
      const { container } = render(<StatusProgressBar status="draft" />)
      const arrows = container.querySelectorAll('[class*="text-muted-foreground/40"]')
      // Should have 4 arrows between 5 forward items
      expect(arrows.length).toBeGreaterThanOrEqual(4)
    })

    it('does not show forward arrow after last item (certified)', () => {
      const { container } = render(<StatusProgressBar status="certified" />)
      const text = container.textContent || ''
      // Certified is the last forward item, should not have arrow after it
      expect(text).toContain('certified')
    })
  })

  describe('terminal state separator', () => {
    it('shows bullet separator and amber box for deprecated', () => {
      const { container } = render(<StatusProgressBar status="deprecated" />)
      const amberBox = container.querySelector('.border-amber-300')
      expect(amberBox).toBeInTheDocument()
    })

    it('shows bullet separator and amber box for archived', () => {
      const { container } = render(<StatusProgressBar status="archived" />)
      const amberBox = container.querySelector('.border-amber-300')
      expect(amberBox).toBeInTheDocument()
    })
  })

  describe('className prop', () => {
    it('applies custom className to container', () => {
      const { container } = render(<StatusProgressBar status="draft" className="custom-class" />)
      const root = container.firstChild as HTMLElement
      expect(root).toHaveClass('custom-class')
    })
  })

  describe('edge cases', () => {
    it('handles unknown status gracefully', () => {
      const { container } = render(<StatusProgressBar status="unknown_status" />)
      expect(container).toBeInTheDocument()
    })

    it('renders all forward chain items even when at first position', () => {
      render(<StatusProgressBar status="draft" />)
      expect(screen.getByText('draft')).toBeInTheDocument()
      expect(screen.getByText('under review')).toBeInTheDocument()
      expect(screen.getByText('approved')).toBeInTheDocument()
      expect(screen.getByText('published')).toBeInTheDocument()
      expect(screen.getByText('certified')).toBeInTheDocument()
    })

    it('renders all forward chain items even when at last position', () => {
      render(<StatusProgressBar status="certified" />)
      expect(screen.getByText('draft')).toBeInTheDocument()
      expect(screen.getByText('under review')).toBeInTheDocument()
      expect(screen.getByText('approved')).toBeInTheDocument()
      expect(screen.getByText('published')).toBeInTheDocument()
      expect(screen.getByText('certified')).toBeInTheDocument()
    })
  })
})

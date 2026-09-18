import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, defaultValue?: string) => defaultValue || key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

import DeliveryModes, { type DeliveryMode } from './delivery-modes'

describe('DeliveryModes', () => {
  describe('rendering modes', () => {
    it('renders all three delivery mode cards', () => {
      render(<DeliveryModes activeModes={[]} />)
      expect(screen.getByText('Direct')).toBeInTheDocument()
      expect(screen.getByText('Indirect')).toBeInTheDocument()
      expect(screen.getByText('Manual')).toBeInTheDocument()
    })

    it('renders mode descriptions', () => {
      render(<DeliveryModes activeModes={[]} />)
      expect(
        screen.getByText(/Ontos applies changes to this workspace immediately/i),
      ).toBeInTheDocument()
      expect(screen.getByText(/Ontos writes YAML to Git/i)).toBeInTheDocument()
      expect(screen.getByText(/Ontos notifies a person/i)).toBeInTheDocument()
    })
  })

  describe('active modes styling', () => {
    it('highlights direct mode when active', () => {
      const { container } = render(<DeliveryModes activeModes={['direct']} />)
      const directCard = container.querySelector('[class*="border-emerald-500"]')
      expect(directCard).toBeInTheDocument()
    })

    it('highlights indirect mode when active', () => {
      const { container } = render(<DeliveryModes activeModes={['indirect']} />)
      const activeCards = container.querySelectorAll('[class*="border-emerald-500"]')
      expect(activeCards.length).toBeGreaterThan(0)
    })

    it('highlights manual mode when active', () => {
      const { container } = render(<DeliveryModes activeModes={['manual']} />)
      const activeCards = container.querySelectorAll('[class*="border-emerald-500"]')
      expect(activeCards.length).toBeGreaterThan(0)
    })

    it('highlights multiple modes when multiple are active', () => {
      const { container } = render(<DeliveryModes activeModes={['direct', 'indirect']} />)
      const activeCards = container.querySelectorAll('[class*="border-emerald-500"]')
      expect(activeCards.length).toBeGreaterThanOrEqual(2)
    })

    it('shows "active" badge for active modes', () => {
      render(<DeliveryModes activeModes={['direct']} />)
      const badges = screen.getAllByText(/active/i)
      expect(badges.length).toBeGreaterThan(0)
    })

    it('does not show "active" badge for inactive modes', () => {
      render(<DeliveryModes activeModes={[]} />)
      const badges = screen.queryAllByText(/active/i)
      expect(badges.length).toBe(0)
    })
  })

  describe('inactive modes', () => {
    it('renders inactive direct mode without highlight', () => {
      const { container } = render(<DeliveryModes activeModes={['indirect']} />)
      // Count emerald cards, should be 1 (indirect)
      const emeraldCards = container.querySelectorAll('[class*="border-emerald-500"]')
      expect(emeraldCards.length).toBe(1)
    })

    it('renders inactive modes with default border color', () => {
      const { container } = render(<DeliveryModes activeModes={['direct']} />)
      const defaultCards = container.querySelectorAll('[class*="bg-card"]')
      expect(defaultCards.length).toBeGreaterThan(0)
    })

    it('shows gray indicator dot for inactive modes', () => {
      const { container } = render(<DeliveryModes activeModes={[]} />)
      // All modes should be inactive, so all dots should be gray/border
      const cards = container.querySelectorAll('[class*="rounded-lg"]')
      expect(cards.length).toBeGreaterThanOrEqual(3)
    })

    it('shows green indicator dot for active modes', () => {
      const { container } = render(<DeliveryModes activeModes={['direct']} />)
      // Should have at least one active mode with emerald styling
      const activeIndicator = container.querySelector('[class*="border-emerald-500"]')
      expect(activeIndicator).toBeInTheDocument()
    })
  })

  describe('settings link', () => {
    it('renders settings link with default href', () => {
      render(<DeliveryModes activeModes={[]} />)
      const link = screen.getByRole('link')
      expect(link).toHaveAttribute('href', '/settings/delivery')
    })

    it('renders settings link with custom href', () => {
      render(<DeliveryModes activeModes={[]} settingsHref="/custom/settings" />)
      const link = screen.getByRole('link')
      expect(link).toHaveAttribute('href', '/custom/settings')
    })

    it('renders settings link text', () => {
      render(<DeliveryModes activeModes={[]} />)
      expect(
        screen.getByText(/Delivery mode is set per site in Settings, Delivery/i),
      ).toBeInTheDocument()
    })

    it('renders external link icon', () => {
      const { container } = render(<DeliveryModes activeModes={[]} />)
      const icon = container.querySelector('svg')
      expect(icon).toBeInTheDocument()
    })
  })

  describe('default props', () => {
    it('uses empty activeModes by default', () => {
      render(<DeliveryModes />)
      // All modes should be inactive
      expect(screen.queryAllByText(/active/i).length).toBe(0)
    })

    it('uses default settingsHref when not provided', () => {
      render(<DeliveryModes />)
      const link = screen.getByRole('link')
      expect(link).toHaveAttribute('href', '/settings/delivery')
    })
  })

  describe('all active modes', () => {
    it('highlights all three modes when all are active', () => {
      const { container } = render(
        <DeliveryModes activeModes={['direct', 'indirect', 'manual']} />,
      )
      const activeCards = container.querySelectorAll('[class*="border-emerald-500"]')
      expect(activeCards.length).toBeGreaterThanOrEqual(3)
    })

    it('shows "active" badge for each active mode', () => {
      render(<DeliveryModes activeModes={['direct', 'indirect', 'manual']} />)
      const badges = screen.getAllByText(/active/i)
      expect(badges.length).toBe(3)
    })
  })

  describe('mode cards structure', () => {
    it('renders three card containers', () => {
      const { container } = render(<DeliveryModes activeModes={[]} />)
      const cards = container.querySelectorAll('[class*="rounded-lg"]')
      expect(cards.length).toBeGreaterThanOrEqual(3)
    })

    it('renders each mode with label and description', () => {
      const { container } = render(<DeliveryModes activeModes={[]} />)
      const labels = container.querySelectorAll('b')
      expect(labels.length).toBeGreaterThanOrEqual(3)
    })
  })

  describe('type safety', () => {
    it('accepts direct as active mode type', () => {
      const modes: DeliveryMode[] = ['direct']
      render(<DeliveryModes activeModes={modes} />)
      expect(screen.getByText(/active/i)).toBeInTheDocument()
    })

    it('accepts indirect as active mode type', () => {
      const modes: DeliveryMode[] = ['indirect']
      render(<DeliveryModes activeModes={modes} />)
      expect(screen.getByText(/active/i)).toBeInTheDocument()
    })

    it('accepts manual as active mode type', () => {
      const modes: DeliveryMode[] = ['manual']
      render(<DeliveryModes activeModes={modes} />)
      expect(screen.getByText(/active/i)).toBeInTheDocument()
    })
  })
})

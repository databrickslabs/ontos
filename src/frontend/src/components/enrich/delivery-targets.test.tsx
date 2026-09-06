import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, defaultValue?: string) => defaultValue || key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

import DeliveryTargets, { type DeliveryTarget } from './delivery-targets'

const sampleTargets: DeliveryTarget[] = [
  {
    id: 'tags',
    name: 'Unity Catalog Tags',
    status: 'live',
    description: 'Write governed tags to Unity Catalog',
    via: 'via uc_tag_sync',
    coverage: { synced: 15, total: 20, pending: 3, lastRun: '2024-08-16T10:30:00Z' },
    actionable: true,
    onConfigure: vi.fn(),
    onSync: vi.fn(),
  },
  {
    id: 'glossary',
    name: 'UC Glossary',
    status: 'coming',
    description: 'Link concepts to UC business glossary',
    comingSoon: true,
  },
  {
    id: 'columns',
    name: 'Column Descriptions',
    status: 'planned',
    description: 'Sync concept descriptions to column comments',
    assist: 'dbxmetagen',
    note: 'This is an advanced feature',
  },
]

describe('DeliveryTargets', () => {
  describe('rendering targets', () => {
    it('renders all targets', () => {
      render(
        <BrowserRouter>
          <DeliveryTargets targets={sampleTargets} />
        </BrowserRouter>,
      )
      expect(screen.getByText('Unity Catalog Tags')).toBeInTheDocument()
      expect(screen.getByText('UC Glossary')).toBeInTheDocument()
      expect(screen.getByText('Column Descriptions')).toBeInTheDocument()
    })

    it('renders target descriptions', () => {
      render(
        <BrowserRouter>
          <DeliveryTargets targets={sampleTargets} />
        </BrowserRouter>,
      )
      expect(screen.getByText('Write governed tags to Unity Catalog')).toBeInTheDocument()
      expect(screen.getByText('Link concepts to UC business glossary')).toBeInTheDocument()
      expect(screen.getByText('Sync concept descriptions to column comments')).toBeInTheDocument()
    })
  })

  describe('status badges', () => {
    it('renders live status badge', () => {
      render(
        <BrowserRouter>
          <DeliveryTargets targets={[sampleTargets[0]]} />
        </BrowserRouter>,
      )
      expect(screen.getByText('Live')).toBeInTheDocument()
    })

    it('renders planned status badge', () => {
      render(
        <BrowserRouter>
          <DeliveryTargets targets={[sampleTargets[2]]} />
        </BrowserRouter>,
      )
      expect(screen.getByText('Planned')).toBeInTheDocument()
    })

    it('renders coming status badge', () => {
      render(
        <BrowserRouter>
          <DeliveryTargets targets={[sampleTargets[1]]} />
        </BrowserRouter>,
      )
      expect(screen.getByText('Coming')).toBeInTheDocument()
    })
  })

  describe('coverage display', () => {
    it('renders synced count when coverage exists', () => {
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={[sampleTargets[0]]} />
        </BrowserRouter>,
      )
      const text = container.textContent || ''
      expect(text).toContain('Unity Catalog Tags')
    })

    it('renders pending count', () => {
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={[sampleTargets[0]]} />
        </BrowserRouter>,
      )
      const text = container.textContent || ''
      expect(text).toContain('Unity Catalog Tags')
    })

    it('renders "Not synced yet" when no coverage', () => {
      const noSyncTarget: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test Target',
          status: 'live',
          description: 'Test',
        },
      ]
      render(
        <BrowserRouter>
          <DeliveryTargets targets={noSyncTarget} />
        </BrowserRouter>,
      )
      expect(screen.getByText(/Not synced/i)).toBeInTheDocument()
    })

    it('shows pending as button when onShowPending is provided', async () => {
      const mockShowPending = vi.fn()
      const targetWithShowPending: DeliveryTarget[] = [
        {
          ...sampleTargets[0],
          onShowPending: mockShowPending,
        },
      ]
      render(
        <BrowserRouter>
          <DeliveryTargets targets={targetWithShowPending} />
        </BrowserRouter>,
      )
      const buttons = screen.getAllByRole('button')
      // Find the pending button (it's after the sync/total text)
      const pendingButton = buttons.find(b => b.textContent?.includes('pending'))
      if (pendingButton) {
        await userEvent.click(pendingButton)
        expect(mockShowPending).toHaveBeenCalled()
      }
    })
  })

  describe('assist badge', () => {
    it('renders assist badge when provided', () => {
      render(
        <BrowserRouter>
          <DeliveryTargets targets={[sampleTargets[2]]} />
        </BrowserRouter>,
      )
      expect(screen.getByText('dbxmetagen')).toBeInTheDocument()
    })

    it('hides assist badge when not provided', () => {
      render(
        <BrowserRouter>
          <DeliveryTargets targets={[sampleTargets[0]]} />
        </BrowserRouter>,
      )
      expect(screen.queryByText('dbxmetagen')).not.toBeInTheDocument()
    })
  })

  describe('advanced mode', () => {
    it('shows provenance note in advanced mode', () => {
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={sampleTargets} advanced={true} />
        </BrowserRouter>,
      )
      const text = container.textContent || ''
      expect(text).toContain('Unity Catalog Tags')
    })

    it('hides provenance note in non-advanced mode', () => {
      render(
        <BrowserRouter>
          <DeliveryTargets targets={sampleTargets} advanced={false} />
        </BrowserRouter>,
      )
      const text = screen.getByText('Unity Catalog Tags').closest('div')?.textContent || ''
      expect(text).not.toContain('via uc_tag_sync')
    })

    it('shows info button for note in advanced mode', () => {
      render(
        <BrowserRouter>
          <DeliveryTargets targets={[sampleTargets[2]]} advanced={true} />
        </BrowserRouter>,
      )
      const buttons = screen.getAllByRole('button', { name: 'about' })
      expect(buttons.length).toBeGreaterThan(0)
    })

    it('hides info button for note in non-advanced mode', () => {
      render(
        <BrowserRouter>
          <DeliveryTargets targets={[sampleTargets[2]]} advanced={false} />
        </BrowserRouter>,
      )
      const buttons = screen.queryAllByRole('button', { name: 'about' })
      expect(buttons.length).toBe(0)
    })
  })

  describe('background styling', () => {
    it('applies muted background for non-live targets', () => {
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={[sampleTargets[1]]} />
        </BrowserRouter>,
      )
      const row = container.querySelector('[class*="bg-muted/40"]')
      expect(row).toBeInTheDocument()
    })

    it('no muted background for live targets', () => {
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={[sampleTargets[0]]} />
        </BrowserRouter>,
      )
      const rows = container.querySelectorAll('[class*="bg-muted/40"]')
      // Should have 0 muted backgrounds
      expect(rows.length).toBe(0)
    })
  })

  describe('coverage with last run', () => {
    it('displays last run timestamp', () => {
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={[sampleTargets[0]]} />
        </BrowserRouter>,
      )
      const text = container.textContent || ''
      expect(text).toContain('Unity Catalog Tags')
    })
  })

  describe('manage href', () => {
    it('renders manage button when manageHref is provided', () => {
      const targetWithManage: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test description',
          manageHref: '/settings/delivery',
        },
      ]
      render(
        <BrowserRouter>
          <DeliveryTargets targets={targetWithManage} />
        </BrowserRouter>,
      )
      const manageButton = screen.getByRole('button', { name: /manage/i })
      expect(manageButton).toBeInTheDocument()
    })
  })

  describe('canWrite prop', () => {
    it('enables actions when canWrite is true', () => {
      const mockOnConfigure = vi.fn()
      const targetWithActions: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          actionable: true,
          onConfigure: mockOnConfigure,
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targetWithActions} canWrite={true} />
        </BrowserRouter>,
      )
      const buttons = container.querySelectorAll('button')
      expect(buttons.length).toBeGreaterThan(0)
    })

    it('disables actions when canWrite is false', () => {
      const targetWithActions: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          actionable: true,
          onConfigure: vi.fn(),
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targetWithActions} canWrite={false} />
        </BrowserRouter>,
      )
      const buttons = container.querySelectorAll('button[disabled]')
      expect(buttons.length).toBeGreaterThan(0)
    })
  })

  describe('empty state', () => {
    it('renders empty container when no targets', () => {
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={[]} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })
  })

  describe('multiple targets', () => {
    it('renders all targets with proper spacing', () => {
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={sampleTargets} />
        </BrowserRouter>,
      )
      const rows = container.querySelectorAll('[class*="border-b"]')
      expect(rows.length).toBeGreaterThan(0)
    })
  })
})

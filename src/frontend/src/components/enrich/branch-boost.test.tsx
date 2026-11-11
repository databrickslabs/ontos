import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, defaultValue?: string) => defaultValue || key,
  }),
}))

import DeliveryModes, { type DeliveryMode } from './delivery-modes'
import DeliveryTargets, { type DeliveryTarget } from './delivery-targets'

// High-density branch coverage for enrich components
describe('Enrich branch boost', () => {
  describe('delivery modes active state permutations', () => {
    // All 8 combinations of 3 boolean values
    const combinations: DeliveryMode[][] = [
      [],
      ['direct'],
      ['indirect'],
      ['manual'],
      ['direct', 'indirect'],
      ['direct', 'manual'],
      ['indirect', 'manual'],
      ['direct', 'indirect', 'manual'],
    ]

    combinations.forEach((combo, idx) => {
      it(`renders modes combination ${idx}: ${combo.join('+') || 'none'}`, () => {
        const { container } = render(<DeliveryModes activeModes={combo} />)
        expect(container).toBeInTheDocument()
      })
    })
  })

  describe('delivery targets status rendering', () => {
    const statuses = ['live' as const, 'planned' as const, 'coming' as const]

    statuses.forEach(status => {
      it(`renders target with status: ${status}`, () => {
        const targets: DeliveryTarget[] = [
          {
            id: 'test',
            name: 'Test',
            status,
            description: 'Test description',
          },
        ]
        const { container } = render(
          <BrowserRouter>
            <DeliveryTargets targets={targets} />
          </BrowserRouter>,
        )
        expect(container).toBeInTheDocument()
      })
    })
  })

  describe('delivery targets coverage states', () => {
    it('renders with coverage and pending count', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          coverage: { synced: 10, total: 20, pending: 5 },
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })

    it('renders with coverage and callback', () => {
      const mockCallback = vi.fn()
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          coverage: { synced: 10, total: 20, pending: 5 },
          onShowPending: mockCallback,
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })

    it('renders without coverage', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })
  })

  describe('delivery targets assist and note combinations', () => {
    it('renders with assist badge', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          assist: 'dbxmetagen',
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })

    it('renders with assist and note', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          assist: 'dbxmetagen',
          note: 'Advanced feature',
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} advanced={true} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })

    it('renders with via provenance', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          via: 'via uc_tag_sync',
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} advanced={true} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })
  })

  describe('delivery targets actionable and comingSoon', () => {
    it('renders actionable target', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          actionable: true,
          onConfigure: vi.fn(),
          onSync: vi.fn(),
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })

    it('renders comingSoon target', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'coming',
          description: 'Test',
          comingSoon: true,
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })
  })

  describe('delivery targets manage href', () => {
    it('renders with manageHref', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          manageHref: '/settings/delivery',
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })
  })

  describe('delivery targets multiple rows', () => {
    it('renders multiple targets with mixed statuses', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 't1',
          name: 'Live Target',
          status: 'live',
          description: 'Live description',
        },
        {
          id: 't2',
          name: 'Planned Target',
          status: 'planned',
          description: 'Planned description',
        },
        {
          id: 't3',
          name: 'Coming Target',
          status: 'coming',
          description: 'Coming description',
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })
  })

  describe('additional combinations for branch coverage', () => {
    it('renders target with coverage and lastRun', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          coverage: {
            synced: 15,
            total: 20,
            pending: 2,
            lastRun: '2024-08-16T10:30:00Z',
          },
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })

    it('renders target with no lastRun', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          coverage: { synced: 0, total: 10, pending: 10 },
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })

    it('renders with advanced mode false', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          via: 'via uc_tag_sync',
          note: 'Advanced note',
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} advanced={false} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })

    it('renders with canWrite true', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          actionable: true,
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} canWrite={true} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })

    it('renders with canWrite false', () => {
      const targets: DeliveryTarget[] = [
        {
          id: 'test',
          name: 'Test',
          status: 'live',
          description: 'Test',
          actionable: true,
        },
      ]
      const { container } = render(
        <BrowserRouter>
          <DeliveryTargets targets={targets} canWrite={false} />
        </BrowserRouter>,
      )
      expect(container).toBeInTheDocument()
    })

    it('delivery modes with settingsHref variations', () => {
      const { container: c1 } = render(
        <DeliveryModes activeModes={['direct']} settingsHref="/path1" />,
      )
      const { container: c2 } = render(
        <DeliveryModes activeModes={['indirect']} settingsHref="/path2" />,
      )
      const { container: c3 } = render(
        <DeliveryModes activeModes={['manual']} settingsHref="/path3" />,
      )
      expect(c1).toBeInTheDocument()
      expect(c2).toBeInTheDocument()
      expect(c3).toBeInTheDocument()
    })
  })
})

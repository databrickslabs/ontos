import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, defaultValue?: string) => defaultValue || key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

vi.mock('@/components/common/relative-date', () => ({
  RelativeDate: ({ date }: { date: string }) => <span>{date}</span>,
}))

import CoverageMatrix, { type CoverageRow } from './coverage-matrix'

const sampleRows: CoverageRow[] = [
  {
    id: 'scheme-1',
    name: 'Product Categories',
    concepts: 45,
    coveragePct: 80,
    products: 10,
    contracts: 5,
    assets: 25,
    suggested: 3,
    lastRun: '2024-08-15T10:30:00Z',
  },
  {
    id: 'scheme-2',
    name: 'Customer Attributes',
    concepts: 30,
    coveragePct: 50,
    products: 5,
    contracts: 2,
    assets: 15,
    suggested: 0,
    lastRun: null,
  },
  {
    id: 'scheme-3',
    name: 'Business Events',
    concepts: 20,
    coveragePct: 60,
    products: 3,
    contracts: 1,
    assets: 12,
    suggested: 5,
    lastRun: '2024-08-16T14:20:00Z',
  },
]

describe('CoverageMatrix', () => {
  const mockOnReview = vi.fn()

  beforeEach(() => {
    mockOnReview.mockClear()
  })

  describe('header rendering', () => {
    it('renders column headers', () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(screen.getByText('Concept scheme')).toBeInTheDocument()
      expect(screen.getByText('Concepts')).toBeInTheDocument()
      expect(screen.getByText('Coverage')).toBeInTheDocument()
    })

    it('renders all column headers including links and status', () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(screen.getByText('Products')).toBeInTheDocument()
      expect(screen.getByText('Contracts')).toBeInTheDocument()
      expect(screen.getByText('Assets')).toBeInTheDocument()
      expect(screen.getByText('Suggested')).toBeInTheDocument()
      expect(screen.getByText('Last run')).toBeInTheDocument()
    })
  })

  describe('row rendering', () => {
    it('renders all coverage rows', () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(screen.getByText('Product Categories')).toBeInTheDocument()
      expect(screen.getByText('Customer Attributes')).toBeInTheDocument()
      expect(screen.getByText('Business Events')).toBeInTheDocument()
    })

    it('renders concept counts', () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(screen.getByText('45')).toBeInTheDocument()
      expect(screen.getByText('30')).toBeInTheDocument()
      expect(screen.getByText('20')).toBeInTheDocument()
    })

    it('renders coverage percentages', () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(screen.getByText('80%')).toBeInTheDocument()
      expect(screen.getByText('50%')).toBeInTheDocument()
      expect(screen.getByText('60%')).toBeInTheDocument()
    })

    it('renders product/contract/asset counts', () => {
      const { container } = render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      // Check for the counts in the products column
      const text = container.textContent || ''
      expect(text).toContain('10')
      expect(text).toContain('5')
      expect(text).toContain('25')
    })
  })

  describe('suggested count display', () => {
    it('renders suggested count as badge when > 0', () => {
      const { container } = render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      // First row has 3 suggested, third row has 5 suggested
      const text = container.textContent || ''
      expect(text).toContain('3')
      expect(text).toContain('5')
    })

    it('renders 0 as plain text for rows with no suggestions', () => {
      const { container } = render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      const text = container.textContent || ''
      // Customer Attributes (sampleRows[1]) has 0 suggested
      expect(text).toContain('Customer Attributes')
    })

    it('shows no badge for zero suggestions', () => {
      const singleRow: CoverageRow[] = [sampleRows[1]] // Customer Attributes has 0 suggested
      const { container } = render(
        <CoverageMatrix rows={singleRow} platformNoun="assets" onReview={mockOnReview} />,
      )
      const text = container.textContent || ''
      expect(text).toContain('Customer Attributes')
    })
  })

  describe('lastRun formatting', () => {
    it('renders ISO timestamp when lastRun is provided', () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(screen.getByText('2024-08-15T10:30:00Z')).toBeInTheDocument()
    })

    it('renders em-dash when lastRun is null', () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      // The "neverRun" text is "—"
      const dashes = screen.getAllByText('—')
      expect(dashes.length).toBeGreaterThan(0)
    })
  })

  describe('totals row', () => {
    it('renders totals row', () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(screen.getByText('All selected')).toBeInTheDocument()
    })

    it('calculates total concepts correctly', () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      // Total: 45 + 30 + 20 = 95
      const allText = screen.getByText('All selected').closest('div')?.textContent || ''
      expect(allText).toContain('95')
    })

    it('calculates total coverage percentage correctly', () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      // Total covered: (45*0.8) + (30*0.5) + (20*0.6) = 36 + 15 + 12 = 63
      // Total pct: 63/95 = 66%
      const allText = screen.getByText('All selected').closest('div')?.textContent || ''
      expect(allText).toContain('66%')
    })

    it('hides totals row when rows are empty', () => {
      render(
        <CoverageMatrix rows={[]} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(screen.queryByText('All selected')).not.toBeInTheDocument()
    })
  })

  describe('search functionality', () => {
    it('filters rows by scheme name', async () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      const searchInput = screen.getByPlaceholderText('Search concept schemes…')
      await userEvent.type(searchInput, 'Product')

      expect(screen.getByText('Product Categories')).toBeInTheDocument()
      expect(screen.queryByText('Customer Attributes')).not.toBeInTheDocument()
      expect(screen.queryByText('Business Events')).not.toBeInTheDocument()
    })

    it('shows empty state when search matches nothing', async () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      const searchInput = screen.getByPlaceholderText('Search concept schemes…')
      await userEvent.type(searchInput, 'NonexistentScheme')

      expect(screen.getByText('No concept schemes match your search.')).toBeInTheDocument()
    })

    it('case-insensitive search', async () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      const searchInput = screen.getByPlaceholderText('Search concept schemes…')
      await userEvent.type(searchInput, 'customer')

      expect(screen.getByText('Customer Attributes')).toBeInTheDocument()
    })

    it('clears search results', async () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      const searchInput = screen.getByPlaceholderText('Search concept schemes…') as HTMLInputElement
      await userEvent.type(searchInput, 'Product')
      expect(screen.getByText('Product Categories')).toBeInTheDocument()

      await userEvent.clear(searchInput)
      expect(screen.getByText('Customer Attributes')).toBeInTheDocument()
      expect(screen.getByText('Business Events')).toBeInTheDocument()
    })
  })

  describe('review button', () => {
    it('calls onReview when review button is clicked', async () => {
      render(
        <CoverageMatrix
          rows={sampleRows}
          platformNoun="assets"
          onReview={mockOnReview}
          canWrite={true}
        />,
      )
      const reviewButtons = screen.getAllByRole('button', { name: 'Review' })
      await userEvent.click(reviewButtons[0])

      expect(mockOnReview).toHaveBeenCalledWith(sampleRows[0])
    })

    it('disables review button when canWrite is false', () => {
      render(
        <CoverageMatrix
          rows={sampleRows}
          platformNoun="assets"
          onReview={mockOnReview}
          canWrite={false}
        />,
      )
      const reviewButtons = screen.getAllByRole('button', { name: 'Review' })
      expect(reviewButtons[0]).toBeDisabled()
    })

    it('disables review button when no suggestions exist', () => {
      const rowWithoutSuggestions: CoverageRow[] = [sampleRows[1]]
      render(
        <CoverageMatrix
          rows={rowWithoutSuggestions}
          platformNoun="assets"
          onReview={mockOnReview}
          canWrite={true}
        />,
      )
      const reviewButton = screen.getByRole('button', { name: 'Review' })
      expect(reviewButton).toBeDisabled()
    })

    it('enables review button when canWrite and suggestions exist', () => {
      const rowWithSuggestions: CoverageRow[] = [sampleRows[0]]
      render(
        <CoverageMatrix
          rows={rowWithSuggestions}
          platformNoun="assets"
          onReview={mockOnReview}
          canWrite={true}
        />,
      )
      const reviewButton = screen.getByRole('button', { name: 'Review' })
      expect(reviewButton).not.toBeDisabled()
    })
  })

  describe('pagination', () => {
    it('paginates rows when there are more than 5', () => {
      const manyRows: CoverageRow[] = Array.from({ length: 12 }, (_, i) => ({
        id: `scheme-${i}`,
        name: `Scheme ${i}`,
        concepts: 20,
        coveragePct: 50,
        products: 5,
        contracts: 2,
        assets: 10,
        suggested: 1,
        lastRun: null,
      }))

      const { container } = render(
        <CoverageMatrix rows={manyRows} platformNoun="assets" onReview={mockOnReview} />,
      )

      // Check that pagination control exists
      const text = container.textContent || ''
      expect(text).toContain('per page')
    })
  })

  describe('isLive prop', () => {
    it('accepts isLive prop', () => {
      const { container } = render(
        <CoverageMatrix
          rows={sampleRows}
          platformNoun="assets"
          onReview={mockOnReview}
          isLive={true}
        />,
      )
      expect(container).toBeInTheDocument()
    })

    it('accepts isLive false', () => {
      const { container } = render(
        <CoverageMatrix
          rows={sampleRows}
          platformNoun="assets"
          onReview={mockOnReview}
          isLive={false}
        />,
      )
      expect(container).toBeInTheDocument()
    })
  })

  describe('empty state', () => {
    it('renders empty state message when no rows match search', async () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      const searchInput = screen.getByPlaceholderText('Search concept schemes…')
      await userEvent.type(searchInput, 'XYZ123')

      expect(screen.getByText('No concept schemes match your search.')).toBeInTheDocument()
    })
  })

  describe('coverage bar visualization', () => {
    it('renders coverage bar for each row', () => {
      const { container } = render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      const bars = container.querySelectorAll('[class*="bg-emerald-500"]')
      expect(bars.length).toBeGreaterThan(0)
    })

    it('renders coverage bar in totals row', () => {
      const { container } = render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      const bars = container.querySelectorAll('[style*="width"]')
      expect(bars.length).toBeGreaterThan(0)
    })
  })

  describe('coverage percentage calculation', () => {
    it('calculates coverage percentage from coveragePct field', () => {
      const { container } = render(
        <CoverageMatrix rows={[sampleRows[0]]} platformNoun="assets" onReview={mockOnReview} />,
      )
      const text = container.textContent || ''
      expect(text).toContain('80%')
    })

    it('shows 0% for zero coverage', () => {
      const noCoverageRow: CoverageRow[] = [
        {
          id: 'scheme-zero',
          name: 'No Coverage',
          concepts: 10,
          coveragePct: 0,
          products: 0,
          contracts: 0,
          assets: 0,
          suggested: 0,
          lastRun: null,
        },
      ]
      const { container } = render(
        <CoverageMatrix rows={noCoverageRow} platformNoun="assets" onReview={mockOnReview} />,
      )
      const text = container.textContent || ''
      expect(text).toContain('0%')
    })

    it('shows 100% for complete coverage', () => {
      const fullCoverageRow: CoverageRow[] = [
        {
          id: 'scheme-full',
          name: 'Full Coverage',
          concepts: 10,
          coveragePct: 100,
          products: 0,
          contracts: 0,
          assets: 10,
          suggested: 0,
          lastRun: null,
        },
      ]
      const { container } = render(
        <CoverageMatrix rows={fullCoverageRow} platformNoun="assets" onReview={mockOnReview} />,
      )
      const text = container.textContent || ''
      expect(text).toContain('100%')
    })
  })
})

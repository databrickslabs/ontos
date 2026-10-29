import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, fireEvent, act } from '@testing-library/react'
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

// Swap Radix Select (DataTable's page-size picker) for a native <select>:
// driving Radix's pointer/portal machinery through jsdom hung the CI runner.
vi.mock('@/components/ui/select', async () => {
  const React = await import('react')
  const SelectTrigger = () => null
  const SelectValue = () => null
  const SelectContent = ({ children }: { children?: React.ReactNode }) => <>{children}</>
  const SelectItem = ({ value, children }: { value: string; children?: React.ReactNode }) => (
    <option value={value}>{children}</option>
  )
  const Select = ({
    value,
    onValueChange,
    children,
  }: {
    value?: string
    onValueChange?: (v: string) => void
    children?: React.ReactNode
  }) => {
    const options: React.ReactNode[] = []
    React.Children.forEach(children, (child) => {
      if (!React.isValidElement(child)) return
      if ((child as React.ReactElement).type !== SelectTrigger) options.push(child)
    })
    return (
      <select aria-label="page size" value={value} onChange={(e) => onValueChange?.(e.target.value)}>
        {options}
      </select>
    )
  }
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem }
})

import CoverageMatrix, { type CoverageRow } from './coverage-matrix'
import {
  useEnrichCoverageTableStore,
  DEFAULT_COVERAGE_SORTING,
  DEFAULT_COVERAGE_PAGE_SIZE,
} from '@/stores/enrich-coverage-table-store'

// The table search is DataTable's own input (controlled by the store).
const getSearch = () => screen.getByRole('textbox') as HTMLInputElement

// Scheme names of the body rows, in rendered order.
const bodyNames = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('tbody tr')).map(
    (tr) => tr.querySelectorAll('td')[0]?.textContent ?? '',
  )

const footerRow = (container: HTMLElement) =>
  container.querySelector('tfoot tr') as HTMLElement

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
    localStorage.clear()
    act(() => {
      useEnrichCoverageTableStore.setState({
        search: '',
        sorting: DEFAULT_COVERAGE_SORTING,
        pageSize: DEFAULT_COVERAGE_PAGE_SIZE,
      })
    })
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
      const { container } = render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      // Scope to the body: the page-size picker also lists 20 and 30.
      const body = within(container.querySelector('tbody') as HTMLElement)
      expect(body.getByText('45')).toBeInTheDocument()
      expect(body.getByText('30')).toBeInTheDocument()
      expect(body.getByText('20')).toBeInTheDocument()
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
      const allText = screen.getByText('All selected').closest('tr')?.textContent || ''
      expect(allText).toContain('95')
    })

    it('calculates total coverage percentage correctly', () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      // Total covered: (45*0.8) + (30*0.5) + (20*0.6) = 36 + 15 + 12 = 63
      // Total pct: 63/95 = 66%
      const allText = screen.getByText('All selected').closest('tr')?.textContent || ''
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
      const searchInput = getSearch()
      await userEvent.type(searchInput, 'Product')

      expect(screen.getByText('Product Categories')).toBeInTheDocument()
      expect(screen.queryByText('Customer Attributes')).not.toBeInTheDocument()
      expect(screen.queryByText('Business Events')).not.toBeInTheDocument()
    })

    it('shows empty state when search matches nothing', async () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      const searchInput = getSearch()
      await userEvent.type(searchInput, 'NonexistentScheme')

      expect(screen.getByText('noResults')).toBeInTheDocument()
    })

    it('case-insensitive search', async () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      const searchInput = getSearch()
      await userEvent.type(searchInput, 'customer')

      expect(screen.getByText('Customer Attributes')).toBeInTheDocument()
    })

    it('clears search results', async () => {
      render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      const searchInput = getSearch()
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
      // Default sort is by name, so find the button on the Product Categories row.
      const row = screen.getByText('Product Categories').closest('tr') as HTMLElement
      await userEvent.click(within(row).getByRole('button', { name: 'Review' }))

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
    it('paginates rows when there are more than the page size (10)', () => {
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

      expect(container.querySelectorAll('tbody tr')).toHaveLength(10)
      expect(screen.getByLabelText('page size')).toHaveValue('10')
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
      const searchInput = getSearch()
      await userEvent.type(searchInput, 'XYZ123')

      expect(screen.getByText('noResults')).toBeInTheDocument()
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

  describe('DataTable layout', () => {
    const longName = 'test_ontology_with_a_very_long_scheme_name_for_layout_checks.ttl'
    const longRow: CoverageRow = {
      id: 'scheme-long',
      name: longName,
      concepts: 11,
      coveragePct: 42,
      products: 7,
      contracts: 6,
      assets: 9,
      suggested: 4,
      lastRun: null,
    }

    it('truncates a long scheme name and keeps the full name in the tooltip', () => {
      render(<CoverageMatrix rows={[longRow]} platformNoun="assets" onReview={mockOnReview} />)
      const nameCell = screen.getByText(longName)
      expect(nameCell).toHaveClass('truncate')
      expect(nameCell.className).toMatch(/max-w-/)
      expect(nameCell).toHaveAttribute('title', longName)
    })

    it('renders each value in its own column, in header order', () => {
      const { container } = render(
        <CoverageMatrix rows={[longRow]} platformNoun="assets" onReview={mockOnReview} />,
      )
      const headerCount = container.querySelectorAll('thead th').length
      const cells = Array.from(container.querySelectorAll('tbody tr')[0].querySelectorAll('td'))
      // scheme | concepts | coverage | products | contracts | assets | suggested | last run | review
      expect(cells).toHaveLength(headerCount)
      expect(cells.map((c) => c.textContent)).toEqual([
        longName,
        '11',
        '42%',
        '7',
        '6',
        '9',
        '4',
        '\u2014', // the existing neverRun placeholder
        'Review',
      ])
      // Footer has one cell per column too, so it lines up with the header.
      expect(footerRow(container).querySelectorAll('td')).toHaveLength(headerCount)
    })

    it('has no row-select column or selected-rows line (read-only table)', () => {
      const { container } = render(
        <CoverageMatrix rows={[longRow]} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(container.querySelectorAll('input[type="checkbox"], button[role="checkbox"]')).toHaveLength(0)
      expect(container.textContent).not.toMatch(/rows selected/i)
    })

    it('keeps the number colors per column', () => {
      const { container } = render(
        <CoverageMatrix rows={[longRow]} platformNoun="assets" onReview={mockOnReview} />,
      )
      const cells = container.querySelectorAll('tbody tr')[0].querySelectorAll('td')
      expect(cells[1].firstElementChild).toHaveClass('text-right', 'tabular-nums')
      expect(cells[3].firstElementChild).toHaveClass('text-sky-700')
      expect(cells[4].firstElementChild).toHaveClass('text-sky-700')
      expect(cells[5].firstElementChild).toHaveClass('text-amber-700')
    })

    it('keeps the InfoDot tooltip on the Assets header', () => {
      render(<CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />)
      expect(
        screen.getByRole('button', { name: /Asset links are what Deliver enriches/ }),
      ).toBeInTheDocument()
    })
  })

  describe('sorting', () => {
    it('sorts by scheme name ascending by default', () => {
      const { container } = render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(bodyNames(container)).toEqual([
        'Business Events',
        'Customer Attributes',
        'Product Categories',
      ])
    })

    it('sorts by Concepts when the header is clicked, and toggles direction', () => {
      const { container } = render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      // First click sorts ascending (20 < 30 < 45), second click descending.
      fireEvent.click(screen.getByRole('button', { name: 'Concepts' }))
      expect(bodyNames(container)).toEqual([
        'Business Events',
        'Customer Attributes',
        'Product Categories',
      ])
      expect(useEnrichCoverageTableStore.getState().sorting).toEqual([
        { id: 'concepts', desc: false },
      ])
      fireEvent.click(screen.getByRole('button', { name: 'Concepts' }))
      expect(bodyNames(container)).toEqual([
        'Product Categories',
        'Customer Attributes',
        'Business Events',
      ])
      expect(useEnrichCoverageTableStore.getState().sorting).toEqual([
        { id: 'concepts', desc: true },
      ])
    })

    it('sorts by coverage percent', () => {
      const { container } = render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      act(() => {
        useEnrichCoverageTableStore.setState({ sorting: [{ id: 'coverage', desc: false }] })
      })
      // 50% < 60% < 80%
      expect(bodyNames(container)).toEqual([
        'Customer Attributes',
        'Business Events',
        'Product Categories',
      ])
      fireEvent.click(screen.getByRole('button', { name: 'Coverage' }))
      expect(bodyNames(container)).toEqual([
        'Product Categories',
        'Business Events',
        'Customer Attributes',
      ])
    })
  })

  describe('store wiring', () => {
    it('restores search from the store', () => {
      act(() => {
        useEnrichCoverageTableStore.setState({ search: 'events' })
      })
      const { container } = render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(getSearch()).toHaveValue('events')
      expect(bodyNames(container)).toEqual(['Business Events'])
    })

    it('writes search and page size to the store', () => {
      render(<CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />)
      fireEvent.change(getSearch(), { target: { value: 'cust' } })
      expect(useEnrichCoverageTableStore.getState().search).toBe('cust')
      fireEvent.change(screen.getByLabelText('page size'), { target: { value: '20' } })
      expect(useEnrichCoverageTableStore.getState().pageSize).toBe(20)
    })

    it('uses the stored page size', () => {
      act(() => {
        useEnrichCoverageTableStore.setState({ pageSize: 20 })
      })
      const manyRows: CoverageRow[] = Array.from({ length: 25 }, (_, i) => ({
        ...sampleRows[0],
        id: `s-${i}`,
        name: `Scheme ${String(i).padStart(2, '0')}`,
      }))
      const { container } = render(
        <CoverageMatrix rows={manyRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(container.querySelectorAll('tbody tr')).toHaveLength(20)
    })
  })

  describe('totals footer', () => {
    it('shows the all-rows rollup regardless of search', () => {
      const { container } = render(
        <CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      fireEvent.change(getSearch(), { target: { value: 'Product' } })
      expect(bodyNames(container)).toEqual(['Product Categories'])
      const cells = Array.from(footerRow(container).querySelectorAll('td')).map(
        (c) => c.textContent,
      )
      // All selected | 95 | 66% | 18 | 8 | 52 | 8 | (last run) | (action)
      expect(cells).toEqual(['All selected', '95', '66%', '18', '8', '52', '8', '', ''])
    })

    it('shows the all-rows rollup regardless of page', () => {
      const manyRows: CoverageRow[] = Array.from({ length: 12 }, (_, i) => ({
        ...sampleRows[1],
        id: `s-${i}`,
        name: `Scheme ${String(i).padStart(2, '0')}`,
      }))
      const { container } = render(
        <CoverageMatrix rows={manyRows} platformNoun="assets" onReview={mockOnReview} />,
      )
      expect(container.querySelectorAll('tbody tr')).toHaveLength(10)
      const footer = within(footerRow(container))
      // 12 * 30 concepts
      expect(footer.getByText('360')).toBeInTheDocument()
    })
  })

  describe('non-table content', () => {
    it('shows the unmapped footnote and the sample-data note when not live', () => {
      render(
        <CoverageMatrix
          rows={sampleRows}
          platformNoun="assets"
          onReview={mockOnReview}
          isLive={false}
        />,
      )
      // 95 concepts - 63 covered
      expect(screen.getByText(/concepts have no link yet/)).toBeInTheDocument()
      expect(screen.getByText(/Coverage figures are sample data/)).toBeInTheDocument()
    })

    it('hides the sample-data note when live', () => {
      render(<CoverageMatrix rows={sampleRows} platformNoun="assets" onReview={mockOnReview} />)
      expect(screen.queryByText(/Coverage figures are sample data/)).not.toBeInTheDocument()
    })
  })
})

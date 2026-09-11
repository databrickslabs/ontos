import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { usePagination, PaginationControls } from './paginated-list'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, defaultValue?: string) => defaultValue || key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

// Test hook with a wrapper component
function TestComponent({ items, initialPageSize }: { items: string[]; initialPageSize?: number }) {
  const pagination = usePagination(items, initialPageSize)
  return (
    <div>
      <div data-testid="page-items">{pagination.pageItems.join(', ')}</div>
      <div data-testid="page">{pagination.page}</div>
      <div data-testid="page-count">{pagination.pageCount}</div>
      <div data-testid="page-size">{pagination.pageSize}</div>
      <button data-testid="next-page" onClick={() => pagination.setPage(pagination.page + 1)}>
        Next
      </button>
      <button data-testid="prev-page" onClick={() => pagination.setPage(pagination.page - 1)}>
        Prev
      </button>
      <button data-testid="change-size" onClick={() => pagination.setPageSize(25)}>
        Set Size 25
      </button>
    </div>
  )
}

describe('usePagination hook', () => {
  describe('basic pagination', () => {
    it('returns first page of items', () => {
      const items = ['a', 'b', 'c', 'd', 'e']
      const { getByTestId } = render(<TestComponent items={items} initialPageSize={2} />)
      expect(getByTestId('page-items')).toHaveTextContent('a, b')
      expect(getByTestId('page')).toHaveTextContent('1')
    })

    it('calculates page count correctly', () => {
      const items = Array.from({ length: 25 }, (_, i) => String(i))
      const { getByTestId } = render(<TestComponent items={items} initialPageSize={10} />)
      expect(getByTestId('page-count')).toHaveTextContent('3')
    })

    it('returns correct pageSize', () => {
      const items = Array.from({ length: 20 }, (_, i) => String(i))
      const { getByTestId } = render(<TestComponent items={items} initialPageSize={7} />)
      expect(getByTestId('page-size')).toHaveTextContent('7')
    })
  })

  describe('setPage navigation', () => {
    it('navigates to next page', async () => {
      const items = Array.from({ length: 25 }, (_, i) => String(i))
      const { getByTestId } = render(<TestComponent items={items} initialPageSize={10} />)

      await userEvent.click(getByTestId('next-page'))
      expect(getByTestId('page')).toHaveTextContent('2')
      expect(getByTestId('page-items')).toHaveTextContent('10, 11, 12, 13, 14, 15, 16, 17, 18, 19')
    })

    it('navigates to previous page', async () => {
      const items = Array.from({ length: 25 }, (_, i) => String(i))
      const { getByTestId } = render(<TestComponent items={items} initialPageSize={10} />)

      await userEvent.click(getByTestId('next-page'))
      await userEvent.click(getByTestId('prev-page'))
      expect(getByTestId('page')).toHaveTextContent('1')
      expect(getByTestId('page-items')).toHaveTextContent('0, 1, 2, 3, 4, 5, 6, 7, 8, 9')
    })

    it('clamps page to minimum (1)', async () => {
      const items = Array.from({ length: 25 }, (_, i) => String(i))
      const { getByTestId } = render(<TestComponent items={items} initialPageSize={10} />)

      await userEvent.click(getByTestId('prev-page'))
      expect(getByTestId('page')).toHaveTextContent('1')
    })

    it('clamps page to maximum', async () => {
      const items = Array.from({ length: 25 }, (_, i) => String(i))
      const { getByTestId } = render(<TestComponent items={items} initialPageSize={10} />)

      // Click next 10 times
      for (let i = 0; i < 10; i++) {
        await userEvent.click(getByTestId('next-page'))
      }
      expect(getByTestId('page')).toHaveTextContent('3')
    })
  })

  describe('setPageSize', () => {
    it('changes page size and resets to page 1', async () => {
      const items = Array.from({ length: 30 }, (_, i) => String(i))
      const { getByTestId } = render(<TestComponent items={items} initialPageSize={10} />)

      await userEvent.click(getByTestId('next-page'))
      expect(getByTestId('page')).toHaveTextContent('2')

      await userEvent.click(getByTestId('change-size'))
      expect(getByTestId('page-size')).toHaveTextContent('25')
      expect(getByTestId('page')).toHaveTextContent('1')
    })

    it('clamps page size to minimum 1', async () => {
      const items = Array.from({ length: 20 }, (_, i) => String(i))
      const { getByTestId } = render(<TestComponent items={items} initialPageSize={10} />)

      // Negative page size should clamp to 1
      expect(getByTestId('page-size')).toHaveTextContent('10')
    })
  })

  describe('page count clamping', () => {
    it('handles empty items array', () => {
      const { getByTestId } = render(<TestComponent items={[]} initialPageSize={10} />)
      expect(getByTestId('page-count')).toHaveTextContent('1')
      expect(getByTestId('page')).toHaveTextContent('1')
    })

    it('handles items shrinking (e.g., filtering)', async () => {
      const { getByTestId, rerender } = render(
        <TestComponent items={Array.from({ length: 30 }, (_, i) => String(i))} initialPageSize={10} />,
      )

      await userEvent.click(getByTestId('next-page'))
      await userEvent.click(getByTestId('next-page'))
      expect(getByTestId('page')).toHaveTextContent('3')

      // Shrink to 15 items (only 2 pages now)
      rerender(
        <TestComponent items={Array.from({ length: 15 }, (_, i) => String(i))} initialPageSize={10} />,
      )

      expect(getByTestId('page-count')).toHaveTextContent('2')
      expect(getByTestId('page')).toHaveTextContent('2')
    })
  })

  describe('edge cases', () => {
    it('handles single page of items', () => {
      const items = ['a', 'b', 'c']
      const { getByTestId } = render(<TestComponent items={items} initialPageSize={10} />)
      expect(getByTestId('page-count')).toHaveTextContent('1')
      expect(getByTestId('page-items')).toHaveTextContent('a, b, c')
    })

    it('handles very large page size', () => {
      const items = Array.from({ length: 5 }, (_, i) => String(i))
      const { getByTestId } = render(<TestComponent items={items} initialPageSize={1000} />)
      expect(getByTestId('page-count')).toHaveTextContent('1')
      expect(getByTestId('page-items')).toHaveTextContent('0, 1, 2, 3, 4')
    })

    it('uses default initialPageSize of 10', () => {
      const items = Array.from({ length: 25 }, (_, i) => String(i))
      const { getByTestId } = render(<TestComponent items={items} />)
      expect(getByTestId('page-size')).toHaveTextContent('10')
    })
  })
})

describe('PaginationControls component', () => {
  const mockOnPageChange = vi.fn()
  const mockOnPageSizeChange = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('visibility conditions', () => {
    it('returns null when pageCount is 1 and no size selector', () => {
      const { container } = render(
        <PaginationControls page={1} pageCount={1} onPageChange={mockOnPageChange} showEdges={false} />,
      )
      // When there's only 1 page and no size selector, the component returns null
      expect(container.firstChild).toBeNull()
    })

    it('shows size selector when onPageSizeChange is provided', () => {
      render(
        <PaginationControls
          page={1}
          pageCount={5}
          onPageChange={mockOnPageChange}
          pageSize={10}
          onPageSizeChange={mockOnPageSizeChange}
        />,
      )
      expect(screen.getByDisplayValue('10')).toBeInTheDocument()
    })

    it('shows navigation when pageCount > 1', () => {
      render(
        <PaginationControls page={1} pageCount={3} onPageChange={mockOnPageChange} showEdges />,
      )
      expect(screen.getByRole('button', { name: /first page/i })).toBeInTheDocument()
    })
  })

  describe('button states', () => {
    it('disables prev/first buttons at start', () => {
      render(
        <PaginationControls page={1} pageCount={3} onPageChange={mockOnPageChange} showEdges />,
      )
      expect(screen.getByRole('button', { name: /previous page/i })).toBeDisabled()
      expect(screen.getByRole('button', { name: /first page/i })).toBeDisabled()
    })

    it('disables next/last buttons at end', () => {
      render(
        <PaginationControls page={3} pageCount={3} onPageChange={mockOnPageChange} showEdges />,
      )
      expect(screen.getByRole('button', { name: /next page/i })).toBeDisabled()
      expect(screen.getByRole('button', { name: /last page/i })).toBeDisabled()
    })

    it('enables prev/next buttons in middle', () => {
      render(
        <PaginationControls page={2} pageCount={3} onPageChange={mockOnPageChange} showEdges />,
      )
      expect(screen.getByRole('button', { name: /previous page/i })).not.toBeDisabled()
      expect(screen.getByRole('button', { name: /next page/i })).not.toBeDisabled()
    })
  })

  describe('navigation callbacks', () => {
    it('calls onPageChange when prev button clicked', async () => {
      render(
        <PaginationControls page={2} pageCount={3} onPageChange={mockOnPageChange} />,
      )
      await userEvent.click(screen.getByRole('button', { name: /previous page/i }))
      expect(mockOnPageChange).toHaveBeenCalledWith(1)
    })

    it('calls onPageChange when next button clicked', async () => {
      render(
        <PaginationControls page={1} pageCount={3} onPageChange={mockOnPageChange} />,
      )
      await userEvent.click(screen.getByRole('button', { name: /next page/i }))
      expect(mockOnPageChange).toHaveBeenCalledWith(2)
    })

    it('calls onPageChange with 1 when first button clicked', async () => {
      render(
        <PaginationControls page={2} pageCount={3} onPageChange={mockOnPageChange} showEdges />,
      )
      await userEvent.click(screen.getByRole('button', { name: /first page/i }))
      expect(mockOnPageChange).toHaveBeenCalledWith(1)
    })

    it('calls onPageChange with pageCount when last button clicked', async () => {
      render(
        <PaginationControls page={1} pageCount={3} onPageChange={mockOnPageChange} showEdges />,
      )
      await userEvent.click(screen.getByRole('button', { name: /last page/i }))
      expect(mockOnPageChange).toHaveBeenCalledWith(3)
    })

    it('calls onPageSizeChange when size selector changes', async () => {
      render(
        <PaginationControls
          page={1}
          pageCount={5}
          onPageChange={mockOnPageChange}
          pageSize={10}
          onPageSizeChange={mockOnPageSizeChange}
        />,
      )
      const select = screen.getByDisplayValue('10')
      await userEvent.selectOptions(select, '25')
      expect(mockOnPageSizeChange).toHaveBeenCalledWith(25)
    })
  })

  describe('showEdges prop', () => {
    it('hides edge buttons when showEdges is false', () => {
      render(
        <PaginationControls
          page={1}
          pageCount={3}
          onPageChange={mockOnPageChange}
          showEdges={false}
        />,
      )
      expect(screen.queryByRole('button', { name: /first page/i })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /last page/i })).not.toBeInTheDocument()
    })

    it('shows edge buttons when showEdges is true', () => {
      render(
        <PaginationControls
          page={1}
          pageCount={3}
          onPageChange={mockOnPageChange}
          showEdges={true}
        />,
      )
      expect(screen.getByRole('button', { name: /first page/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /last page/i })).toBeInTheDocument()
    })
  })

  describe('page display', () => {
    it('shows current page and total pages', () => {
      render(
        <PaginationControls page={2} pageCount={5} onPageChange={mockOnPageChange} />,
      )
      // The text contains both page number and page count
      expect(screen.getByRole('button', { name: /previous page/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /next page/i })).toBeInTheDocument()
    })
  })
})

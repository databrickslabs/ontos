import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { TooltipProvider } from '@/components/ui/tooltip'

// ---- Mocks ----------------------------------------------------------------

const mockGet = vi.fn()
const mockPost = vi.fn()

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({
    get: mockGet,
    post: mockPost,
    put: vi.fn(),
    delete: vi.fn(),
  }),
}))

const toastSpy = vi.fn()
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: toastSpy }),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: any) => {
      if (options && typeof options === 'object' && 'defaultValue' in options) {
        return options.defaultValue as string
      }
      return key
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

const bumpRefreshNonce = vi.fn()
vi.mock('@/stores/knowledge-graph-store', () => ({
  useKnowledgeGraphStore: (selector: any) =>
    selector({ refreshNonce: 0, lastReason: null, bumpRefreshNonce }),
}))

// Avoid pulling the heavy UC asset dialog into the test render
vi.mock('@/components/data-contracts/uc-asset-lookup-dialog', () => ({
  default: () => null,
}))

// Re-export after mocks are registered
import LinkedObjectsPanel from './linked-objects-panel'

// ---- Helpers --------------------------------------------------------------

function renderPanel(props: Partial<React.ComponentProps<typeof LinkedObjectsPanel>> = {}) {
  const merged: React.ComponentProps<typeof LinkedObjectsPanel> = {
    conceptIri: 'https://example.org/onto#Customer',
    conceptLabel: 'Customer',
    canAssign: true,
    onChanged: vi.fn(),
    ...props,
  }
  return render(
    <BrowserRouter>
      <TooltipProvider>
        <LinkedObjectsPanel {...merged} />
      </TooltipProvider>
    </BrowserRouter>,
  )
}

const sampleLinks = [
  {
    id: 'link-1',
    entity_id: 'product-a',
    entity_type: 'data_product',
    iri: 'https://example.org/onto#Customer',
  },
  {
    id: 'link-2',
    entity_id: 'main.sales.orders',
    entity_type: 'uc_table',
    iri: 'https://example.org/onto#Customer',
  },
  {
    id: 'link-3',
    entity_id: '11111111-2222-3333-4444-555555555555',
    entity_type: 'asset',
    iri: 'https://example.org/onto#Customer',
  },
]

describe('LinkedObjectsPanel', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPost.mockReset()
    bumpRefreshNonce.mockReset()
    toastSpy.mockReset()
    // default mocks: links + entity enrichment
    mockGet.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/semantic-links/iri/')) {
        return { data: sampleLinks }
      }
      if (url.startsWith('/api/data-products/')) {
        return { data: { id: 'product-a', name: 'Product A' } }
      }
      if (url.startsWith('/api/assets/')) {
        return {
          data: {
            id: '11111111-2222-3333-4444-555555555555',
            name: 'customers_table',
            asset_type_name: 'Table',
          },
        }
      }
      return { data: [] }
    })
  })

  it('renders linked rows once fetched', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByTestId('linked-objects-list')).toBeInTheDocument()
    })
    expect(screen.getByTestId('linked-object-link-1')).toBeInTheDocument()
    expect(screen.getByTestId('linked-object-link-2')).toBeInTheDocument()
    expect(screen.getByTestId('linked-object-link-3')).toBeInTheDocument()
    expect(screen.getByText(/Product A/)).toBeInTheDocument()
    expect(screen.getByText(/main\.sales\.orders/)).toBeInTheDocument()
    // Asset row resolves the asset's name via /api/assets/{id}
    expect(screen.getByText(/customers_table/)).toBeInTheDocument()
  })

  it('hides assign button and remove buttons when read-only', async () => {
    renderPanel({ canAssign: false })
    await waitFor(() => {
      expect(screen.getByTestId('linked-objects-list')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('linked-objects-assign-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('linked-object-remove-link-1')).not.toBeInTheDocument()
    expect(screen.queryByTestId('linked-object-remove-link-2')).not.toBeInTheDocument()
  })

  it('shows assign button when canAssign is true', async () => {
    renderPanel({ canAssign: true })
    await waitFor(() => {
      expect(screen.getByTestId('linked-objects-assign-button')).toBeInTheDocument()
    })
  })

  it('fires DELETE and bumps refresh store when removing a link', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      text: async () => '',
    })
    global.fetch = fetchSpy as unknown as typeof fetch

    const onChanged = vi.fn()
    renderPanel({ onChanged })

    await waitFor(() => {
      expect(screen.getByTestId('linked-object-remove-link-1')).toBeInTheDocument()
    })

    const user = userEvent.setup()
    const removeBtn = screen.getByTestId('linked-object-remove-link-1')
    await user.click(removeBtn)

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/semantic-links/link-1',
        expect.objectContaining({ method: 'DELETE' }),
      )
    })
    expect(bumpRefreshNonce).toHaveBeenCalledWith('semantic-link-mutated')
    expect(onChanged).toHaveBeenCalled()
  })

  it('renders empty state when no links exist', async () => {
    mockGet.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/semantic-links/iri/')) {
        return { data: [] }
      }
      return { data: [] }
    })
    renderPanel()
    await waitFor(() => {
      expect(
        screen.getByText(/No entities linked to this concept/i),
      ).toBeInTheDocument()
    })
    // No link rows should be rendered, even though the content container
    // (which holds the empty-state copy) is always present in the new shell.
    expect(screen.queryByTestId(/^linked-object-link-/)).not.toBeInTheDocument()
  })

  it('always shows the title row', async () => {
    renderPanel({ canAssign: false })
    const heading = await screen.findByText('Linked Entities')
    expect(heading).toBeInTheDocument()
    // Sanity: heading is in the same panel, not a stray match
    expect(within(heading.parentElement as HTMLElement).getByText('Linked Entities'))
      .toBeInTheDocument()
  })
})

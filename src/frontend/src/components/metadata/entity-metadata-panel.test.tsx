import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import EntityMetadataPanel from './entity-metadata-panel'

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { name?: string }) => (opts?.name ? `${key}:${opts.name}` : key),
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

// The info dialog is not under test and fetches on its own.
vi.mock('@/components/metadata/entity-info-dialog', () => ({ default: () => null }))

const merged = {
  rich_texts: [
    { id: 'own-note', entity_id: 'p-1', entity_type: 'data_product', title: 'Own note', content_markdown: 'x', level: 50 },
    { id: 'asset-note', entity_id: 'a-1', entity_type: 'asset', title: 'Dashboard preview', content_markdown: 'y', level: 10 },
  ],
  links: [],
  documents: [
    { id: 'snap', entity_id: 'a-1', entity_type: 'asset', title: 'Snapshot', original_filename: 's.png', storage_path: 'p', level: 10 },
  ],
  sources: { 'own-note': 'p-1', 'asset-note': 'asset:a-1', snap: 'asset:a-1' },
  source_names: { 'asset:a-1': 'Orders Overview' },
}

function mockFetch(mergedBody: unknown) {
  return vi.fn(async (url: string) => {
    const body = url.includes('/metadata/merged') ? mergedBody : []
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
}

describe('EntityMetadataPanel inherited section', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetch(merged))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists inherited items with their source, but not the entity\'s own items', async () => {
    render(<EntityMetadataPanel entityId="p-1" entityType="data_product" />)

    expect(await screen.findByText('inherited.title')).toBeInTheDocument()
    expect(screen.getByText('Dashboard preview')).toBeInTheDocument()
    expect(screen.getByText('Snapshot')).toBeInTheDocument()
    expect(screen.getAllByText('inherited.fromAsset:Orders Overview')).toHaveLength(2)
    expect(screen.queryByText('Own note')).not.toBeInTheDocument()
  })

  it('does not request merged metadata for entities that do not inherit', async () => {
    const fetchSpy = mockFetch(merged)
    vi.stubGlobal('fetch', fetchSpy)

    render(<EntityMetadataPanel entityId="a-1" entityType="asset" />)

    await waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    expect(fetchSpy.mock.calls.some(([url]) => String(url).includes('/metadata/merged'))).toBe(false)
    expect(screen.queryByText('inherited.title')).not.toBeInTheDocument()
  })
})

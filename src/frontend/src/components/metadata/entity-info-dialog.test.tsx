import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import EntityInfoDialog from './entity-info-dialog'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { name?: string }) => (opts?.name ? `${key}:${opts.name}` : key),
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

vi.mock('@/hooks/use-comments', () => ({
  useComments: () => ({
    createRating: vi.fn(),
    fetchRatingAggregation: vi.fn().mockResolvedValue(null),
  }),
}))

const merged = {
  rich_texts: [
    { id: 'asset-note', entity_id: 'a-1', entity_type: 'asset', title: 'Dashboard preview', content_markdown: 'Body', level: 10 },
  ],
  links: [],
  documents: [],
  sources: { 'asset-note': 'asset:a-1' },
  source_names: { 'asset:a-1': 'Orders Overview' },
}

function stubFetch() {
  const spy = vi.fn(async (url: string) => {
    const body = String(url).includes('/metadata/merged') ? merged : []
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', spy)
  return spy
}

const urls = (spy: ReturnType<typeof stubFetch>) => spy.mock.calls.map(([url]) => String(url))

describe('EntityInfoDialog metadata source', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses merged metadata for products without explicit contract ids', async () => {
    const spy = stubFetch()
    render(<EntityInfoDialog entityType="data_product" entityId="p-1" open onOpenChange={() => {}} />)

    await waitFor(() => expect(urls(spy).some(u => u.includes('/api/entities/data_product/metadata/merged'))).toBe(true))
    expect(urls(spy).some(u => u.includes('/rich-texts'))).toBe(false)
    expect(urls(spy).find(u => u.includes('/metadata/merged'))).not.toContain('max_level')
    expect((await screen.findAllByText(/inherited\.fromAsset:Orders Overview/)).length).toBeGreaterThan(0)
  })

  it('uses direct metadata for domains', async () => {
    const spy = stubFetch()
    render(<EntityInfoDialog entityType="data_domain" entityId="d-1" open onOpenChange={() => {}} />)

    await waitFor(() => expect(urls(spy).some(u => u.includes('/api/entities/data_domain/rich-texts'))).toBe(true))
    expect(urls(spy).some(u => u.includes('/metadata/merged'))).toBe(false)
  })
})

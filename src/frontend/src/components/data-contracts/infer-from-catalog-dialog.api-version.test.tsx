/**
 * Infer from Catalog asks for ODCS logical types for the contract's version: the
 * Databricks connector stores the Unity Catalog type name (`LONG`) as a column's
 * logical type, which isn't an ODCS type on any version.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: unknown) => (typeof fallback === 'string' ? fallback : _key),
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

const connection = { id: 'conn-1', name: 'uc', enabled: true }
const apiGet = vi.fn(async () => ({ data: [connection] }))
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: apiGet }) }))

vi.mock('@/components/schema-importer/schema-browser', () => ({
  default: ({ onSelectionChange }: { onSelectionChange: (p: Set<string>) => void }) => (
    <button onClick={() => onSelectionChange(new Set(['c.s.events']))}>select</button>
  ),
}))

import InferFromCatalogDialog from './infer-from-catalog-dialog'

describe('InferFromCatalogDialog logical types', () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({
    name: 'events',
    path: 'c.s.events',
    schema_info: { columns: [{ name: 'id', data_type: 'bigint', logical_type: 'integer' }] },
  }), { status: 200 }))

  beforeEach(() => {
    fetchMock.mockClear()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it.each([
    ['v3.0.2', '/api/schema-import/metadata/conn-1?path=c.s.events&odcs=true&api_version=v3.0.2'],
    [undefined, '/api/schema-import/metadata/conn-1?path=c.s.events&odcs=true'],
  ])('apiVersion %s asks %s', async (apiVersion, url) => {
    const onInfer = vi.fn()
    render(
      <InferFromCatalogDialog
        isOpen onOpenChange={vi.fn()} onInfer={onInfer} apiVersion={apiVersion}
      />,
    )

    fireEvent.click(await screen.findByText('select'))
    fireEvent.click(await screen.findByRole('button', { name: /inferSchemasButton/ }))

    await waitFor(() => expect(onInfer).toHaveBeenCalled())
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe(url)
    expect(onInfer.mock.calls[0][0][0].properties[0].logicalType).toBe('integer')
  })
})

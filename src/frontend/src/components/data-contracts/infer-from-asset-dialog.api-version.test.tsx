/**
 * Infer from Asset asks for the logical types of the contract's ODCS version, so a
 * v3.0.2 contract doesn't get timestamp / time (only ODCS v3.1.0 lists them).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

vi.mock('@/components/common/asset-selector', () => ({
  AssetSelector: ({ onConfirm }: { onConfirm: (a: unknown[]) => void }) => (
    <button onClick={() => onConfirm([{ id: 'a-1', name: 'events' }])}>confirm</button>
  ),
}))

import InferFromAssetDialog from './infer-from-asset-dialog'

describe('InferFromAssetDialog apiVersion', () => {
  const fetchMock = vi.fn(
    async () => new Response(JSON.stringify([{ name: 's' }]), { status: 200 }),
  )

  beforeEach(() => {
    fetchMock.mockClear()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it.each([
    ['v3.0.2', '/api/assets/a-1/infer-schema?api_version=v3.0.2'],
    [undefined, '/api/assets/a-1/infer-schema'],
  ])('apiVersion %s asks %s', async (apiVersion, url) => {
    const onInfer = vi.fn()
    render(
      <InferFromAssetDialog
        isOpen onOpenChange={vi.fn()} onInfer={onInfer} apiVersion={apiVersion}
      />,
    )

    fireEvent.click(screen.getByText('confirm'))

    await waitFor(() => expect(onInfer).toHaveBeenCalled())
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe(url)
  })
})

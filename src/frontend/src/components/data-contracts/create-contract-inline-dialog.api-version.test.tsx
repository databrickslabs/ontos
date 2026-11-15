/**
 * A contract created from the inline dialog (Link contract > Create New
 * Contract) gets a valid ODCS apiVersion: the dialog sent '3.0.2' (no "v"),
 * which the backend now reads.
 *
 * The Radix Select hangs in jsdom and the domain selector fetches, so both are stubbed.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

vi.mock('@/components/ui/domain-multi-selector', () => ({ default: () => null }))

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
  SelectContent: () => null,
  SelectItem: () => null,
}))

import CreateContractInlineDialog from './create-contract-inline-dialog'

describe('CreateContractInlineDialog', () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 'c-1' }), { status: 200 }))

  beforeEach(() => {
    fetchMock.mockClear()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('creates the contract with an ODCS apiVersion', async () => {
    const onSuccess = vi.fn()
    render(<CreateContractInlineDialog isOpen onOpenChange={vi.fn()} onSuccess={onSuccess} />)

    await userEvent.type(document.getElementById('name') as HTMLInputElement, 'Orders')
    await userEvent.click(screen.getByRole('button', { name: 'Create Contract' }))

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith('c-1'))
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/data-contracts')
    expect(JSON.parse(init.body as string).apiVersion).toBe('v3.1.0')
  })
})

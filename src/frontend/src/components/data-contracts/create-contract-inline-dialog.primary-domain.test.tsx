/**
 * The inline create sends the effective primary domain: when the prefilled primary is not
 * among the selected domains (its domain was dropped from the selection), the first selected
 * domain is sent, as the server now refuses a primary outside `domainIds`.
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

vi.mock('@/components/ui/domain-multi-selector', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/components/ui/domain-multi-selector')>()),
  default: () => null,
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
  SelectContent: () => null,
  SelectItem: () => null,
}))

import CreateContractInlineDialog from './create-contract-inline-dialog'

describe('CreateContractInlineDialog primary domain', () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 'c-1' }), { status: 200 }))

  beforeEach(() => {
    fetchMock.mockClear()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const submit = async (prefillData: Record<string, unknown>) => {
    const onSuccess = vi.fn()
    render(
      <CreateContractInlineDialog
        isOpen onOpenChange={vi.fn()} onSuccess={onSuccess} prefillData={prefillData}
      />,
    )
    await userEvent.type(document.getElementById('name') as HTMLInputElement, 'Orders')
    await userEvent.click(screen.getByRole('button', { name: 'Create Contract' }))
    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    return JSON.parse(init.body as string)
  }

  it('sends the first selected domain when the primary is not selected any more', async () => {
    const body = await submit({ domainIds: ['d1', 'd2'], primaryDomainId: 'removed' })

    expect(body.domainIds).toEqual(['d1', 'd2'])
    expect(body.primaryDomainId).toBe('d1')
  })

  it('keeps a primary that is selected', async () => {
    const body = await submit({ domainIds: ['d1', 'd2'], primaryDomainId: 'd2' })

    expect(body.primaryDomainId).toBe('d2')
  })

  it('sends no domains when none is selected', async () => {
    const body = await submit({ primaryDomainId: 'removed' })

    expect(body).not.toHaveProperty('domainIds')
    expect(body).not.toHaveProperty('primaryDomainId')
  })
})

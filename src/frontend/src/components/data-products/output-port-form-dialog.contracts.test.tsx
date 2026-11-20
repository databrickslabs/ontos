/**
 * The contract picker of an output port lists active or approved contracts and
 * says so, in the UI language (certified is not a status).
 */
import { screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderWithProviders } from '@/test/utils'
import OutputPortFormDialog from './output-port-form-dialog'

vi.mock('@/hooks/use-toast', () => ({
  default: () => ({ toast: vi.fn() }),
  useToast: () => ({ toast: vi.fn() }),
}))

const json = (body: unknown) => Promise.resolve({ ok: true, json: () => Promise.resolve(body) })

describe('OutputPortFormDialog contract filter', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.startsWith('/api/data-contracts')) {
        return json([{ id: 'c1', name: 'Orders', version: '1.0.0', status: 'certified' }])
      }
      return json([])
    }))
  })

  afterEach(() => vi.unstubAllGlobals())

  it('explains the filter without naming certified', async () => {
    renderWithProviders(
      <OutputPortFormDialog
        isOpen={true}
        onOpenChange={vi.fn()}
        onSubmit={vi.fn()}
        initial={{ name: 'out', version: '1.0.0', contractId: 'c1' } as any}
      />,
    )

    expect(
      await screen.findByText('Only showing active/approved contracts'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/certified/)).not.toBeInTheDocument()
  })
})

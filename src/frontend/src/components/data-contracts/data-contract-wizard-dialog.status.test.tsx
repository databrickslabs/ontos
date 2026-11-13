/**
 * The wizard offers the contract lifecycle statuses: `archived` is not one.
 */
import { screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { renderWithProviders } from '@/test/utils'
import DataContractWizardDialog from './data-contract-wizard-dialog'

vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => ({ domains: [], loading: false, refetch: vi.fn() }),
}))

vi.mock('@/hooks/use-toast', () => ({
  default: () => ({ toast: vi.fn() }),
  useToast: () => ({ toast: vi.fn() }),
}))

vi.mock('./infer-from-asset-dialog', () => ({ default: () => null }))

vi.mock('@/components/business-concepts/business-concepts-display', () => ({
  default: () => <div data-testid="business-concepts-display" />,
}))

describe('DataContractWizardDialog status', () => {
  it('offers the lifecycle statuses, without archived', () => {
    renderWithProviders(
      <DataContractWizardDialog isOpen={true} onOpenChange={vi.fn()} onSubmit={vi.fn()} />,
    )

    const statusSelect = screen
      .getAllByRole('combobox')
      .find((el) => el.textContent === 'draft')
    expect(statusSelect).toBeDefined()
    fireEvent.click(statusSelect!)
    const options = screen.getAllByRole('option').map((o) => o.textContent)
    expect(options).toEqual([
      'draft', 'proposed', 'under_review', 'approved', 'active', 'deprecated', 'retired',
    ])
  })
})

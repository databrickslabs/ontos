/**
 * The wizard offers the stages of the default contract lifecycle, from the
 * API: `archived` is not one.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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

const STAGES = ['draft', 'proposed', 'under_review', 'approved', 'active', 'deprecated', 'retired']

describe('DataContractWizardDialog status', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve({
      ok: true,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: () => Promise.resolve(url.startsWith('/api/lifecycle-stage-groups') ? [{
        id: 'g', name: 'Default data contract lifecycle', entity_type: 'data_contract',
        is_default_for_type: true, transitions: [],
        stages: STAGES.map((key, order) => ({
          key, label: key, category: 'draft', color: null, order, is_initial: order === 0,
        })),
      }, {
        id: 'g-live', name: 'Certified feeds', entity_type: 'data_contract',
        is_default_for_type: false, transitions: [],
        stages: ['intake', 'live'].map((key, order) => ({
          key, label: key, category: order ? 'active' : 'draft', color: null, order,
          is_initial: order === 0,
        })),
      }] : []),
    })))
  })

  afterEach(() => vi.unstubAllGlobals())

  it('offers the lifecycle statuses, without archived', async () => {
    renderWithProviders(
      <DataContractWizardDialog isOpen={true} onOpenChange={vi.fn()} onSubmit={vi.fn()} />,
    )
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/api/lifecycle-stage-groups?entity_type=data_contract',
    ))
    await new Promise((resolve) => setTimeout(resolve, 0))

    const statusSelect = screen
      .getAllByRole('combobox')
      .find((el) => el.textContent === 'draft')
    expect(statusSelect).toBeDefined()
    fireEvent.click(statusSelect!)
    const options = screen.getAllByRole('option').map((o) => o.textContent)
    expect(options).toEqual(STAGES)
  })

  it('offers an edited contract the stages of its own group', async () => {
    renderWithProviders(
      <DataContractWizardDialog isOpen={true} onOpenChange={vi.fn()} onSubmit={vi.fn()}
        initial={{ name: 'Feed', version: '1.0.0', status: 'live',
          lifecycle_stage_group_id: 'g-live' }} />,
    )
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/api/lifecycle-stage-groups?entity_type=data_contract',
    ))
    await new Promise((resolve) => setTimeout(resolve, 0))

    const statusSelect = screen
      .getAllByRole('combobox')
      .find((el) => el.textContent === 'live')
    expect(statusSelect).toBeDefined()
    fireEvent.click(statusSelect!)
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['intake', 'live'])
  })
})

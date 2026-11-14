import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ---- Mocks ----------------------------------------------------------------

const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPut = vi.fn()

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({
    get: mockGet,
    post: mockPost,
    put: mockPut,
    patch: vi.fn(),
    delete: vi.fn(),
    loading: false,
  }),
}))

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

vi.mock('@/components/ui/domain-multi-selector', () => ({
  default: () => <div data-testid="domains" />,
}))

// The real picker pulls in Radix popover/command, which hangs in jsdom. The stub
// shows the selected FQNs and drives onChange like the picker does.
vi.mock('@/components/ui/tag-selector', async () => {
  const actual = await vi.importActual<typeof import('@/components/ui/tag-selector')>('@/components/ui/tag-selector')
  return {
    ...actual,
    default: ({ value, onChange }: { value: { fqn: string; value?: string }[]; onChange: (tags: unknown[]) => void }) => (
      <>
        <ul aria-label="selected-tags">
          {value.map(tag => <li key={tag.fqn}>{tag.fqn}</li>)}
        </ul>
        <button onClick={() => onChange([...value, { fqn: 'governance/pii' }])}>add-tag</button>
      </>
    ),
  }
})

import { AssetFormDialog } from './asset-form-dialog'
import type { AssetRead } from '@/types/asset'

const asset = {
  id: 'asset-1',
  name: 'customers',
  asset_type_id: 'type-1',
  asset_type_name: 'Table',
  status: 'active',
  relationships: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  domains: [],
  domain_ids: [],
  tags: [
    {
      tag_id: 'tag-1',
      tag_name: 'lookup',
      namespace_id: 'ns-1',
      namespace_name: 'default',
      status: 'active',
      fully_qualified_name: 'default/lookup',
      assigned_at: '2026-01-01T00:00:00Z',
    },
  ],
} as unknown as AssetRead

function renderEdit() {
  return render(
    <AssetFormDialog
      isOpen
      onOpenChange={vi.fn()}
      onSuccess={vi.fn()}
      assetTypeId="type-1"
      assetTypeName="Table"
      asset={asset}
    />,
  )
}

describe('AssetFormDialog tags', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPut.mockResolvedValue({ data: asset, error: null })
  })

  it('shows the asset tags in the shared picker', () => {
    renderEdit()

    expect(screen.getByLabelText('selected-tags')).toHaveTextContent('default/lookup')
  })

  it('saves the tags unchanged as FQNs, so stored values are kept', async () => {
    const user = userEvent.setup()
    renderEdit()

    await user.click(screen.getByRole('button', { name: 'common:actions.saveChanges' }))

    await waitFor(() => expect(mockPut).toHaveBeenCalled())
    const [url, payload] = mockPut.mock.calls[0]
    expect(url).toBe('/api/assets/asset-1')
    expect(payload.tags).toEqual([{ tag_fqn: 'default/lookup' }])
  })

  it('sends a tag added in the picker with the update', async () => {
    const user = userEvent.setup()
    renderEdit()

    await user.click(screen.getByRole('button', { name: 'add-tag' }))
    await user.click(screen.getByRole('button', { name: 'common:actions.saveChanges' }))

    await waitFor(() => expect(mockPut).toHaveBeenCalled())
    const payload = mockPut.mock.calls[0][1]
    expect(payload.tags).toEqual([{ tag_fqn: 'default/lookup' }, { tag_fqn: 'governance/pii' }])
  })
})

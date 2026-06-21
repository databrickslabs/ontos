import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { TooltipProvider } from '@/components/ui/tooltip'
import { FeatureAccessLevel } from '@/types/feature-access-levels'

// ---- Mocks ----------------------------------------------------------------

const mockGet = vi.fn()
const mockPost = vi.fn()

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({
    get: mockGet,
    post: mockPost,
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    loading: false,
  }),
}))

const toastSpy = vi.fn()
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: toastSpy }),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

let mockLevel: FeatureAccessLevel = FeatureAccessLevel.READ_WRITE
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    hasPermission: (_feature: string, required: FeatureAccessLevel) => {
      const order: Record<string, number> = {
        [FeatureAccessLevel.NONE]: 0,
        [FeatureAccessLevel.READ_ONLY]: 1,
        [FeatureAccessLevel.READ_WRITE]: 3,
        [FeatureAccessLevel.ADMIN]: 4,
      }
      return (order[mockLevel] ?? 0) >= (order[required] ?? 0)
    },
  }),
}))

// TagSelector pulls in Radix popover/command which hangs in jsdom; stub it with
// a simple control that drives the onChange contract this panel relies on.
vi.mock('@/components/ui/tag-selector', () => ({
  default: ({ onChange }: { onChange: (tags: string[]) => void }) => (
    <button onClick={() => onChange(['governance.pii'])}>add-tag</button>
  ),
}))

// TagChip fetches global settings on mount; stub the store so jsdom does not
// attempt a real network request for the relative /api/settings URL.
vi.mock('@/stores/app-settings-store', () => ({
  useAppSettingsStore: () => ({ tagDisplayFormat: 'long', fetchSettings: vi.fn() }),
}))

import EntityTagsPanel from './entity-tags-panel'

const sampleTags = [
  {
    tag_id: 'tag-1',
    tag_name: 'pii',
    namespace_id: 'ns-1',
    namespace_name: 'governance',
    status: 'active',
    fully_qualified_name: 'governance.pii',
    assigned_at: '2026-01-01T00:00:00Z',
  },
]

function renderPanel() {
  return render(
    <BrowserRouter>
      <TooltipProvider>
        <EntityTagsPanel entityId="samples.nyctaxi.trips" entityType="catalog-object" />
      </TooltipProvider>
    </BrowserRouter>,
  )
}

beforeEach(() => {
  mockGet.mockReset()
  mockPost.mockReset()
  toastSpy.mockReset()
  mockLevel = FeatureAccessLevel.READ_WRITE
})

describe('EntityTagsPanel', () => {
  it('loads assigned tags from the entity-tags endpoint', async () => {
    mockGet.mockResolvedValue({ data: sampleTags })
    renderPanel()

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(
        '/api/entities/catalog-object/samples.nyctaxi.trips/tags',
      )
    })
    expect(await screen.findByText('governance.pii')).toBeInTheDocument()
  })

  it('applies a tag via the tags:set endpoint as {tag_fqn} payload', async () => {
    mockGet.mockResolvedValue({ data: [] })
    mockPost.mockResolvedValue({ data: sampleTags })
    renderPanel()

    // Enter edit mode
    await userEvent.click(await screen.findByRole('button', { name: 'tags.edit' }))
    // Select a tag via the stubbed TagSelector
    await userEvent.click(screen.getByText('add-tag'))
    // Save
    await userEvent.click(screen.getByText('tags.save'))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/api/entities/catalog-object/samples.nyctaxi.trips/tags:set',
        [{ tag_fqn: 'governance.pii' }],
      )
    })
  })

  it('hides the edit control without tags write permission', async () => {
    mockLevel = FeatureAccessLevel.READ_ONLY
    mockGet.mockResolvedValue({ data: [] })
    renderPanel()

    await waitFor(() => expect(mockGet).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'tags.edit' })).not.toBeInTheDocument()
  })
})

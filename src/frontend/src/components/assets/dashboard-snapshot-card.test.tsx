import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import DashboardSnapshotCard from './dashboard-snapshot-card'

const mockGet = vi.fn()
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: vi.fn(), put: vi.fn() }),
}))
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))

const response = (overrides = {}) => ({
  data: {
    snapshot: { status: 'ok', document_id: 'doc-1', captured_at: '2026-11-05T12:00:00+00:00', source: 'view_image' },
    opt_out: false,
    supported: true,
    ...overrides,
  },
})

describe('DashboardSnapshotCard', () => {
  beforeEach(() => mockGet.mockReset())

  it('shows the stored snapshot with its status and live link', async () => {
    mockGet.mockResolvedValue(response())
    render(<DashboardSnapshotCard assetId="a-1" assetTypeName="Dashboard" dashboardUrl="https://t/v" canWrite />)

    const img = await screen.findByAltText('snapshot.imageAlt')
    expect(img.getAttribute('src')).toContain('/api/documents/doc-1/content')
    expect(screen.getByText('snapshot.status.ok')).toBeInTheDocument()
    expect(screen.getByText('snapshot.openLive').closest('a')?.getAttribute('href')).toBe('https://t/v')
    expect(screen.getByText('snapshot.refresh')).toBeInTheDocument()
    expect(screen.getByText('snapshot.optOut')).toBeInTheDocument()
  })

  it('lists user-filter risks and hides write controls for readers', async () => {
    mockGet.mockResolvedValue(response({
      snapshot: { status: 'skipped_user_filters', risks: ["'Region' uses USERNAME()"] },
    }))
    render(<DashboardSnapshotCard assetId="a-1" assetTypeName="Dashboard" canWrite={false} />)

    expect(await screen.findByText("'Region' uses USERNAME()")).toBeInTheDocument()
    expect(screen.queryByText('snapshot.refresh')).not.toBeInTheDocument()
    expect(screen.queryByText('snapshot.optOut')).not.toBeInTheDocument()
  })

  it('renders nothing for other asset types', async () => {
    const { container } = render(<DashboardSnapshotCard assetId="a-1" assetTypeName="Table" canWrite />)
    await waitFor(() => expect(mockGet).not.toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})

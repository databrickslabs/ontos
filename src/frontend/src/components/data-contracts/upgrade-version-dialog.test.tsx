/**
 * Tests for UpgradeVersionDialog (ODCS v3.2.0 upgrade flow).
 */
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderWithProviders } from '@/test/utils'
import UpgradeVersionDialog from './upgrade-version-dialog'

const mockToast = vi.fn()
vi.mock('@/hooks/use-toast', () => ({
  default: () => ({ toast: mockToast }),
  useToast: () => ({ toast: mockToast }),
}))

describe('UpgradeVersionDialog', () => {
  beforeEach(() => {
    mockToast.mockReset()
    // Default: versions endpoint returns the supported list.
    global.fetch = vi.fn(async (url: any) => {
      if (String(url).includes('/meta/odcs-versions')) {
        return {
          ok: true,
          json: async () => ({ supported: ['v3.2.0', 'v3.1.0', 'v3.0.2', 'v3.0.1'], latest: 'v3.2.0', default: 'v3.2.0' }),
        } as any
      }
      return { ok: true, json: async () => ({ id: 'new-id', version: '1.1.0' }) } as any
    }) as any
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('offers only newer versions as upgrade targets and posts the upgrade', async () => {
    const onSuccess = vi.fn()
    renderWithProviders(
      <UpgradeVersionDialog
        isOpen
        onOpenChange={() => {}}
        contractId="c1"
        contractName="cust"
        currentApiVersion="v3.1.0"
        onSuccess={onSuccess}
      />,
    )

    // Default target should be the latest available upgrade.
    await waitFor(() => expect(screen.getByText('v3.2.0')).toBeInTheDocument())

    const submit = screen.getByRole('button', { name: /Create Upgraded Draft/i })
    fireEvent.click(submit)

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith('new-id'))

    const upgradeCall = (global.fetch as any).mock.calls.find((c: any[]) =>
      String(c[0]).endsWith('/data-contracts/c1/upgrade'),
    )
    expect(upgradeCall).toBeTruthy()
    const body = JSON.parse(upgradeCall[1].body)
    expect(body.targetApiVersion).toBe('v3.2.0')
    expect(body.versionBump).toBe('minor')
  })

  it('shows "already up to date" when on the latest version', async () => {
    renderWithProviders(
      <UpgradeVersionDialog
        isOpen
        onOpenChange={() => {}}
        contractId="c1"
        contractName="cust"
        currentApiVersion="v3.2.0"
        onSuccess={vi.fn()}
      />,
    )
    await waitFor(() => expect(screen.getByText(/Already up to date/i)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Create Upgraded Draft/i })).toBeDisabled()
  })
})

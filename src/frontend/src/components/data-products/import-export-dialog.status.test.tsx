/**
 * The ODPS import dialog accepts every status an Ontos export carries.
 */
import { screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/utils'
import ImportExportDialog from './import-export-dialog'

const mockToast = vi.fn()

vi.mock('@/hooks/use-toast', () => ({
  default: () => ({ toast: mockToast }),
  useToast: () => ({ toast: mockToast }),
}))

const odps = (status: string) => JSON.stringify({
  apiVersion: 'v1.0.0', kind: 'DataProduct', id: 'p1', status,
})

function validate(status: string) {
  renderWithProviders(<ImportExportDialog isOpen={true} onOpenChange={vi.fn()} />)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: odps(status) } })
  fireEvent.click(screen.getByRole('button', { name: /Validate/ }))
}

describe('ImportExportDialog status validation', () => {
  beforeEach(() => mockToast.mockClear())

  it.each(['sandbox', 'under_review', 'approved'])(
    'accepts the %s status of an Ontos export',
    (status) => {
      validate(status)
      expect(screen.queryByText(/Invalid status/)).not.toBeInTheDocument()
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Validation Passed' }),
      )
    },
  )

  it('still refuses a status that is no lifecycle status', () => {
    validate('certified')
    expect(screen.getByText(/Invalid status: certified/)).toBeInTheDocument()
  })
})

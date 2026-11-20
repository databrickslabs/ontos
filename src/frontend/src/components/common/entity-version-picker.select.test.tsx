/**
 * Picking a contract closes the list. In entity mode the list stayed open
 * after a pick (for the version sub-picker, which renders below the field, not
 * in the list), covering the dialog under it.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EntityVersionPicker } from './entity-version-picker'

const ROWS = [
  { id: 'c-1', name: 'Orders', version: '1.0.0', status: 'active', versionFamilyId: 'f-1' },
]

describe('EntityVersionPicker pick', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(ROWS), { status: 200 })))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('closes the list after a contract is picked', async () => {
    const onChange = vi.fn()
    render(<EntityVersionPicker entityKind="contract" value={null} onChange={onChange} />)

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByRole('option', { name: /Orders/ }))

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ scope: 'entity', entityId: 'c-1' }),
    )
    await waitFor(() => expect(screen.queryByRole('option')).not.toBeInTheDocument())
  })
})

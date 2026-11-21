/** `timezone` is a boolean on ODCS v3.1 timestamp / time columns, a zone name on a date. */
import { screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { renderWithProviders } from '@/test/utils'
import SchemaPropertyEditor from './schema-property-editor'
import type { ColumnProperty } from '@/types/data-contract'

vi.mock('@/hooks/use-toast', () => ({
  default: () => ({ toast: vi.fn() }),
  useToast: () => ({ toast: vi.fn() }),
}))

vi.mock('@/components/business-concepts/business-concepts-display', () => ({
  default: () => <div />,
}))

function column(logicalType: string, timezone: string | boolean | undefined): ColumnProperty {
  return { name: 'col', logicalType, timezone } as ColumnProperty
}

function openColumn(prop: ColumnProperty) {
  const onChange = vi.fn()
  renderWithProviders(
    <SchemaPropertyEditor properties={[prop]} onChange={onChange} apiVersion="v3.1.0" />,
  )
  fireEvent.click(screen.getByText('col'))
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'Constraints' }), { button: 0 })
  return onChange
}

function saved(onChange: ReturnType<typeof vi.fn>): ColumnProperty {
  fireEvent.click(screen.getByRole('button', { name: /update column/i }))
  return onChange.mock.calls[0][0][0]
}

describe('SchemaPropertyEditor timezone', () => {
  it('shows a stored boolean on a timestamp as a ticked checkbox without crashing', () => {
    openColumn(column('timestamp', true))

    expect(screen.getByRole('checkbox', { name: 'Timezone' })).toBeChecked()
    expect(screen.queryByPlaceholderText('e.g., UTC')).not.toBeInTheDocument()
  })

  it('clears the value when the box is unticked', () => {
    const onChange = openColumn(column('timestamp', true))

    fireEvent.click(screen.getByRole('checkbox', { name: 'Timezone' }))

    expect(saved(onChange).timezone).toBeUndefined()
  })

  it('saves a ticked box as true', () => {
    const onChange = openColumn(column('time', undefined))

    fireEvent.click(screen.getByRole('checkbox', { name: 'Timezone' }))

    expect(saved(onChange).timezone).toBe(true)
  })

  it('drops a zone name stored on a timestamp', () => {
    const onChange = openColumn(column('timestamp', 'UTC'))

    expect(screen.getByRole('checkbox', { name: 'Timezone' })).not.toBeChecked()
    expect(saved(onChange).timezone).toBeUndefined()
  })

  it('keeps the free-text zone name on a date', () => {
    const onChange = openColumn(column('date', 'UTC'))

    expect(screen.getByPlaceholderText('e.g., UTC')).toHaveValue('UTC')
    expect(screen.queryByRole('checkbox', { name: 'Timezone' })).not.toBeInTheDocument()
    expect(saved(onChange).timezone).toBe('UTC')
  })

  it('drops a zone name left on a column whose type takes no timezone', () => {
    const onChange = openColumn(column('string', 'UTC'))

    expect(saved(onChange).timezone).toBeUndefined()
  })
})

/**
 * The contract / product picker speaks the user's language: its texts used to
 * interpolate the raw kind ("Pesquisar contract…" in Portuguese).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18n from '@/i18n/config'
import { EntityVersionPicker } from './entity-version-picker'

describe('EntityVersionPicker texts', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })))
  })

  afterEach(async () => {
    vi.unstubAllGlobals()
    await i18n.changeLanguage('en')
  })

  it('names contracts in Portuguese', async () => {
    await i18n.changeLanguage('pt')
    render(<EntityVersionPicker entityKind="contract" value={null} onChange={vi.fn()} />)

    const trigger = screen.getByRole('combobox')
    await userEvent.click(trigger)

    expect(trigger).toHaveTextContent('Selecione um contrato…')
    expect(screen.getByPlaceholderText('Pesquisar contratos…')).toBeInTheDocument()
    expect(await screen.findByText('Nenhum contrato correspondente.')).toBeInTheDocument()
  })

  it('names products in English', async () => {
    render(<EntityVersionPicker entityKind="product" value={null} onChange={vi.fn()} />)

    const trigger = screen.getByRole('combobox')
    await userEvent.click(trigger)

    expect(trigger).toHaveTextContent('Select a product…')
    expect(screen.getByPlaceholderText('Search products…')).toBeInTheDocument()
    expect(await screen.findByText('No matching products.')).toBeInTheDocument()
  })
})

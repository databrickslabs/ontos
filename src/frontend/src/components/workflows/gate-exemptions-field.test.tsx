/**
 * The designer field that switches a status gate off per domain, data product
 * or data contract (part of #1114).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => ({
    domains: [{ id: 'dom-sales', name: 'Sales' }, { id: 'dom-fin', name: 'Finance' }],
    loading: false,
    getDomainName: (id: string) => ({ 'dom-sales': 'Sales', 'dom-fin': 'Finance' } as Record<string, string>)[id],
  }),
}));

import i18n from '@/i18n/config';
import GateExemptionsField, { EMPTY_GATE_EXEMPTIONS, missingExemptionIds, toOptions } from './gate-exemptions-field';

const lists: Record<string, unknown> = {
  '/api/data-products': [{ id: 'p-1', name: 'Orders' }, { id: 'p-2', name: 'Payments' }],
  '/api/data-contracts': { items: [{ id: 'c-1', name: 'Orders Contract' }] },
};

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((url: string) =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(lists[url] ?? []) })));
});

afterEach(async () => {
  vi.unstubAllGlobals();
  await i18n.changeLanguage('en');
});

describe('toOptions', () => {
  it('reads a plain array or {items}, and keeps only rows with an id', () => {
    expect(toOptions([{ id: 'a', name: 'A' }, { name: 'no id' }])).toEqual([{ id: 'a', name: 'A' }]);
    expect(toOptions({ items: [{ id: 'b' }] })).toEqual([{ id: 'b', name: 'b' }]);
    expect(toOptions(null)).toEqual([]);
  });
});

describe('GateExemptionsField', () => {
  it('shows the selected entities by name and removes one', async () => {
    const onChange = vi.fn();
    render(
      <GateExemptionsField
        value={{ domains: ['dom-sales'], data_products: ['p-2'], data_contracts: [] }}
        onChange={onChange}
      />,
    );
    expect(screen.getByText('Switched off for')).toBeInTheDocument();
    expect(screen.getByTestId('gate-disabled-domains-selected')).toHaveTextContent('Sales');
    await waitFor(() =>
      expect(screen.getByTestId('gate-disabled-products-selected')).toHaveTextContent('Payments'));
    fireEvent.click(screen.getByRole('button', { name: 'Remove Sales' }));
    expect(onChange).toHaveBeenCalledWith({ domains: [], data_products: ['p-2'], data_contracts: [] });
  });

  it('adds a domain from the picker', async () => {
    const onChange = vi.fn();
    render(<GateExemptionsField value={EMPTY_GATE_EXEMPTIONS} onChange={onChange} />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Domains' }));
    fireEvent.click(await screen.findByText('Finance'));
    expect(onChange).toHaveBeenCalledWith({ domains: ['dom-fin'], data_products: [], data_contracts: [] });
  });

  it('is translated', async () => {
    await i18n.changeLanguage('pt');
    render(<GateExemptionsField value={EMPTY_GATE_EXEMPTIONS} onChange={vi.fn()} />);
    expect(screen.getByText('Desligado para')).toBeInTheDocument();
    expect(screen.getByText('Produtos de dados')).toBeInTheDocument();
    expect(screen.getAllByText('Nenhum')).toHaveLength(3);
  });

  it('marks a selected entity that no longer exists and reports it', async () => {
    await i18n.changeLanguage('pt');
    const onMissingChange = vi.fn();
    render(
      <GateExemptionsField
        value={{ domains: ['dom-gone'], data_products: ['p-1', 'p-gone'], data_contracts: [] }}
        onChange={vi.fn()}
        onMissingChange={onMissingChange}
      />,
    );
    await waitFor(() => expect(onMissingChange).toHaveBeenLastCalledWith(['dom-gone', 'p-gone']));
    expect(screen.getByTestId('gate-disabled-domains-selected')).toHaveTextContent('dom-gone (não existe mais)');
    expect(screen.getByTestId('gate-disabled-products-selected')).toHaveTextContent('Orders');
    expect(screen.getByTestId('gate-disabled-products-selected')).toHaveTextContent('p-gone (não existe mais)');
  });

  it('shortens a long missing id so the whole note stays visible', async () => {
    const id = 'd13d7c8f-fd8e-4f02-b5cd-180bf276ae10';
    render(
      <GateExemptionsField
        value={{ domains: [id], data_products: [], data_contracts: [] }}
        onChange={vi.fn()}
      />,
    );
    const selected = screen.getByTestId('gate-disabled-domains-selected');
    await waitFor(() => expect(selected).toHaveTextContent('d13d7c8f… (no longer exists)'));
    expect(selected.querySelector(`[title="${id}"]`)).not.toBeNull();
  });

  it('reports nothing missing when a list cannot be read', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) })));
    const onMissingChange = vi.fn();
    render(
      <GateExemptionsField
        value={{ domains: [], data_products: ['p-1'], data_contracts: [] }}
        onChange={vi.fn()}
        onMissingChange={onMissingChange}
      />,
    );
    await waitFor(() => expect(onMissingChange).toHaveBeenCalled());
    expect(onMissingChange).not.toHaveBeenCalledWith(['p-1']);
    expect(screen.getByTestId('gate-disabled-products-selected')).toHaveTextContent('p-1');
  });
});

describe('missingExemptionIds', () => {
  it('lists the ids not in their loaded list, and none for a list not loaded', () => {
    const value = { domains: ['d-1', 'd-x'], data_products: ['p-x'], data_contracts: ['c-x'] };
    expect(missingExemptionIds(value, {
      domains: [{ id: 'd-1', name: 'D' }], data_products: [], data_contracts: null,
    })).toEqual(['d-x', 'p-x']);
  });
});

describe('the save message for missing exemptions', () => {
  it('is one sentence with its count, in each language', async () => {
    expect(i18n.t('workflows:designer.triggerConfig.disabledFor.missingOnSave', { count: 1 }))
      .toBe('The gate is switched off for 1 item that no longer exists. Remove it and save again.');
    await i18n.changeLanguage('pt');
    expect(i18n.t('workflows:designer.triggerConfig.disabledFor.missingOnSave', { count: 2 }))
      .toBe('O gate está desligado para 2 itens que não existem mais. Remova-os e salve de novo.');
  });
});

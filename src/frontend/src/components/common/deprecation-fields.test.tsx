import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import DeprecationFields, {
  EMPTY_DEPRECATION,
  deprecationPayload,
} from './deprecation-fields';

const get = vi.fn();

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get }),
}));

const PRODUCTS = [
  { id: 'self', name: 'Orders v1', version: '1.0.0', status: 'active' },
  { id: 'next', name: 'Orders v2', version: '2.0.0', status: 'active' },
  { id: 'gone', name: 'Orders v0', version: '0.1.0', status: 'retired' },
];

describe('DeprecationFields', () => {
  beforeAll(() => {
    // Radix Select needs pointer capture and scrollIntoView, which jsdom lacks.
    Element.prototype.hasPointerCapture = () => false;
    Element.prototype.releasePointerCapture = () => {};
    Element.prototype.scrollIntoView = () => {};
  });

  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue({ data: PRODUCTS });
  });

  it('asks for a reason, a sunset date and a replacement', async () => {
    renderWithProviders(
      <DeprecationFields
        entityType="data_product"
        entityId="self"
        value={EMPTY_DEPRECATION}
        onChange={vi.fn()}
      />,
    );

    expect(document.getElementById('deprecation-reason')).toBeInTheDocument();
    expect(document.getElementById('deprecation-sunset-date')).toHaveAttribute('type', 'date');
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/data-products'));
  });

  it('offers other non-retired entities of the same type as replacements', async () => {
    renderWithProviders(
      <DeprecationFields
        entityType="data_product"
        entityId="self"
        value={EMPTY_DEPRECATION}
        onChange={vi.fn()}
      />,
    );
    await waitFor(() => expect(get).toHaveBeenCalled());

    const trigger = document.getElementById('deprecation-replacement')!;
    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: 'mouse' });
    fireEvent.click(trigger);

    await waitFor(() => expect(screen.getByText('Orders v2 (2.0.0)')).toBeInTheDocument());
    expect(screen.queryByText('Orders v1 (1.0.0)')).not.toBeInTheDocument();
    expect(screen.queryByText('Orders v0 (0.1.0)')).not.toBeInTheDocument();
  });

  it('loads contracts for a data contract', async () => {
    renderWithProviders(
      <DeprecationFields
        entityType="data_contract"
        entityId="c1"
        value={EMPTY_DEPRECATION}
        onChange={vi.fn()}
      />,
    );

    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/data-contracts'));
  });
});

describe('deprecationPayload', () => {
  it('trims the reason and omits empty optional fields', () => {
    expect(
      deprecationPayload({ deprecationReason: '  Replaced  ', sunsetDate: '', replacementId: '' }),
    ).toEqual({
      deprecation_reason: 'Replaced',
      sunset_date: undefined,
      replacement_id: undefined,
    });
  });

  it('keeps the sunset date and replacement when set', () => {
    expect(
      deprecationPayload({
        deprecationReason: 'Replaced',
        sunsetDate: '2027-01-31',
        replacementId: 'next',
      }),
    ).toEqual({
      deprecation_reason: 'Replaced',
      sunset_date: '2027-01-31',
      replacement_id: 'next',
    });
  });
});

import { screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import DeprecationNotice from './deprecation-notice';
import DeprecationFields, {
  EMPTY_DEPRECATION,
  requestedDeprecationPayload,
} from './deprecation-fields';

const get = vi.fn();

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get }),
}));

describe('DeprecationNotice', () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue({ data: { name: 'Orders v2' } });
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('shows the reason, the sunset date and a link to the replacement', async () => {
    await i18n.changeLanguage('pt');
    renderWithProviders(
      <DeprecationNotice
        entityType="data_product"
        status="deprecated"
        reason="Replaced by v2"
        sunsetDate="2027-01-31"
        replacementId="p-2"
      />,
    );

    expect(screen.getByText('Obsoleto')).toBeInTheDocument();
    expect(screen.getByTestId('deprecation-reason')).toHaveTextContent('Replaced by v2');
    expect(screen.getByTestId('deprecation-sunset-date')).toHaveTextContent('2027-01-31');
    await waitFor(() =>
      expect(screen.getByTestId('deprecation-replacement')).toHaveTextContent('Orders v2'),
    );
    expect(screen.getByTestId('deprecation-replacement'))
      .toHaveAttribute('href', '/data-products/p-2');
    expect(get).toHaveBeenCalledWith('/api/data-products/p-2');
  });

  it('links a contract replacement to the contract page', async () => {
    renderWithProviders(
      <DeprecationNotice entityType="data_contract" status="retired" replacementId="c-9" />,
    );

    expect(screen.getByText('Retired')).toBeInTheDocument();
    expect(screen.getByTestId('deprecation-reason')).toHaveTextContent('No reason recorded');
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/data-contracts/c-9'));
    expect(screen.getByTestId('deprecation-replacement'))
      .toHaveAttribute('href', '/data-contracts/c-9');
  });

  it('shows nothing for an entity that is not deprecated or retired', () => {
    const { container } = renderWithProviders(
      <DeprecationNotice entityType="data_product" status="active" reason="stale" />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(get).not.toHaveBeenCalled();
  });
});

describe('Requested deprecation fields', () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue({ data: [] });
  });

  it('hides the reason when the justification is the reason', () => {
    renderWithProviders(
      <DeprecationFields
        entityType="data_product"
        entityId="self"
        value={EMPTY_DEPRECATION}
        onChange={vi.fn()}
        hideReason
      />,
    );

    expect(document.getElementById('deprecation-reason')).toBeNull();
    expect(document.getElementById('deprecation-sunset-date')).toBeInTheDocument();
    expect(document.getElementById('deprecation-replacement')).toBeInTheDocument();
  });

  it('sends only the sunset date and the replacement with a request', () => {
    expect(
      requestedDeprecationPayload({
        deprecationReason: 'x', sunsetDate: '2027-01-31', replacementId: 'p-2',
      }),
    ).toEqual({ sunset_date: '2027-01-31', replacement_id: 'p-2' });
    expect(requestedDeprecationPayload(EMPTY_DEPRECATION)).toEqual({
      sunset_date: undefined,
      replacement_id: undefined,
    });
  });
});

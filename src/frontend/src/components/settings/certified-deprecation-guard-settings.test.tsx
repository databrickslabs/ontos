/**
 * The certified deprecation guard's switch: loaded and saved through
 * /api/certified-deprecation-guard, with the guard's own hint, and the
 * backend's `gate_exemption_not_found` shown in the UI language.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import CertifiedDeprecationGuardSettings, {
  GUARD_URL,
} from './certified-deprecation-guard-settings';

const mockGet = vi.fn();
const mockPut = vi.fn();
const mockToast = vi.fn();

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mockToast }) }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: mockGet, put: mockPut }) }));
vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => ({ domains: [{ id: 'd-sales', name: 'Sales' }], loading: false, error: null }),
}));

const SAVED = { domains: ['d-sales'], data_products: [], data_contracts: [] };

describe('CertifiedDeprecationGuardSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ data: SAVED });
    // The product and contract pickers read their lists with fetch
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => [] })));
  });

  afterEach(async () => {
    vi.unstubAllGlobals();
    await i18n.changeLanguage('en');
  });

  it('shows the stored switch with the guard hint and saves it', async () => {
    mockPut.mockResolvedValue({ data: SAVED });
    renderWithProviders(<CertifiedDeprecationGuardSettings />);

    expect(await screen.findByText('Sales')).toBeInTheDocument();
    expect(screen.getByText(i18n.t('workflow-gates:certifiedGuard.hint'))).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith(GUARD_URL);

    fireEvent.click(screen.getByRole('button', { name: i18n.t('common:actions.save') }));

    await waitFor(() => expect(mockPut).toHaveBeenCalledWith(GUARD_URL, SAVED));
    expect(mockToast).toHaveBeenCalledWith({
      title: i18n.t('workflow-gates:certifiedGuard.saved'),
    });
  });

  it('shows an unknown entity in the UI language', async () => {
    await i18n.changeLanguage('pt');
    mockPut.mockResolvedValue({
      data: null, error: "disabled_for: unknown domain 'd-sales'",
      errorCode: 'gate_exemption_not_found', errorParams: { kind: 'domain', id: 'd-sales' },
    });
    renderWithProviders(<CertifiedDeprecationGuardSettings />);

    fireEvent.click(await screen.findByRole('button', { name: 'Salvar' }));

    await waitFor(() => expect(mockToast).toHaveBeenCalledTimes(1));
    expect(mockToast.mock.calls[0][0]).toMatchObject({
      description: 'd-sales não existe mais. Remova-o e salve de novo.',
      variant: 'destructive',
    });
  });

  it('refuses to save an entity that no longer exists', async () => {
    mockGet.mockResolvedValue({ data: { ...SAVED, domains: ['d-gone'] } });
    renderWithProviders(<CertifiedDeprecationGuardSettings />);

    fireEvent.click(await screen.findByRole('button', { name: i18n.t('common:actions.save') }));

    await waitFor(() => expect(mockToast).toHaveBeenCalledTimes(1));
    expect(mockPut).not.toHaveBeenCalled();
    expect(mockToast.mock.calls[0][0].description).toBe(
      i18n.t('workflow-gates:certifiedGuard.missingOnSave', { count: 1 }),
    );
  });

  it('says when the switch cannot be loaded', async () => {
    mockGet.mockResolvedValue({ data: null, error: 'boom' });
    renderWithProviders(<CertifiedDeprecationGuardSettings />);

    await waitFor(() => expect(mockToast).toHaveBeenCalledWith({
      title: i18n.t('workflow-gates:certifiedGuard.loadFailed'), variant: 'destructive',
    }));
  });
});

/** Navigation presets card (#1325): preview, apply and undo with their refreshes and errors. */
import { screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import i18n from '@/i18n/config';
import { renderWithProviders } from '@/test/utils';
import { HomeSection } from '@/types/settings';
import type { NavigationPresetsResponse } from '@/types/navigation-presets';
import NavigationPresetsCard from './navigation-presets-card';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockToast = vi.fn();
const mockFetchNavigation = vi.fn();

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: mockToast }) }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: mockGet, post: mockPost }) }));
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({ fetchNavigation: mockFetchNavigation }),
}));

const URL = '/api/settings/navigation-presets';

const consumer = {
  role_name: 'Data Consumer', role_id: 'r1', found: true,
  shown: ['data-catalog', 'assets', 'semantic-models'],
  hidden: ['marketplace', 'data-products'],
  no_access: ['assets', 'semantic-models'],
  home_sections: [HomeSection.JOURNEY],
  current_hidden: [], current_home_sections: [HomeSection.DISCOVERY], changed: true,
};
const missing = {
  role_name: 'Data Governance Officer', role_id: null, found: false,
  shown: ['data-catalog'], hidden: [], no_access: [], home_sections: [HomeSection.JOURNEY],
  current_hidden: [], current_home_sections: [], changed: false,
};
const unchanged = {
  ...consumer, role_name: 'Data Steward', role_id: 'r2', no_access: [],
  shown: ['data-catalog'], home_sections: null, changed: false,
};

const PRESETS: NavigationPresetsResponse = {
  presets: [
    { id: 'essentials', roles: [consumer, unchanged, missing] },
    {
      id: 'data-consumer',
      roles: [{
        ...consumer, shown: ['marketplace', 'my-products'], no_access: [],
        home_sections: [HomeSection.MARKETPLACE],
      }],
    },
  ],
  last_applied: null,
};

const LAST_APPLIED = {
  preset_id: 'essentials', applied_at: '2026-11-24T10:30:00+00:00', applied_by: 'ana@x.io',
  roles: [{ role_id: 'r1', role_name: 'Data Consumer' }],
};

const setPresets = (overrides: Partial<NavigationPresetsResponse> = {}) =>
  mockGet.mockResolvedValue({ data: { ...PRESETS, ...overrides } });

const confirmDialog = async (button: string) => {
  const dialog = await screen.findByRole('alertdialog');
  fireEvent.click(within(dialog).getByRole('button', { name: button }));
};

describe('NavigationPresetsCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setPresets();
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('says it never changes access levels and previews each role of the first preset', async () => {
    renderWithProviders(<NavigationPresetsCard />);

    expect(await screen.findByTestId('preset-role-Data Consumer')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith(URL);
    expect(screen.getByTestId('navigation-presets-help')).toHaveTextContent(
      'never access levels',
    );
    expect(screen.getByTestId('navigation-presets-help')).toHaveTextContent('matched by name');

    const row = screen.getByTestId('preset-role-Data Consumer');
    // Only the entries the role can reach are in the menu; the others carry the hint.
    expect(within(row).getByText('Data Catalog')).toBeInTheDocument();
    expect(within(row).getByTestId('preset-no-access')).toHaveTextContent(
      'Not shown: the role has no access to Assets, Concepts.',
    );
    expect(within(row).getByText('Journey home')).toBeInTheDocument();
    expect(within(row).getByText('Changes')).toBeInTheDocument();
    expect(within(screen.getByTestId('preset-role-Data Steward')).getByText('Unchanged'))
      .toBeInTheDocument();
    expect(within(screen.getByTestId('preset-role-Data Steward')).getByText('No change'))
      .toBeInTheDocument();
    expect(within(screen.getByTestId('preset-role-Data Governance Officer'))
      .getByText('Role not found')).toBeInTheDocument();
  });

  it('switches the preview to the other preset', async () => {
    renderWithProviders(<NavigationPresetsCard />);
    await screen.findByTestId('preset-role-Data Consumer');

    fireEvent.click(screen.getByRole('radio', { name: /Data Consumer/ }));

    const row = await screen.findByTestId('preset-role-Data Consumer');
    expect(within(row).getByText('Marketplace, My Products')).toBeInTheDocument();
    expect(within(row).getByText('Marketplace home')).toBeInTheDocument();
    expect(screen.queryByTestId('preset-role-Data Steward')).not.toBeInTheDocument();
  });

  it('applies after a confirmation, then refreshes the preview, the roles and the menus', async () => {
    mockPost.mockResolvedValue({ data: {
      preset_id: 'essentials', changed_roles: [{ role_id: 'r1', role_name: 'Data Consumer' }],
      unchanged_roles: ['Data Steward'], missing_roles: ['Data Governance Officer'],
    } });
    const onChanged = vi.fn();
    renderWithProviders(<NavigationPresetsCard onChanged={onChanged} />);
    await screen.findByTestId('preset-role-Data Consumer');

    fireEvent.click(screen.getByRole('button', { name: 'Apply preset' }));
    // Nothing is sent before the confirmation.
    expect(mockPost).not.toHaveBeenCalled();
    expect(await screen.findByText('Apply the Essentials preset?')).toBeInTheDocument();
    await confirmDialog('Apply preset');

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(`${URL}/essentials/apply`, {}));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(mockGet).toHaveBeenCalledTimes(2);
    expect(mockFetchNavigation).toHaveBeenCalledTimes(1);
    expect(mockToast).toHaveBeenCalledWith({
      title: 'Essentials preset applied',
      description: 'Changed: 1, unchanged: 1, not found: 1.',
    });
  });

  it('cannot apply a preset that changes no role', async () => {
    setPresets({ presets: [{ id: 'essentials', roles: [unchanged, missing] }] });
    renderWithProviders(<NavigationPresetsCard />);
    await screen.findByTestId('preset-role-Data Steward');

    expect(screen.getByRole('button', { name: 'Apply preset' })).toBeDisabled();
  });

  it('offers undo with who and when, and restores after a confirmation', async () => {
    setPresets({ last_applied: LAST_APPLIED });
    mockPost.mockResolvedValue({ data: {
      preset_id: 'essentials', restored_roles: [{ role_id: 'r1', role_name: 'Data Consumer' }],
      missing_roles: [],
    } });
    const onChanged = vi.fn();
    renderWithProviders(<NavigationPresetsCard onChanged={onChanged} />);

    const last = await screen.findByTestId('preset-last-applied');
    expect(last).toHaveTextContent('Last applied: Essentials by ana@x.io,');
    expect(last).toHaveTextContent('2026');

    fireEvent.click(screen.getByRole('button', { name: 'Undo last preset' }));
    expect(mockPost).not.toHaveBeenCalled();
    await confirmDialog('Undo last preset');

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(`${URL}/undo`, {}));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(mockFetchNavigation).toHaveBeenCalledTimes(1);
    expect(mockToast).toHaveBeenCalledWith({
      title: 'Essentials preset undone', description: 'Restored: 1, not found: 0.',
    });
  });

  it('has no undo button until a preset was applied', async () => {
    renderWithProviders(<NavigationPresetsCard />);
    await screen.findByTestId('preset-role-Data Consumer');

    expect(screen.queryByRole('button', { name: 'Undo last preset' })).not.toBeInTheDocument();
  });

  it('shows a coded error in the UI language, not the API text', async () => {
    await i18n.changeLanguage('pt');
    setPresets({ last_applied: LAST_APPLIED });
    mockPost.mockResolvedValue({
      data: null, error: 'No navigation preset application to undo.',
      errorCode: 'navigation_preset_nothing_to_undo',
    });
    renderWithProviders(<NavigationPresetsCard />);
    expect(await screen.findByText('Predefinições de navegação')).toBeInTheDocument();

    fireEvent.click(await screen.findByRole('button', { name: 'Desfazer última predefinição' }));
    await confirmDialog('Desfazer última predefinição');

    await waitFor(() => expect(mockToast).toHaveBeenCalledTimes(1));
    expect(mockToast.mock.calls[0][0]).toMatchObject({
      title: 'Não foi possível desfazer a predefinição',
      description: 'Não há nenhuma aplicação de predefinição para desfazer.',
      variant: 'destructive',
    });
    // The preview is read again: the stored application may be gone.
    expect(mockGet).toHaveBeenCalledTimes(2);
    expect(mockFetchNavigation).not.toHaveBeenCalled();
  });

  it('shows an unknown preset in English too, and other errors by their API text', async () => {
    mockPost.mockResolvedValueOnce({
      data: null, error: 'Unknown navigation preset: essentials',
      errorCode: 'navigation_preset_unknown', errorParams: { preset_id: 'essentials' },
    });
    renderWithProviders(<NavigationPresetsCard />);
    await screen.findByTestId('preset-role-Data Consumer');

    fireEvent.click(screen.getByRole('button', { name: 'Apply preset' }));
    await confirmDialog('Apply preset');
    await waitFor(() => expect(mockToast).toHaveBeenCalledTimes(1));
    expect(mockToast.mock.calls[0][0]).toMatchObject({
      description: 'This preset does not exist.', variant: 'destructive',
    });

    mockPost.mockResolvedValueOnce({ data: null, error: 'Server said no' });
    fireEvent.click(screen.getByRole('button', { name: 'Apply preset' }));
    await confirmDialog('Apply preset');
    await waitFor(() => expect(mockToast).toHaveBeenCalledTimes(2));
    expect(mockToast.mock.calls[1][0]).toMatchObject({ description: 'Server said no' });
  });

  it('says so when the presets cannot be loaded', async () => {
    mockGet.mockResolvedValue({ data: {}, error: 'boom' });
    renderWithProviders(<NavigationPresetsCard />);

    expect(await screen.findByText('Could not load the navigation presets.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Apply preset' })).not.toBeInTheDocument();
  });
});

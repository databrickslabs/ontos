/** The navigation presets card sits above the roles table for role admins only (#1325). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const state = vi.hoisted(() => ({ admin: true }));
const getMock = vi.fn();
const fetchAvailableRoles = vi.fn();

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: getMock, delete: vi.fn() }) }));
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    hasPermission: (_id: string, level: string) => level !== 'Admin' || state.admin,
    fetchPermissions: vi.fn(),
    fetchAvailableRoles,
  }),
}));
vi.mock('@/stores/user-store', () => ({ useUserStore: () => ({ userInfo: null }) }));
vi.mock('./role-form-dialog', () => ({ default: () => null }));
vi.mock('./request-role-access-dialog', () => ({ default: () => null }));
vi.mock('./navigation-presets-card', () => ({
  default: ({ onChanged }: { onChanged: () => void }) => (
    <button data-testid="presets-card" onClick={() => onChanged()}>card</button>
  ),
}));
vi.mock('@/components/ui/data-table', () => ({
  DataTable: ({ data }: any) => (
    <div data-testid="roles-table">{data.map((r: any) => r.name).join(',')}</div>
  ),
}));

import RolesSettings from './roles-settings';

describe('RolesSettings navigation presets', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.admin = true;
    let rolesCalls = 0;
    getMock.mockImplementation(async (url: string) => {
      if (!url.endsWith('/roles')) return { data: {} };
      rolesCalls += 1;
      return { data: [{ id: 'r1', name: rolesCalls === 1 ? 'Before' : 'After' }] };
    });
  });

  it('shows the card to a role admin and reloads the table and role store', async () => {
    render(<RolesSettings />);
    fireEvent.click(await screen.findByTestId('presets-card'));

    await waitFor(() => expect(screen.getByTestId('roles-table')).toHaveTextContent('After'));
    expect(fetchAvailableRoles).toHaveBeenCalledTimes(1);
  });

  it('does not show the card without Admin on the roles settings', async () => {
    state.admin = false;
    render(<RolesSettings />);

    expect(await screen.findByTestId('roles-table')).toBeInTheDocument();
    expect(screen.queryByTestId('presets-card')).not.toBeInTheDocument();
  });
});

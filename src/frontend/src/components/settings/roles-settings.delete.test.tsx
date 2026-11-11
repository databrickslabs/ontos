import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const toast = vi.fn();
const getMock = vi.fn();
const deleteMock = vi.fn();

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast }) }));
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: getMock, delete: deleteMock }),
}));
vi.mock('@/stores/permissions-store', () => ({
  usePermissions: () => ({
    hasPermission: () => true,
    fetchPermissions: vi.fn(),
    fetchAvailableRoles: vi.fn(),
  }),
}));
vi.mock('@/stores/user-store', () => ({ useUserStore: () => ({ userInfo: null }) }));
vi.mock('./role-form-dialog', () => ({ default: () => null }));
vi.mock('./request-role-access-dialog', () => ({ default: () => null }));
vi.mock('@/components/ui/data-table', () => ({
  DataTable: ({ columns, data }: any) => (
    <div>
      {data.map((row: any) => (
        <div key={row.id}>
          {columns.find((c: any) => c.id === 'actions').cell({ row: { original: row } })}
        </div>
      ))}
    </div>
  ),
}));

import RolesSettings from './roles-settings';

describe('RolesSettings delete', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    getMock.mockImplementation(async (url: string) =>
      url.endsWith('/roles')
        ? { data: [{ id: 'r1', name: 'Custom', assigned_groups: [], feature_permissions: {} }] }
        : { data: {} },
    );
  });

  it('shows the error toast and does not refetch when DELETE fails', async () => {
    deleteMock.mockResolvedValue({ data: null, error: 'role in use' });
    render(<RolesSettings />);
    fireEvent.click(await screen.findByTitle('roles.actions.deleteRole'));
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({ variant: 'destructive', description: 'role in use' }),
      ),
    );
    expect(toast).not.toHaveBeenCalledWith(
      expect.objectContaining({ description: 'roles.messages.roleDeleted' }),
    );
    expect(getMock).toHaveBeenCalledTimes(2); // initial roles + features only
  });
});

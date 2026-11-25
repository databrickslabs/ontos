/**
 * #1580: the Assign Owner dialog shows the business role it assigns and preselects an owner
 * role. Before, it had no role field and saved the first active role by name (usually
 * "Business Sponsor"), so the new owner was left out of owner-routed approvals.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AssignOwnerDialog, defaultOwnerRole, isOwnerRole } from './assign-owner-dialog';
import type { BusinessRoleRead } from '@/types/business-role';

const get = vi.fn();
const post = vi.fn();

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get, post }),
}));

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock('@/components/common/principal-picker', () => ({
  PrincipalPicker: ({ onChange }: { onChange: (v: string | null) => void }) => (
    <input aria-label="owner user" onChange={(e) => onChange(e.target.value)} />
  ),
}));

function role(id: string, name: string, extra: Partial<BusinessRoleRead> = {}): BusinessRoleRead {
  return {
    id, name, is_system: true, is_approver: false, status: 'active',
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', ...extra,
  };
}

// As /api/business-roles returns them: sorted by name
const ROLES = [
  role('r-sponsor', 'Business Sponsor', { is_approver: true, description: 'Sponsors it.' }),
  role('r-custodian', 'Data Custodian', { status: 'deprecated' }),
  role('r-owner', 'Data Owner', { is_approver: true, description: 'Accountable for it.' }),
  role('r-steward', 'Data Steward', { is_approver: true }),
];

function renderDialog(objectType: 'data_product' | 'data_domain' = 'data_product') {
  const onSuccess = vi.fn();
  render(
    <AssignOwnerDialog
      open
      onOpenChange={vi.fn()}
      objectType={objectType}
      objectId="p-1"
      onSuccess={onSuccess}
    />,
  );
  return { onSuccess };
}

describe('AssignOwnerDialog role (#1580)', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    get.mockResolvedValue({ data: ROLES });
    post.mockResolvedValue({ data: { id: 'bo-1' } });
  });

  it('shows a role field preselected to Data Owner, not the first role', async () => {
    renderDialog();
    const select = await screen.findByRole('combobox', { name: 'Role' });
    expect(select).toHaveTextContent('Data Owner');
    expect(screen.getByText('Accountable for it.')).toBeInTheDocument();
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('submits the preselected owner role', async () => {
    const { onSuccess } = renderDialog();
    await screen.findByRole('combobox', { name: 'Role' });
    await userEvent.type(screen.getByLabelText('owner user'), 'ana@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Assign Owner' }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith('/api/business-owners', expect.objectContaining({
      object_type: 'data_product',
      object_id: 'p-1',
      user_email: 'ana@example.com',
      role_id: 'r-owner',
    }));
    expect(onSuccess).toHaveBeenCalled();
  });

  it('warns when the role is not an owner role', async () => {
    get.mockResolvedValue({ data: [ROLES[0]] });
    renderDialog();
    expect(await screen.findByRole('note')).toHaveTextContent(/don't receive owner approvals/);
  });

  it("doesn't warn on a domain: every domain owner gets the domain's approvals", async () => {
    get.mockResolvedValue({ data: [ROLES[0]] });
    renderDialog('data_domain');
    await screen.findByRole('combobox', { name: 'Role' });
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('explains when no business role exists', async () => {
    get.mockResolvedValue({ data: [] });
    renderDialog();
    expect(await screen.findByText(/No business roles are configured/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Assign Owner' })).toBeDisabled();
  });
});

describe('defaultOwnerRole', () => {
  it('prefers Data Owner, then Owner, then an approver role, then the first role', () => {
    const sponsor = role('s', 'Business Sponsor');
    const tech = role('t', 'Technical Owner', { is_approver: true });
    expect(defaultOwnerRole([sponsor, tech, role('o', 'Owner'), role('d', 'Data Owner')])?.id)
      .toBe('d');
    expect(defaultOwnerRole([sponsor, tech, role('o', 'owner')])?.id).toBe('o');
    expect(defaultOwnerRole([sponsor, tech])?.id).toBe('t');
    expect(defaultOwnerRole([sponsor])?.id).toBe('s');
    expect(defaultOwnerRole([])).toBeUndefined();
  });

  it('counts only Data Owner and Owner as owner roles', () => {
    expect(isOwnerRole({ name: ' Data Owner ' })).toBe(true);
    expect(isOwnerRole({ name: 'OWNER' })).toBe(true);
    expect(isOwnerRole({ name: 'Domain Owner' })).toBe(false);
  });
});

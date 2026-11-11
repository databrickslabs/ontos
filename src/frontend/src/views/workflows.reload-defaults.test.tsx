/**
 * "Reload All Defaults" asks first, keeps edited defaults unless the admin opts
 * in to resetting them, names the kept ones, and shows a failure as an error.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

const get = vi.fn();
const post = vi.fn();
const toast = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get, post, delete: vi.fn() }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast }) }));
vi.mock('@/stores/permissions-store', async (orig) => {
  const actual = await orig<Record<string, unknown>>();
  return { ...actual, usePermissions: () => ({ hasPermission: () => true }) };
});
// Inline stand-in for the Radix dropdown (see workflows.cancel-execution.test.tsx).
vi.mock('@/components/ui/dropdown-menu', () => {
  const Box = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    DropdownMenu: Box, DropdownMenuContent: Box, DropdownMenuLabel: Box,
    DropdownMenuGroup: Box, DropdownMenuPortal: Box, DropdownMenuSub: Box,
    DropdownMenuSubContent: Box, DropdownMenuSubTrigger: Box, DropdownMenuRadioGroup: Box,
    DropdownMenuShortcut: Box, DropdownMenuCheckboxItem: Box, DropdownMenuRadioItem: Box,
    DropdownMenuTrigger: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    DropdownMenuItem: (
      { children, onClick }: { children?: React.ReactNode; onClick?: () => void },
    ) => <button type="button" role="menuitem" onClick={onClick}>{children}</button>,
    DropdownMenuSeparator: () => <hr />,
  };
});
vi.mock('@/components/settings/settings-page-wrapper', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import Workflows from './workflows';

function mockLists() {
  get.mockImplementation(async (url: string) => {
    if (url.startsWith('/api/workflows/executions')) return { data: { executions: [], total: 0 } };
    if (url.startsWith('/api/workflows')) return { data: { workflows: [], total: 0 } };
    return { data: { sessions: [], total: 0 } };
  });
}

async function openReloadAll() {
  const user = userEvent.setup();
  render(<MemoryRouter><Workflows /></MemoryRouter>);
  await user.click(await screen.findByRole('menuitem', { name: /reload all defaults/i }));
  return user;
}

const reloadCalls = () => post.mock.calls.filter(([url]) => String(url).startsWith('/api/workflows/load-defaults'));
const lastToast = () => toast.mock.calls[toast.mock.calls.length - 1][0];

describe('Workflows view: Reload All Defaults', () => {
  afterEach(() => {
    get.mockReset();
    post.mockReset();
    toast.mockReset();
  });

  it('asks before reloading and Cancel sends nothing', async () => {
    mockLists();
    const user = await openReloadAll();

    expect(await screen.findByText('Reload all default workflows?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^cancel$/i }));

    expect(reloadCalls()).toHaveLength(0);
  });

  it('keeps edited defaults by default and names them', async () => {
    mockLists();
    post.mockResolvedValue({
      data: { message: 'Workflows: updated 3, kept 1 edited', created: 0, updated: 3, skipped: 0,
        kept_edited: 1, kept_edited_names: ['Contract Purpose Gate'] },
    });
    const user = await openReloadAll();

    await user.click(await screen.findByRole('button', { name: /^reload$/i }));

    await waitFor(() => expect(reloadCalls()).toHaveLength(1));
    expect(reloadCalls()[0][0]).toBe('/api/workflows/load-defaults?update_existing=true&include_edited=false');
    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(lastToast().description).toBe(
      'Workflows: updated 3, kept 1 edited. Kept edited: Contract Purpose Gate',
    );
  });

  it('resets edited defaults only when the admin opts in', async () => {
    mockLists();
    post.mockResolvedValue({ data: { message: 'Workflows: updated 4', created: 0, updated: 4, skipped: 0 } });
    const user = await openReloadAll();

    await user.click(await screen.findByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: /^reload$/i }));

    await waitFor(() => expect(reloadCalls()).toHaveLength(1));
    expect(reloadCalls()[0][0]).toBe('/api/workflows/load-defaults?update_existing=true&include_edited=true');
  });

  it('shows a failed reload as an error', async () => {
    mockLists();
    post.mockResolvedValue({ error: 'Insufficient permissions' });
    const user = await openReloadAll();

    await user.click(await screen.findByRole('button', { name: /^reload$/i }));

    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(lastToast().variant).toBe('destructive');
    expect(lastToast().description).toBe('Failed to load default workflows');
  });
});

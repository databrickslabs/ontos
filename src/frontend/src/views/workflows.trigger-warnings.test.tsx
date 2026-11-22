/** The workflows list flags a workflow whose stored trigger has warnings (#1438). */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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

import i18n from '@/i18n/config';
import Workflows from './workflows';

function workflow(id: string, name: string, triggerWarnings: unknown[]) {
  return {
    id, name, description: '', workflow_type: 'process', is_active: true, is_default: false,
    version: 1, scope: { type: 'all', ids: [] },
    trigger: { type: 'before_update', entity_types: ['dataset'] },
    steps: [], trigger_warnings: triggerWarnings,
  };
}

describe('Workflows view: trigger warnings', () => {
  afterEach(() => {
    get.mockReset();
    post.mockReset();
    toast.mockReset();
  });

  it('flags only the workflows whose stored trigger has warnings', async () => {
    get.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/workflows/executions')) return { data: { executions: [], total: 0 } };
      if (url.startsWith('/api/workflows')) {
        return {
          data: {
            workflows: [
              workflow('wf-1', 'Stale gate', [
                { code: 'stored_entity_type_unknown', message: 'x', params: { triggerType: 'before_update', entityType: 'dataset' } },
              ]),
              workflow('wf-2', 'Clean gate', []),
            ],
            total: 2,
          },
        };
      }
      return { data: { sessions: [], total: 0 } };
    });

    render(<MemoryRouter><Workflows /></MemoryRouter>);

    const label = i18n.getFixedT('en')('workflows:view.badges.triggerWarnings');
    expect(await screen.findByText('Stale gate')).toBeInTheDocument();
    expect(screen.getAllByText(label)).toHaveLength(1);
    expect(screen.getByText(label).closest('tr')?.textContent).toContain('Stale gate');
  });
});

/**
 * A requested deprecation shows its replacement by name in the approval
 * dialog (part of #1042); the id stays in the request.
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import WorkflowApprovalResponseDialog, { withReplacementName } from './workflow-approval-response-dialog';

const api = vi.hoisted(() => ({
  get: async () => ({ data: null }),
  post: async () => ({ data: {} }),
  toast: () => {},
}));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: api.post }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));

describe('withReplacementName', () => {
  it('shows the name, without the id, when the request has one', () => {
    expect(withReplacementName({ replacement_id: 'p-2', replacement_name: 'Orders v2', sunset_date: '2027-01-01' }))
      .toEqual({ sunset_date: '2027-01-01', replacement_name: 'Orders v2' });
  });

  it('keeps the id when there is no name', () => {
    expect(withReplacementName({ replacement_id: 'p-2', replacement_name: null })).toEqual({ replacement_id: 'p-2' });
    expect(withReplacementName({ target_status: 'deprecated' })).toEqual({ target_status: 'deprecated' });
  });
});

describe('WorkflowApprovalResponseDialog replacement', () => {
  it('shows the replacement product by name', async () => {
    render(
      <WorkflowApprovalResponseDialog
        isOpen
        onOpenChange={() => {}}
        payload={{
          execution_id: 'e-1',
          entity_name: 'Orders',
          full_payload: { target_status: 'deprecated', replacement_id: 'p-2', replacement_name: 'Orders v2' },
        } as never}
      />,
    );

    expect(await screen.findByText('Orders v2')).toBeInTheDocument();
    expect(screen.queryByText('p-2')).toBeNull();
  });
});

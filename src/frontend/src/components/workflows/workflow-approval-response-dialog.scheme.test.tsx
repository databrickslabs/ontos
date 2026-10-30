/**
 * Concept approvals show the scheme's label captured at submit time in the
 * Scheme row, not the raw scheme key, and do not repeat the label as a
 * second raw row.
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import WorkflowApprovalResponseDialog from './workflow-approval-response-dialog';

// Stable functions: the dialog loads its config in an effect that depends on `get`
const api = vi.hoisted(() => ({
  get: async () => ({ data: { id: 'wf', name: 'Approval response', steps: [] } }),
  post: async () => ({ data: {} }),
  toast: () => {},
}));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: api.post }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));

function renderDialog(fullPayload: Record<string, unknown>) {
  return render(
    <WorkflowApprovalResponseDialog
      isOpen
      onOpenChange={() => {}}
      payload={{ execution_id: 'e-1', entity_name: 'Customer', full_payload: fullPayload } as never}
    />,
  );
}

function schemeValue() {
  const dt = screen.getByText('Scheme', { selector: 'dt' });
  return dt.nextElementSibling?.textContent;
}

describe('WorkflowApprovalResponseDialog scheme row', () => {
  it('shows source_label in the Scheme row and no raw source_label row', async () => {
    renderDialog({ source_context: 'supply-chain', source_label: 'Supply Chain Ontology TEST' });
    await screen.findByText('Scheme', { selector: 'dt' });
    expect(schemeValue()).toBe('Supply Chain Ontology TEST');
    expect(screen.getAllByText('Supply Chain Ontology TEST')).toHaveLength(1);
    expect(screen.queryByText(/source[ _]label/i)).toBeNull();
    expect(screen.queryByText('supply-chain')).toBeNull();
  });

  it('falls back to source_context when no source_label is sent', async () => {
    renderDialog({ source_context: 'supply-chain' });
    await screen.findByText('Scheme', { selector: 'dt' });
    expect(schemeValue()).toBe('supply-chain');
  });
});

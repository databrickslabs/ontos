/**
 * The approval response dialog shows the shipped default texts in the user's
 * language, and a text an admin changed as written.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import i18n from '@/i18n/config';
import WorkflowApprovalResponseDialog from './workflow-approval-response-dialog';

const step = vi.hoisted(() => ({
  config: {
    title: 'Enter a reason',
    description: 'Provide a reason for your approval or rejection decision.',
    required_fields: [{ id: 'reason', label: 'Reason for approval or rejection', type: 'text' }],
  } as Record<string, unknown>,
}));

// Stable functions: the dialog loads its config in an effect that depends on `get`
const api = vi.hoisted(() => ({
  get: async () => ({
    data: {
      id: 'wf',
      name: 'Approval response',
      steps: [{ step_id: 'enter-reason', name: 'Enter a reason', step_type: 'user_action', config: step.config }],
    },
  }),
  post: async () => ({ data: {} }),
  toast: () => {},
}));

vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: api.get, post: api.post }) }));

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));

function renderDialog() {
  return render(
    <WorkflowApprovalResponseDialog
      isOpen
      onOpenChange={() => {}}
      payload={{ execution_id: 'e-1', entity_name: 'Product' } as never}
    />,
  );
}

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('WorkflowApprovalResponseDialog default texts', () => {
  it('shows the shipped texts in Portuguese', async () => {
    await i18n.changeLanguage('pt');
    renderDialog();

    expect(await screen.findByText('Informe um motivo')).toBeInTheDocument();
    expect(screen.getByText('Informe o motivo da sua decisão de aprovar ou rejeitar.')).toBeInTheDocument();
    expect(screen.getByText(/Motivo da aprovação ou rejeição/)).toBeInTheDocument();
  });

  it('shows a title an admin changed as written', async () => {
    await i18n.changeLanguage('pt');
    step.config.title = 'Why do you decide so?';
    try {
      renderDialog();
      expect(await screen.findByText('Why do you decide so?')).toBeInTheDocument();
      // The untouched description is still translated
      expect(screen.getByText('Informe o motivo da sua decisão de aprovar ou rejeitar.')).toBeInTheDocument();
    } finally {
      step.config.title = 'Enter a reason';
    }
  });
});

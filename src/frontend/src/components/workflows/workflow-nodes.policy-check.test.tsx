/** The Policy Check node marks a step whose policy is not selected. */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ReactFlowProvider } from 'reactflow';
import '@/i18n/config';
import { PolicyCheckNode } from './workflow-nodes';

function renderNode(config: Record<string, unknown>) {
  const props = {
    id: 'n1',
    selected: false,
    data: { step: { step_id: 's1', name: 'Check naming', step_type: 'policy_check', config } },
  } as unknown as React.ComponentProps<typeof PolicyCheckNode>;
  return render(
    <ReactFlowProvider>
      <PolicyCheckNode {...props} />
    </ReactFlowProvider>,
  );
}

describe('PolicyCheckNode', () => {
  it('shows the policy name when a policy is selected', () => {
    renderNode({ policy_id: 'pol-1', policy_name: 'Naming Conventions' });

    expect(screen.getByText('Policy: Naming Conventions')).toBeInTheDocument();
    expect(screen.queryByText('No policy selected')).not.toBeInTheDocument();
  });

  it('marks an empty policy id as not selected and keeps the name as a hint', () => {
    renderNode({ policy_id: '', policy_name: 'Naming Conventions' });

    expect(screen.getByText('No policy selected')).toBeInTheDocument();
    expect(screen.getByText('Suggested: Naming Conventions')).toBeInTheDocument();
    expect(screen.queryByText('Policy: Naming Conventions')).not.toBeInTheDocument();
  });
});

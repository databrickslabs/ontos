/** The Policy Check node marks a step whose policy is not selected or not known. */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ReactFlowProvider } from 'reactflow';
import '@/i18n/config';
import { CompliancePolicyIdsContext, PolicyCheckNode } from './workflow-nodes';

function renderNode(config: Record<string, unknown>, policyIds?: string[]) {
  const props = {
    id: 'n1',
    selected: false,
    data: { step: { step_id: 's1', name: 'Check naming', step_type: 'policy_check', config } },
  } as unknown as React.ComponentProps<typeof PolicyCheckNode>;
  return render(
    <ReactFlowProvider>
      <CompliancePolicyIdsContext.Provider value={policyIds}>
        <PolicyCheckNode {...props} />
      </CompliancePolicyIdsContext.Provider>
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

  it('marks an id no loaded policy has, such as an old placeholder slug', () => {
    renderNode({ policy_id: 'naming-conventions', policy_name: 'Naming Conventions' }, ['pol-1']);

    expect(screen.getByText('Unknown or inactive policy: naming-conventions')).toBeInTheDocument();
    expect(screen.getByText('Suggested: Naming Conventions')).toBeInTheDocument();
    expect(screen.queryByText('Policy: Naming Conventions')).not.toBeInTheDocument();
  });

  it('shows a known policy as selected, with surrounding spaces ignored', () => {
    renderNode({ policy_id: ' pol-1 ', policy_name: 'Naming Conventions' }, ['pol-1']);

    expect(screen.getByText('Policy: Naming Conventions')).toBeInTheDocument();
    expect(screen.queryByText(/Unknown or inactive policy/)).not.toBeInTheDocument();
  });

  it('flags nothing while the policy list is not loaded', () => {
    renderNode({ policy_id: 'naming-conventions', policy_name: 'Naming Conventions' });

    expect(screen.getByText('Policy: Naming Conventions')).toBeInTheDocument();
    expect(screen.queryByText(/Unknown or inactive policy/)).not.toBeInTheDocument();
  });
});

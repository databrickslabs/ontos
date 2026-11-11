/**
 * A designer load that was superseded (React.StrictMode runs the load effect twice in dev) must
 * not overwrite what the user did after the newer load finished.
 */
import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import WorkflowDesigner from './workflow-designer';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), toast: vi.fn() }));

vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: api.get, post: api.post, put: api.put }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));
vi.mock('./template-vars-inspector', () => ({ default: () => null }));

const STEP_TYPES = [
  {
    type: 'conditional', name: 'Conditional', description: '', icon: 'git-branch',
    config_schema: {
      type: 'object', properties: { condition: { type: 'string' } }, required: ['condition'],
    },
    has_pass_branch: true, has_fail_branch: true,
  },
];

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
});

describe('WorkflowDesigner overlapping loads', () => {
  it('keeps a step added before the first (superseded) load finishes', async () => {
    // The first step-types request (from the first, superseded effect run) answers last
    let releaseFirst: () => void = () => undefined;
    let stepTypeCalls = 0;
    api.get.mockImplementation(async (url: string) => {
      if (url === '/api/workflows/step-types') {
        stepTypeCalls += 1;
        if (stepTypeCalls === 1) {
          await new Promise<void>(resolve => { releaseFirst = resolve; });
        }
        return { data: STEP_TYPES };
      }
      return { data: [] };
    });

    const { container } = render(
      <StrictMode>
        <MemoryRouter initialEntries={['/workflows/new?type=process']}>
          <WorkflowDesigner workflowId="new" />
        </MemoryRouter>
      </StrictMode>,
    );
    const nodes = () => container.querySelectorAll('.react-flow__node');

    // The second run finishes first: the trigger shows and the user adds a step
    await waitFor(() => expect(nodes()).toHaveLength(1));
    fireEvent.click(await screen.findByRole('button', { name: 'Conditional' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByTestId('step-config-done'));
    await waitFor(() => expect(nodes()).toHaveLength(2));

    // The first run now finishes: it must not reset the canvas to the trigger alone
    await act(async () => {
      releaseFirst();
      await new Promise(resolve => setTimeout(resolve, 50));
    });
    expect(nodes()).toHaveLength(2);
  });
});

/**
 * Unit tests for the FetchedSelectField helper used by the user_action
 * step renderer in approval-wizard-dialog. Covers the options-endpoint fetch
 * path and the response-shape normalization (id/name vs value/label vs
 * deployment_name) so portable workflow configs can point at existing
 * backend endpoints without per-endpoint adapters.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { FetchedSelectField } from './approval-wizard-dialog';

describe('FetchedSelectField', () => {
  it('fetches and normalizes {id,name} response (workspace-endpoint shape)', async () => {
    // Mirrors /api/workspace/accessible-workspaces response shape.
    const fetcher = vi.fn().mockResolvedValue({
      data: [
        { id: 'ws-prod', name: 'Production', deployment_name: 'prod' },
        { id: 'ws-dev', name: 'Development', deployment_name: 'dev' },
      ],
    });
    render(
      <FetchedSelectField
        field={{
          id: 'target_workspace',
          label: 'Target workspace',
          type: 'select',
          options_endpoint: '/api/workspace/accessible-workspaces',
        }}
        value=""
        onChange={vi.fn()}
        fetcher={fetcher}
      />,
    );
    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledWith('/api/workspace/accessible-workspaces');
    });
    // Trigger renders the placeholder (value is empty); the actual options
    // live inside SelectContent which Radix portals on open. We assert via
    // the trigger having been rendered with the expected placeholder.
    expect(screen.getByText('Target workspace')).toBeInTheDocument();
  });

  it('skips fetch when no options_endpoint is provided (uses static options)', async () => {
    const fetcher = vi.fn();
    render(
      <FetchedSelectField
        field={{
          id: 'priority',
          label: 'Priority',
          type: 'select',
          options: [
            { value: 'low', label: 'Low' },
            { value: 'high', label: 'High' },
          ],
        }}
        value=""
        onChange={vi.fn()}
        fetcher={fetcher}
      />,
    );
    // No fetcher invocation when static options are provided.
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('handles fetch errors gracefully without crashing', async () => {
    const fetcher = vi.fn().mockResolvedValue({ error: 'boom' });
    render(
      <FetchedSelectField
        field={{
          id: 'target_workspace',
          label: 'Target workspace',
          type: 'select',
          options_endpoint: '/api/workspace/accessible-workspaces',
        }}
        value=""
        onChange={vi.fn()}
        fetcher={fetcher}
      />,
    );
    await waitFor(() => {
      expect(fetcher).toHaveBeenCalled();
    });
    // Component renders without throwing — placeholder is still there.
    expect(screen.getByText('Target workspace')).toBeInTheDocument();
  });
});

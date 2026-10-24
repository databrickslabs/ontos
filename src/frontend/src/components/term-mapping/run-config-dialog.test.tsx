import type React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import RunConfigDialog from './run-config-dialog';

const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: mockGet, post: mockPost }),
}));

// Render Radix Popover content inline: opening it through jsdom pointer events
// is environment-dependent (it never opened on the CI runner). What this file
// tests is the options list and the payload, not the popover mechanics.
vi.mock('@/components/ui/popover', () => ({
  Popover: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  PopoverTrigger: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  PopoverContent: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));

const ASSET_TYPES = [
  { id: '1', name: 'Table', status: 'active', is_system: true, asset_count: 3 },
  { id: '2', name: 'Column', status: 'active', is_system: true, asset_count: 9 },
  { id: '3', name: 'View', status: 'active', is_system: true, asset_count: 1 },
  { id: '4', name: 'LegacyThing', status: 'deprecated', is_system: false, asset_count: 0 },
];

describe('RunConfigDialog asset-type multi-select', () => {
  beforeEach(() => {
    mockGet.mockImplementation((url: string) => {
      if (url.startsWith('/api/asset-types')) return Promise.resolve({ data: ASSET_TYPES });
      if (url.startsWith('/api/term-mappings/contexts')) {
        return Promise.resolve({ data: [{ context: 'urn:glossary:x', label: 'X', concept_count: 2 }] });
      }
      return Promise.resolve({ data: [] });
    });
    mockPost.mockResolvedValue({ data: { id: 'run-1', stats: {} } });
  });

  it('lists asset types from the API and sends selected names in the run payload', async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    renderWithProviders(<RunConfigDialog isOpen onOpenChange={vi.fn()} onCreated={onCreated} />);

    await waitFor(() =>
      expect(mockGet).toHaveBeenCalledWith(expect.stringMatching(/^\/api\/asset-types/)),
    );
    // Default selection is preserved.
    expect(within(screen.getByTestId('tm-asset-types-selected')).getByText('Column')).toBeInTheDocument();

    const listbox = await screen.findByRole('listbox');
    expect(within(listbox).getByRole('option', { name: 'Table' })).toBeInTheDocument();
    expect(within(listbox).getByRole('option', { name: 'View' })).toBeInTheDocument();
    expect(within(listbox).queryByRole('option', { name: 'LegacyThing' })).not.toBeInTheDocument();

    await user.click(within(listbox).getByRole('option', { name: 'Table' }));

    await user.click(screen.getByRole('button', { name: 'Create run' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const [url, payload] = mockPost.mock.calls[0];
    expect(url).toBe('/api/term-mappings/runs');
    expect(payload.target_filter.asset_type_names).toEqual(['Column', 'Table']);
  });

  it('removing a chip drops the name from the payload', async () => {
    const user = userEvent.setup();
    renderWithProviders(<RunConfigDialog isOpen onOpenChange={vi.fn()} onCreated={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('X')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Remove Column' }));
    expect(screen.queryByTestId('tm-asset-types-selected')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Create run' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost.mock.calls[0][1].target_filter.asset_type_names).toEqual([]);
  });
});

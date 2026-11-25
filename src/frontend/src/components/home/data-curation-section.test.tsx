/**
 * The Self-Service buttons wait for the user's teams, so a click can't skip
 * the team membership check while /api/user/teams is still loading.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import DataCurationSection from './data-curation-section';

const mockGet = vi.fn();
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: mockGet }) }));
vi.mock('@/components/data-contracts/self-service-dialog', () => ({
  default: ({ isOpen }: { isOpen: boolean }) => (isOpen ? <div>self-service-dialog</div> : null),
}));

const selfServiceButtons = () => screen.getAllByRole('button', { name: /self-service/i });

describe('DataCurationSection', () => {
  beforeEach(() => vi.clearAllMocks());

  it('keeps the buttons disabled until the teams have loaded', async () => {
    let resolve!: (v: unknown) => void;
    mockGet.mockReturnValue(new Promise((r) => { resolve = r; }));
    renderWithProviders(<DataCurationSection />);

    expect(selfServiceButtons()).toHaveLength(3);
    for (const b of selfServiceButtons()) expect(b).toBeDisabled();

    resolve({ data: [] });
    await waitFor(() => {
      for (const b of selfServiceButtons()) expect(b).toBeEnabled();
    });
  });

  it('shows the membership alert, not the dialog, for a user without teams', async () => {
    mockGet.mockResolvedValue({ data: [] });
    renderWithProviders(<DataCurationSection />);
    await waitFor(() => expect(selfServiceButtons()[0]).toBeEnabled());

    fireEvent.click(selfServiceButtons()[0]);
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument();
    expect(screen.queryByText('self-service-dialog')).not.toBeInTheDocument();
  });

  it('opens the dialog for a team member', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 't1' }] });
    renderWithProviders(<DataCurationSection />);
    await waitFor(() => expect(selfServiceButtons()[0]).toBeEnabled());

    fireEvent.click(selfServiceButtons()[0]);
    expect(await screen.findByText('self-service-dialog')).toBeInTheDocument();
  });
});

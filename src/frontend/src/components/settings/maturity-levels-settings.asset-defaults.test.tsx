import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const toast = vi.fn();
const getMock = vi.fn();
const postMock = vi.fn();

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'count' in opts ? `${key}:${opts.count}` : key,
    i18n: { language: 'en' },
  }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast }) }));
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({ get: getMock, post: postMock, put: vi.fn(), delete: vi.fn() }),
}));

import MaturityLevelsSettings from './maturity-levels-settings';

const productLevel = {
  id: 'l1', level_order: 1, name: 'Accessible', description: null, icon: null, color: null,
  entity_type: 'all', gates: [],
};
const assetLevel = { ...productLevel, id: 'l2', name: 'Prerequisite', entity_type: 'Asset' };

function levelsAre(levels: unknown[]) {
  getMock.mockImplementation(async (url: string) =>
    url === '/api/maturity-levels' ? { data: levels } : { data: [] },
  );
}

describe('MaturityLevelsSettings default asset levels', () => {
  beforeEach(() => vi.clearAllMocks());

  it('loads the default asset levels and refreshes the list', async () => {
    levelsAre([productLevel]);
    postMock.mockResolvedValue({ data: { created: 4, levels: [] } });
    render(<MaturityLevelsSettings />);

    fireEvent.click(await screen.findByText('maturityLevels.assetDefaults.load'));

    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/api/maturity-levels/asset-defaults', {},
    ));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
      description: 'maturityLevels.assetDefaults.loaded:4',
    })));
    expect(getMock.mock.calls.filter(([url]) => url === '/api/maturity-levels').length)
      .toBe(2);
  });

  it('says nothing changed when the levels exist already', async () => {
    levelsAre([productLevel]);
    postMock.mockResolvedValue({ data: { created: 0, levels: [] } });
    render(<MaturityLevelsSettings />);

    fireEvent.click(await screen.findByText('maturityLevels.assetDefaults.load'));

    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
      description: 'maturityLevels.assetDefaults.alreadyLoaded',
    })));
  });

  it('shows a translated error when loading fails', async () => {
    levelsAre([productLevel]);
    postMock.mockResolvedValue({ data: null, error: 'Internal Server Error' });
    render(<MaturityLevelsSettings />);

    fireEvent.click(await screen.findByText('maturityLevels.assetDefaults.load'));

    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({
      variant: 'destructive', description: 'maturityLevels.assetDefaults.loadFailed',
    })));
  });

  it('hides the action once an asset level exists', async () => {
    levelsAre([productLevel, assetLevel]);
    render(<MaturityLevelsSettings />);

    expect(await screen.findByText('Prerequisite')).toBeInTheDocument();
    expect(screen.queryByText('maturityLevels.assetDefaults.load')).not.toBeInTheDocument();
  });
});

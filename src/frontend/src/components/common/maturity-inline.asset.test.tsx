import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));

import { MaturityInline } from './maturity-inline';

describe('MaturityInline for assets', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('reads the asset maturity and shows its level', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        entity_type: 'Asset', entity_id: 'a-1', achieved_level_order: 2,
        achieved_level_name: '1 star', total_levels: 4, gates_passed: 4, gates_total: 9,
        levels: [], evaluated_at: '2026-11-10T00:00:00Z', evaluated_by: null,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<MaturityInline entityType="Asset" entityId="a-1" />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/assets/a-1/maturity'));
    expect(await screen.findByText(/1 star/)).toBeInTheDocument();
    expect(screen.getByText('4/9')).toBeInTheDocument();
  });
});

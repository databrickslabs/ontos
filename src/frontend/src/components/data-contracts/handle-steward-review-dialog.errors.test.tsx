/**
 * A steward's review decision that a workflow gate blocks is explained in the
 * user's language (it showed the API's English message).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import i18n from '@/i18n/config';
import HandleStewardReviewDialog from './handle-steward-review-dialog';

const api = vi.hoisted(() => ({ post: vi.fn(), toast: vi.fn() }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ post: api.post }) }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: api.toast }) }));

const BLOCKED = {
  data: null,
  error: "Status transition from 'proposed' to 'approved' blocked by workflow: Contract Gate: Add a quality section first",
  errorCode: 'status_change_blocked',
  errorParams: {
    fromStatus: 'proposed',
    toStatus: 'approved',
    reasons: [{ workflow: 'Contract Gate', text: 'Add a quality section first' }],
  },
};

beforeEach(() => {
  api.post.mockReset();
  api.toast.mockReset();
});

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('HandleStewardReviewDialog', () => {
  it('translates a decision a workflow gate blocks', async () => {
    await i18n.changeLanguage('pt');
    api.post.mockResolvedValue(BLOCKED);
    render(
      <HandleStewardReviewDialog
        isOpen onOpenChange={() => {}} contractId="c1" requesterEmail="p@example.com" onDecisionMade={() => {}}
      />,
    );

    fireEvent.click(screen.getAllByRole('button').find(b => /aprovar/i.test(b.textContent || ''))!);

    await waitFor(() => expect(api.toast).toHaveBeenCalled());
    const description = api.toast.mock.calls[0][0].description as string;
    expect(description).not.toBe(BLOCKED.error);
    expect(description).toContain('Proposto');
    expect(description).toContain('Aprovado');
    expect(description).toContain('Contract Gate: Add a quality section first');
  });
});

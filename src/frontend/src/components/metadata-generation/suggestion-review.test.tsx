/**
 * Asset Review editor for a Description Suggestion: loads the suggestion by
 * its metagen:// FQN, shows current vs proposed text, and posts the reviewer's
 * decision (with an edited text and comment) to the decisions endpoint.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MetadataSuggestionReview from './suggestion-review';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
const toast = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-api', () => ({ useApi: () => api }));
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast }) }));

const FQN = 'metagen://run-1/s-1';
const suggestion = (overrides = {}) => ({
  id: 's-1', run_id: 'run-1', kind: 'description', object_type: 'column', table_fqn: 'main.sales.orders',
  column_name: 'amount', base_text: 'amt', proposed_text: 'Order amount in EUR.', status: 'pending',
  review_request_id: 'rev-1', ...overrides,
});
const OK = { data: { accepted: 1, rejected: 0, clarify: 0, skipped: 0, errors: [] } };

describe('MetadataSuggestionReview', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    toast.mockReset();
  });

  it('loads the suggestion and shows current and proposed text', async () => {
    api.get.mockResolvedValue({ data: suggestion() });
    render(<MetadataSuggestionReview assetFqn={FQN} />);

    expect(await screen.findByText('main.sales.orders.amount')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/metadata-generation/runs/run-1/suggestions/s-1');
    expect(screen.getByText('amt')).toBeInTheDocument();
    expect(screen.getByLabelText(/Proposed/)).toHaveValue('Order amount in EUR.');
  });

  it('approves with the edited text and comment', async () => {
    api.get.mockResolvedValue({ data: suggestion() });
    api.post.mockResolvedValue(OK);
    const onReviewComplete = vi.fn();
    render(<MetadataSuggestionReview assetFqn={FQN} onReviewComplete={onReviewComplete} />);

    const text = await screen.findByLabelText(/Proposed/);
    await userEvent.clear(text);
    await userEvent.type(text, 'Gross order amount in EUR.');
    expect(screen.getByText('Edited')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Comment'), 'gross, not net');
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));

    await waitFor(() => expect(onReviewComplete).toHaveBeenCalledWith('approved'));
    expect(api.post).toHaveBeenCalledWith('/api/metadata-generation/runs/run-1/decisions', {
      decisions: [{ id: 's-1', decision: 'accept', edited_text: 'Gross order amount in EUR.', comment: 'gross, not net' }],
    });
  });

  it('reports a clarification request as needs_clarification, not as rejected', async () => {
    api.get.mockResolvedValue({ data: suggestion() });
    api.post.mockResolvedValue({ data: { ...OK.data, accepted: 0, clarify: 1 } });
    const onReviewComplete = vi.fn();
    render(<MetadataSuggestionReview assetFqn={FQN} onReviewComplete={onReviewComplete} />);

    await userEvent.click(await screen.findByRole('button', { name: /Needs clarification/ }));
    await waitFor(() => expect(onReviewComplete).toHaveBeenCalledWith('needs_clarification'));
    expect(api.post.mock.calls[0][1].decisions[0]).toEqual({ id: 's-1', decision: 'clarify', edited_text: undefined, comment: undefined });
    // It left the review: no more decisions here
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
  });

  it('does not approve an empty description', async () => {
    api.get.mockResolvedValue({ data: suggestion() });
    render(<MetadataSuggestionReview assetFqn={FQN} />);

    await userEvent.clear(await screen.findByLabelText(/Proposed/));
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(api.post).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ variant: 'destructive' }));
  });

  it('surfaces a decision the backend skipped', async () => {
    api.get.mockResolvedValue({ data: suggestion() });
    api.post.mockResolvedValue({ data: { ...OK.data, accepted: 0, skipped: 1, errors: ['Suggestion s-1 is assigned to another reviewer'] } });
    const onReviewComplete = vi.fn();
    render(<MetadataSuggestionReview assetFqn={FQN} onReviewComplete={onReviewComplete} />);

    await userEvent.click(await screen.findByRole('button', { name: 'Reject' }));
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(expect.objectContaining({ description: 'Suggestion s-1 is assigned to another reviewer' })),
    );
    expect(onReviewComplete).not.toHaveBeenCalled();
  });

  it('is read-only once applied', async () => {
    api.get.mockResolvedValue({ data: suggestion({ status: 'applied' }) });
    render(<MetadataSuggestionReview assetFqn={FQN} />);

    expect(await screen.findByText('This suggestion can no longer be changed.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled();
  });

  it('rejects an FQN that is not a metagen one', () => {
    render(<MetadataSuggestionReview assetFqn="main.sales.orders" />);
    expect(screen.getByText(/Not a Metadata Generation suggestion/)).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });
});

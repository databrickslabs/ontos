/**
 * The contract request dialog follows the contract's Lifecycle Stage Group
 * (#1215): review is offered from a draft-category stage, publish from an
 * active-category one, whatever their keys, and the status change offers the
 * moves the API allows.
 *
 * The Radix Select hangs in jsdom, so it is replaced by a native select.
 */
import { screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import RequestContractActionDialog from './request-contract-action-dialog';

const mockGet = vi.fn();

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: mockGet, post: vi.fn() }) }));
vi.mock('@/stores/notifications-store', () => ({
  useNotificationsStore: (selector: any) => selector({ refreshNotifications: vi.fn() }),
}));
vi.mock('@/components/ui/select', () => ({
  Select: ({ value, onValueChange, children }: any) => (
    <select value={value} onChange={(e) => onValueChange(e.target.value)}>
      <option value="" />
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: any) => <>{children}</>,
  SelectItem: ({ value, disabled }: any) => (
    <option value={value} disabled={disabled}>{value}</option>
  ),
}));

const st = (key: string, category: string, order: number) => ({
  key, label: key, category, color: null, order, is_initial: order === 0,
});

function lifecycle(stage: ReturnType<typeof st>, next: ReturnType<typeof st>[]) {
  return {
    entity_type: 'data_contract', entity_id: 'c-1', status: stage.key,
    group: { id: 'g', name: 'Custom', entity_type: 'data_contract', is_default_for_type: false },
    stage, allowed_transitions: next,
  };
}

// The deploy request's policy (the dialog opens on it) and anything else
const OTHER = { data: { allowed_catalogs: [], allowed_schemas: [], default_catalog: null } };

function render(status: string) {
  renderWithProviders(
    <RequestContractActionDialog isOpen onOpenChange={vi.fn()} contractId="c-1"
      contractName="Orders" contractStatus={status} />,
  );
}

const requestType = (type: string) =>
  document.querySelector(`option[value="${type}"]`) as HTMLOptionElement;

describe('RequestContractActionDialog lifecycle', () => {
  beforeEach(() => vi.clearAllMocks());

  it('offers a review from a custom draft-category stage, not a publish', async () => {
    mockGet.mockImplementation(async (url: string) => url === '/api/lifecycle/data_contract/c-1'
      ? { data: lifecycle(st('ideation', 'draft', 0), [st('vetting', 'review', 1)]) }
      : OTHER);
    render('ideation');

    await waitFor(() => expect(requestType('review').disabled).toBe(false));
    expect(requestType('publish').disabled).toBe(true);
    // The status change offers the API's moves
    fireEvent.change(requestType('status_change').closest('select')!, {
      target: { value: 'status_change' },
    });
    expect(document.querySelector('option[value="vetting"]')).not.toBeNull();
  });

  it('offers a publish from a custom active-category stage, not a review', async () => {
    mockGet.mockImplementation(async (url: string) => url === '/api/lifecycle/data_contract/c-1'
      ? { data: lifecycle(st('live', 'active', 2), [st('sunset', 'deprecated', 3)]) }
      : OTHER);
    render('live');

    await waitFor(() => expect(requestType('publish').disabled).toBe(false));
    expect(requestType('review').disabled).toBe(true);
    expect(screen.queryByText('No transitions available from live status.')).toBeNull();
  });

  it('offers a publish from approved in the default lifecycle', async () => {
    mockGet.mockImplementation(async (url: string) => url === '/api/lifecycle/data_contract/c-1'
      ? { data: lifecycle(st('approved', 'review', 3), [st('active', 'active', 4)]) }
      : OTHER);
    render('approved');

    await waitFor(() => expect(requestType('publish').disabled).toBe(false));
  });

  it('shows the lifecycle loading, and no terminal state when it can’t be read', async () => {
    let answer: (value: unknown) => void = () => {};
    mockGet.mockImplementation((url: string) => url === '/api/lifecycle/data_contract/c-1'
      ? new Promise((resolve) => { answer = resolve; }) : Promise.resolve(OTHER));
    render('active');
    fireEvent.change(requestType('status_change').closest('select')!, {
      target: { value: 'status_change' },
    });

    expect(await screen.findByText('Loading the lifecycle…')).toBeInTheDocument();
    expect(screen.queryByText(/Terminal State/)).toBeNull();
    await act(async () => { answer({ data: null, error: 'Entity not found' }); });
    expect(await screen.findByText(/The lifecycle couldn’t be loaded/)).toBeInTheDocument();
    expect(screen.queryByText(/Terminal State/)).toBeNull();
  });

  it.each([
    ['active', false, true], ['approved', false, true], ['draft', true, false],
  ])('offers requests from %s while its lifecycle can’t be read', async (status, publishOff,
    reviewOff) => {
    mockGet.mockImplementation(async (url: string) => url === '/api/lifecycle/data_contract/c-1'
      ? { data: null, error: 'Entity not found' } : OTHER);
    render(status);

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/api/lifecycle/data_contract/c-1'));
    await act(async () => {});
    expect(requestType('publish').disabled).toBe(publishOff);
    expect(requestType('review').disabled).toBe(reviewOff);
  });
});

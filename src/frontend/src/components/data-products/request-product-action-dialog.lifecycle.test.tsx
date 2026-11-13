/**
 * The status change of a product offers the stages its Lifecycle Stage Group
 * allows next, from the API (#1215): no transition map in the frontend. A
 * custom stage shows its label; a move into a deprecated-category stage asks
 * for the deprecation details.
 *
 * The Radix Select hangs in jsdom, so it is replaced by a native select.
 */
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderWithProviders } from '@/test/utils';
import RequestProductActionDialog from './request-product-action-dialog';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockLookupWorkflowId = vi.fn();

vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock('@/hooks/use-api', () => ({ useApi: () => ({ get: mockGet, post: mockPost }) }));
vi.mock('@/hooks/use-approval-wizard-trigger', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/use-approval-wizard-trigger')>(
    '@/hooks/use-approval-wizard-trigger',
  );
  return {
    ...actual,
    useApprovalWizardTrigger: () => ({ lookupWorkflowId: mockLookupWorkflowId }),
  };
});
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
  SelectItem: ({ value, children }: any) => <option value={value}>{children}</option>,
}));

const stage = (key: string, label: string, category: string, order: number) => ({
  key, label, category, color: null, order, is_initial: false,
});

// Active in a looping group: Needs Review (review) or Sunset (deprecated) next
const LIFECYCLE = {
  entity_type: 'data_product', entity_id: 'prod-1', status: 'active',
  group: { id: 'g-loop', name: 'Authority resolution', entity_type: 'data_product',
    is_default_for_type: false },
  stage: stage('active', 'Active', 'active', 1),
  allowed_transitions: [
    stage('needs_review', 'Needs Review', 'review', 2),
    stage('sunset', 'Sunset', 'deprecated', 3),
  ],
  can_change_group: true,
};

function render() {
  renderWithProviders(
    <RequestProductActionDialog
      isOpen={true}
      onOpenChange={vi.fn()}
      productId="prod-1"
      productName="Orders"
      productStatus="active"
      defaultRequestType="status_change"
      canDirectStatusChange={true}
    />,
  );
}

const targetSelect = () => screen.getAllByRole('combobox').find(
  (select) => select.querySelector('option[value="needs_review"]'),
) as HTMLSelectElement | undefined;

describe('RequestProductActionDialog lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLookupWorkflowId.mockResolvedValue(null);
    mockGet.mockImplementation(async (url: string) =>
      url === '/api/lifecycle/data_product/prod-1' ? { data: LIFECYCLE } : { data: [] });
    mockPost.mockResolvedValue({ data: {} });
  });

  it('offers the stages the API allows next, by their labels', async () => {
    render();

    await waitFor(() => expect(targetSelect()).toBeDefined());
    const options = Array.from(targetSelect()!.querySelectorAll('option'))
      .map((o) => [o.value, o.textContent]).filter(([value]) => value);
    expect(options).toEqual([['needs_review', 'Needs Review'], ['sunset', 'Sunset']]);
    // Moving back into review needs no deprecation details
    fireEvent.change(targetSelect()!, { target: { value: 'needs_review' } });
    expect(document.getElementById('deprecation-reason')).toBeNull();
  });

  it('asks for deprecation details for a deprecated-category stage', async () => {
    render();

    await waitFor(() => expect(targetSelect()).toBeDefined());
    fireEvent.change(targetSelect()!, { target: { value: 'sunset' } });
    expect(document.getElementById('deprecation-reason')).not.toBeNull();
    fireEvent.change(document.getElementById('deprecation-reason') as HTMLTextAreaElement, {
      target: { value: 'Replaced by Orders v2 for every consumer.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Change Status' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost.mock.calls[0][0]).toBe('/api/data-products/prod-1/change-status');
    expect(mockPost.mock.calls[0][1]).toMatchObject({
      new_status: 'sunset', deprecation_reason: 'Replaced by Orders v2 for every consumer.',
    });
  });

  it('names the moves of the default lifecycle by their actions', async () => {
    mockGet.mockImplementation(async (url: string) => url === '/api/lifecycle/data_product/prod-1'
      ? { data: { ...LIFECYCLE, stage: stage('draft', 'Draft', 'draft', 0),
        allowed_transitions: [stage('sandbox', 'Sandbox', 'draft', 1),
          stage('proposed', 'Proposed', 'review', 2)] } }
      : { data: [] });
    render();

    await waitFor(() => expect(document.querySelector('option[value="proposed"]')).not.toBeNull());
    const select = document.querySelector('option[value="proposed"]')!.closest('select')!;
    expect(Array.from(select.querySelectorAll('option')).map((o) => o.textContent)
      .filter(Boolean)).toEqual(['Move to Sandbox', 'Submit for Review']);
  });
});

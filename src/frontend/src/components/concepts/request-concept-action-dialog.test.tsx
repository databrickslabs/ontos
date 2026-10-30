import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  RequestConceptActionDialog,
  type ConceptTransitionItem,
  type RequestConceptActionDialogProps,
} from './request-concept-action-dialog';

// Swap Radix Select for a native <select>: driving Radix's pointer/portal
// machinery through jsdom hung the CI runner. What matters here is which
// options exist and how the dialog adapts to the picked one.
vi.mock('@/components/ui/select', async () => {
  const React = await import('react');
  const SelectTrigger = (_: { 'aria-label'?: string; children?: React.ReactNode }) => null;
  const SelectValue = () => null;
  const SelectContent = ({ children }: { children?: React.ReactNode }) => <>{children}</>;
  const SelectItem = ({ value, children }: { value: string; children?: React.ReactNode }) => (
    <option value={value}>{children}</option>
  );
  const Select = ({
    value,
    onValueChange,
    children,
  }: {
    value?: string;
    onValueChange?: (v: string) => void;
    children?: React.ReactNode;
  }) => {
    let label: string | undefined;
    const options: React.ReactNode[] = [];
    React.Children.forEach(children, (child) => {
      if (!React.isValidElement(child)) return;
      const el = child as React.ReactElement<any>;
      if (el.type === SelectTrigger) label = el.props['aria-label'];
      else if (el.type === SelectContent) options.push(el);
    });
    return (
      <select aria-label={label} value={value} onChange={(e) => onValueChange?.(e.target.value)}>
        {options}
      </select>
    );
  };
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem };
});

const PICKER = 'What do you want to request?';

const reviewTransitions: ConceptTransitionItem[] = [
  { status: 'under_review', action: 'submit-review', labelKey: 'x:submit', defaultLabel: 'Submit' },
];
const reviewerTransitions: ConceptTransitionItem[] = [
  { status: 'approved', action: 'approve', labelKey: 'x:approve', defaultLabel: 'Approve' },
  { status: 'draft', action: 'reject', labelKey: 'x:requestChanges', defaultLabel: 'Request Changes' },
];

function renderDialog(overrides: Partial<RequestConceptActionDialogProps> = {}) {
  const props: RequestConceptActionDialogProps = {
    open: true,
    onOpenChange: vi.fn(),
    conceptLabel: 'Customer',
    currentStatus: 'draft',
    transitions: reviewTransitions,
    newVersion: { disabled: false, onSelect: vi.fn() },
    onTransition: vi.fn(),
    ...overrides,
  };
  const utils = render(<RequestConceptActionDialog {...props} />);
  return { ...utils, props };
}

describe('RequestConceptActionDialog', () => {
  it('lists every transition plus New Version and mentions the concept', () => {
    renderDialog({ transitions: [...reviewTransitions, ...reviewerTransitions] });
    expect(screen.getByText('Request Action')).toBeInTheDocument();
    expect(screen.getByText(/Customer/)).toBeInTheDocument();
    const select = screen.getByRole('combobox', { name: PICKER });
    const names = within(select)
      .getAllByRole('option')
      .map((o) => o.textContent);
    expect(names).toEqual(['Request Review', 'Approve', 'Request Changes', 'New Version']);
  });

  it('adapts the description and primary label to the selection', async () => {
    const user = userEvent.setup();
    renderDialog({ transitions: reviewerTransitions });
    const body = screen.getByTestId('request-concept-action-body');
    expect(within(body).getByText(/Approve this concept/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();

    const select = screen.getByRole('combobox', { name: PICKER });
    const changes = within(select).getByRole('option', { name: 'Request Changes' }) as HTMLOptionElement;
    await user.selectOptions(select, changes.value);
    expect(within(body).getByText(/back to draft/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Request Changes' })).toBeEnabled();

    const nv = within(select).getByRole('option', { name: 'New Version' }) as HTMLOptionElement;
    await user.selectOptions(select, nv.value);
    expect(within(body).getByText(/IRI stays the same/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create New Version' })).toBeEnabled();
  });

  it('confirm closes the dialog and calls onTransition with status and action', async () => {
    const user = userEvent.setup();
    const { props } = renderDialog();
    expect(screen.getByText(/reviewer is chosen in the next step/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Request Review' }));
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
    expect(props.onTransition).toHaveBeenCalledWith('under_review', 'submit-review');
    expect(props.newVersion!.onSelect).not.toHaveBeenCalled();
  });

  it('New Version calls newVersion.onSelect', async () => {
    const user = userEvent.setup();
    const { props } = renderDialog({ transitions: [] });
    await user.click(screen.getByRole('button', { name: 'Create New Version' }));
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
    expect(props.newVersion!.onSelect).toHaveBeenCalledTimes(1);
    expect(props.onTransition).not.toHaveBeenCalled();
  });

  it('disabled New Version shows the reason and cannot be confirmed', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderDialog({
      newVersion: { disabled: true, disabledReason: 'Publish the concept first.', onSelect },
    });
    // Default selection skips the disabled option.
    expect(screen.getByRole('button', { name: 'Request Review' })).toBeEnabled();

    const select = screen.getByRole('combobox', { name: PICKER });
    const nv = within(select).getByRole('option', { name: 'New Version' }) as HTMLOptionElement;
    await user.selectOptions(select, nv.value);
    expect(screen.getByText('Publish the concept first.')).toBeInTheDocument();
    const confirm = screen.getByRole('button', { name: 'Create New Version' });
    expect(confirm).toBeDisabled();
    await user.click(confirm);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('renders nothing when there is nothing to offer', () => {
    const { container } = renderDialog({ transitions: [], newVersion: null });
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText('Request Action')).not.toBeInTheDocument();
  });

  it('busy disables confirm', () => {
    renderDialog({ busy: true });
    expect(screen.getByRole('button', { name: 'Request Review' })).toBeDisabled();
  });

  it('resets the selection when reopened', async () => {
    const user = userEvent.setup();
    const props: RequestConceptActionDialogProps = {
      open: true,
      onOpenChange: vi.fn(),
      transitions: reviewerTransitions,
      newVersion: null,
      onTransition: vi.fn(),
    };
    const { rerender } = render(<RequestConceptActionDialog {...props} />);
    const select = screen.getByRole('combobox', { name: PICKER });
    const changes = within(select).getByRole('option', { name: 'Request Changes' }) as HTMLOptionElement;
    await user.selectOptions(select, changes.value);
    expect(screen.getByRole('button', { name: 'Request Changes' })).toBeInTheDocument();
    rerender(<RequestConceptActionDialog {...props} open={false} />);
    rerender(<RequestConceptActionDialog {...props} open />);
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument();
  });
});

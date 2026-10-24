import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { GuidedGenerateDialog, composeGuidedPrompt } from './guided-generate-dialog';

const mockUseDomains = vi.fn();
vi.mock('@/hooks/use-domains', () => ({
  useDomains: () => mockUseDomains(),
}));

const DOMAINS = [
  { id: 'd1', name: 'Finance', description: null },
  { id: 'd2', name: 'Logistics', description: null },
];

// Swap Radix Select for a native <select>: driving Radix's pointer/portal
// machinery through jsdom hung the CI runner. The dialog's behaviour (which
// options exist, what picking one does) is what this file tests.
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
      else options.push(el);
    });
    return (
      <select aria-label={label} value={value} onChange={(e) => onValueChange?.(e.target.value)}>
        {options}
      </select>
    );
  };
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem };
});

function GeneratorProbe() {
  const loc = useLocation();
  return <div data-testid="generator-search">{loc.search}</div>;
}

function renderDialog() {
  return render(
    <MemoryRouter initialEntries={['/concepts']}>
      <Routes>
        <Route path="/concepts" element={<GuidedGenerateDialog open onOpenChange={vi.fn()} />} />
        <Route path="/concepts/generator" element={<GeneratorProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('composeGuidedPrompt', () => {
  it('numbers non-blank questions and skips blanks', () => {
    const prompt = composeGuidedPrompt('Finance', ['Q one?', '  ', 'Q two?'], 'Invoice');
    expect(prompt).toBe(
      'Build a domain ontology for: Finance.\n' +
        'It should help answer these questions:\n1. Q one?\n2. Q two?\n' +
        'Key objects and concepts to model: Invoice.',
    );
  });

  it('omits the questions part when all questions are blank', () => {
    expect(composeGuidedPrompt('Finance', ['', ' '], '')).toBe('Build a domain ontology for: Finance.');
  });
});

describe('GuidedGenerateDialog', () => {
  beforeEach(() => {
    mockUseDomains.mockReturnValue({ domains: DOMAINS, loading: false, error: null });
  });

  it('renders real data domains in the dropdown and fills the domain field', async () => {
    const user = userEvent.setup();
    renderDialog();

    const select = screen.getByRole('combobox', { name: 'Data domain' });
    expect(within(select).getByRole('option', { name: 'Finance' })).toBeInTheDocument();
    expect(within(select).getByRole('option', { name: 'Logistics' })).toBeInTheDocument();
    expect(within(select).getByRole('option', { name: /No data domain/ })).toBeInTheDocument();
    // Hardcoded example chips are gone.
    expect(screen.queryByText('Supply chain')).not.toBeInTheDocument();

    await user.selectOptions(select, 'd2');
    expect(screen.getByLabelText('What domain are you working in?')).toHaveValue('Logistics');
  });

  it('shows a loading state while domains load', () => {
    mockUseDomains.mockReturnValue({ domains: [], loading: true, error: null });
    renderDialog();
    expect(screen.getByTestId('guided-domains-loading')).toBeInTheDocument();
  });

  it('shows a hint and keeps free text usable when no domains exist', async () => {
    mockUseDomains.mockReturnValue({ domains: [], loading: false, error: null });
    const user = userEvent.setup();
    renderDialog();
    expect(screen.getByTestId('guided-domains-empty')).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Data domain' })).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('What domain are you working in?'), 'Clinical trials');
    expect(screen.getByTestId('guided-prompt-preview')).toHaveTextContent(
      'Build a domain ontology for: Clinical trials.',
    );
  });

  it('composes multiple questions (Enter adds, blanks ignored, remove works) into the prompt', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.type(screen.getByLabelText('What domain are you working in?'), 'Finance');
    await user.type(screen.getByLabelText('Question 1'), 'Which invoices are overdue?{Enter}');
    // Enter in the last input added and focused a new one.
    expect(screen.getByLabelText('Question 2')).toHaveFocus();
    await user.keyboard('Temp question{Enter}');
    await user.type(screen.getByLabelText('Question 3'), 'Who owns each cost center?');
    await user.click(screen.getByRole('button', { name: 'Add question' }));
    // Question 4 stays blank and must be ignored. Remove question 2.
    await user.click(screen.getByRole('button', { name: 'Remove question 2' }));

    const preview = screen.getByTestId('guided-prompt-preview');
    expect(preview.textContent).toBe(
      'Build a domain ontology for: Finance.\n' +
        'It should help answer these questions:\n' +
        '1. Which invoices are overdue?\n2. Who owns each cost center?',
    );

    await user.click(screen.getByRole('button', { name: 'Continue to generator' }));
    const search = screen.getByTestId('generator-search').textContent ?? '';
    const guidelines = new URLSearchParams(search).get('guidelines');
    expect(guidelines).toBe(preview.textContent);
  });
});

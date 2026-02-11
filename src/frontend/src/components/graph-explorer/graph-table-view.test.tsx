import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GraphTableView } from './graph-table-view';
import type { GraphData } from '@/types/graph-explorer';

// Mock react-i18next — return the key as the display text
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

const sampleData: GraphData = {
  nodes: [
    { id: 'n1', label: 'Alice', type: 'Person', properties: { age: '30' }, status: 'existing' as const },
    { id: 'n2', label: 'Bob', type: 'Person', properties: { age: '25' }, status: 'existing' as const },
    { id: 'n3', label: 'Acme', type: 'Company', properties: {}, status: 'existing' as const },
  ],
  edges: [
    { id: 'e1', source: 'n1', target: 'n2', relationshipType: 'KNOWS', properties: {}, status: 'existing' as const },
    { id: 'e2', source: 'n1', target: 'n3', relationshipType: 'WORKS_AT', properties: {}, status: 'existing' as const },
  ],
};

const emptyData: GraphData = { nodes: [], edges: [] };

describe('GraphTableView', () => {
  it('renders the nodes tab by default', () => {
    render(<GraphTableView data={sampleData} />);
    // Should show node labels
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.getByText('Acme')).toBeInTheDocument();
  });

  it('shows correct node count in tab button', () => {
    render(<GraphTableView data={sampleData} />);
    expect(screen.getByText(/tableView\.nodes.*3/)).toBeInTheDocument();
  });

  it('shows correct edge count in tab button', () => {
    render(<GraphTableView data={sampleData} />);
    expect(screen.getByText(/tableView\.edges.*2/)).toBeInTheDocument();
  });

  it('switches to edges tab on click', async () => {
    const user = userEvent.setup();
    render(<GraphTableView data={sampleData} />);

    await user.click(screen.getByText(/tableView\.edges/));
    // Should show edge relationship types
    expect(screen.getByText('KNOWS')).toBeInTheDocument();
    expect(screen.getByText('WORKS_AT')).toBeInTheDocument();
  });

  it('shows empty state for nodes', () => {
    render(<GraphTableView data={emptyData} />);
    expect(screen.getByText('tableView.noNodes')).toBeInTheDocument();
  });

  it('shows empty state for edges', async () => {
    const user = userEvent.setup();
    render(<GraphTableView data={emptyData} />);

    await user.click(screen.getByText(/tableView\.edges/));
    expect(screen.getByText('tableView.noEdges')).toBeInTheDocument();
  });

  it('calls onNodeClick when a node row is clicked', async () => {
    const user = userEvent.setup();
    const onNodeClick = vi.fn();
    render(<GraphTableView data={sampleData} onNodeClick={onNodeClick} />);

    await user.click(screen.getByText('Alice'));
    expect(onNodeClick).toHaveBeenCalledWith('n1');
  });

  it('calls onEdgeClick when an edge row is clicked', async () => {
    const user = userEvent.setup();
    const onEdgeClick = vi.fn();
    render(<GraphTableView data={sampleData} onEdgeClick={onEdgeClick} />);

    await user.click(screen.getByText(/tableView\.edges/));
    await user.click(screen.getByText('KNOWS'));
    expect(onEdgeClick).toHaveBeenCalledWith('e1');
  });

  it('shows property columns for nodes', () => {
    render(<GraphTableView data={sampleData} />);
    // 'age' property should appear as a column header and values
    expect(screen.getByText('age')).toBeInTheDocument();
    expect(screen.getByText('30')).toBeInTheDocument();
    expect(screen.getByText('25')).toBeInTheDocument();
  });

  it('highlights selected node row', () => {
    const { container } = render(<GraphTableView data={sampleData} selectedNodeId="n1" />);
    // Find the row containing Alice and check it has the highlight class
    const aliceRow = screen.getByText('Alice').closest('tr');
    expect(aliceRow?.className).toContain('bg-primary/10');
  });
});

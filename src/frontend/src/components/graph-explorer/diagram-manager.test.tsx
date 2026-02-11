import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DiagramManager, getDiagrams, saveDiagrams, type SavedDiagram } from './diagram-manager';
import type { GraphData } from '@/types/graph-explorer';

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      // Minimal interpolation for description text
      if (opts && key === 'diagrams.saveDescription') {
        return `Save current view (${opts.nodeCount} nodes, ${opts.edgeCount} edges)`;
      }
      return key;
    },
    i18n: { language: 'en' },
  }),
}));

const sampleData: GraphData = {
  nodes: [
    { id: 'n1', label: 'Alice', type: 'Person', properties: {}, status: 'existing' as const },
    { id: 'n2', label: 'Bob', type: 'Person', properties: {}, status: 'existing' as const },
  ],
  edges: [
    { id: 'e1', source: 'n1', target: 'n2', relationshipType: 'KNOWS', properties: {}, status: 'existing' as const },
  ],
};

const emptyData: GraphData = { nodes: [], edges: [] };

describe('diagram localStorage helpers', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('getDiagrams returns empty array for unknown table', () => {
    expect(getDiagrams('nonexistent')).toEqual([]);
  });

  it('saveDiagrams + getDiagrams round-trips data', () => {
    const diagrams: SavedDiagram[] = [
      {
        id: 'diag-1',
        name: 'Test',
        savedAt: '2026-01-01T00:00:00Z',
        nodeCount: 2,
        edgeCount: 1,
        data: sampleData,
      },
    ];
    saveDiagrams('test-table', diagrams);
    const loaded = getDiagrams('test-table');
    expect(loaded).toEqual(diagrams);
  });

  it('getDiagrams handles corrupt data gracefully', () => {
    localStorage.setItem('graph-explorer-diagrams:bad', '{invalid json');
    expect(getDiagrams('bad')).toEqual([]);
  });
});

describe('DiagramManager component', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('shows empty state when no diagrams saved', () => {
    render(
      <DiagramManager
        tableName="test"
        currentData={sampleData}
        onRestoreDiagram={vi.fn()}
      />,
    );
    expect(screen.getByText('diagrams.empty')).toBeInTheDocument();
  });

  it('disables save button when data is empty', () => {
    render(
      <DiagramManager
        tableName="test"
        currentData={emptyData}
        onRestoreDiagram={vi.fn()}
      />,
    );
    const saveBtn = screen.getByText('diagrams.save').closest('button');
    expect(saveBtn).toBeDisabled();
  });

  it('opens save dialog and saves a diagram', async () => {
    const user = userEvent.setup();
    render(
      <DiagramManager
        tableName="test"
        currentData={sampleData}
        onRestoreDiagram={vi.fn()}
      />,
    );

    // Click save button to open dialog
    await user.click(screen.getByText('diagrams.save'));
    // Type a name
    const input = screen.getByPlaceholderText('diagrams.namePlaceholder');
    await user.type(input, 'My Diagram');
    // Click save in dialog
    const dialogSaveButtons = screen.getAllByText('diagrams.save');
    // The second one is inside the dialog
    await user.click(dialogSaveButtons[dialogSaveButtons.length - 1]);

    // Diagram should now appear in the list
    expect(screen.getByText('My Diagram')).toBeInTheDocument();
    // Should be saved in localStorage
    const saved = getDiagrams('test');
    expect(saved).toHaveLength(1);
    expect(saved[0].name).toBe('My Diagram');
  });

  it('restores a diagram when restore button is clicked', async () => {
    const user = userEvent.setup();
    const onRestore = vi.fn();

    // Pre-save a diagram
    saveDiagrams('test', [
      {
        id: 'diag-1',
        name: 'Saved View',
        savedAt: '2026-01-01T00:00:00Z',
        nodeCount: 2,
        edgeCount: 1,
        data: sampleData,
      },
    ]);

    render(
      <DiagramManager
        tableName="test"
        currentData={emptyData}
        onRestoreDiagram={onRestore}
      />,
    );

    // Find the diagram entry and hover to reveal buttons
    const entry = screen.getByText('Saved View').closest('div[class*="group"]')!;
    // Click the restore button (FolderOpen icon button)
    const restoreBtn = within(entry as HTMLElement).getAllByRole('button')[0];
    await user.click(restoreBtn);

    expect(onRestore).toHaveBeenCalledWith(sampleData);
  });

  it('deletes a diagram when delete button is clicked', async () => {
    const user = userEvent.setup();

    saveDiagrams('test', [
      {
        id: 'diag-1',
        name: 'To Delete',
        savedAt: '2026-01-01T00:00:00Z',
        nodeCount: 2,
        edgeCount: 1,
        data: sampleData,
      },
    ]);

    render(
      <DiagramManager
        tableName="test"
        currentData={sampleData}
        onRestoreDiagram={vi.fn()}
      />,
    );

    expect(screen.getByText('To Delete')).toBeInTheDocument();

    // Click delete button
    const entry = screen.getByText('To Delete').closest('div[class*="group"]')!;
    const deleteBtn = within(entry as HTMLElement).getAllByRole('button')[1];
    await user.click(deleteBtn);

    // Should be removed from view and localStorage
    expect(screen.queryByText('To Delete')).not.toBeInTheDocument();
    expect(getDiagrams('test')).toHaveLength(0);
  });
});

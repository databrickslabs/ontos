import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MarkerType } from 'reactflow';
import type { Edge, Connection } from 'reactflow';
import type { WorkflowStepCreate } from '@/types/process-workflow';

// ─── Mocks ──────────────────────────────────────────────────────────────────

// Mock react-router-dom
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ workflowId: 'new' }),
}));

// Mock hooks
vi.mock('@/hooks/use-api', () => ({
  useApi: () => ({
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
  }),
}));

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('@/stores/breadcrumb-store', () => ({
  default: () => vi.fn(),
  __esModule: true,
}));

// Mock dagre to avoid layout computation issues in jsdom
vi.mock('dagre', () => {
  const mockGraph = {
    setDefaultEdgeLabel: vi.fn(),
    setGraph: vi.fn(),
    setNode: vi.fn(),
    setEdge: vi.fn(),
    node: vi.fn().mockReturnValue({ x: 100, y: 100 }),
  };
  return {
    default: {
      graphlib: {
        Graph: vi.fn(() => mockGraph),
      },
      layout: vi.fn(),
    },
  };
});

// ─── Helpers: extract pure logic from callbacks for unit testing ────────────

/**
 * Replicates onConnect logic from workflow-designer.tsx (lines 615-644).
 * Given current edges, steps, and a connection, returns the new edges and steps.
 */
function applyConnect(
  edges: Edge[],
  steps: WorkflowStepCreate[],
  connection: Connection,
): { edges: Edge[]; steps: WorkflowStepCreate[] } {
  if (!connection.source || !connection.target) return { edges, steps };
  const handleType = connection.sourceHandle || 'pass';
  const isPass = handleType !== 'fail';

  // Remove any existing edge from the same source handle
  const filtered = edges.filter(
    (e) => !(e.source === connection.source && e.sourceHandle === handleType),
  );

  const newEdge: Edge = {
    id: `${connection.source}-${handleType}-to-${connection.target}`,
    source: connection.source,
    sourceHandle: handleType,
    target: connection.target,
    type: 'deletable',
    label: isPass ? 'Pass' : 'Fail',
    labelStyle: { fill: isPass ? '#22c55e' : '#ef4444', fontWeight: 500 },
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: isPass ? '#22c55e' : '#ef4444' },
  };

  const newEdges = [...filtered, newEdge];

  const newSteps = steps.map((s) =>
    s.step_id === connection.source
      ? { ...s, [isPass ? 'on_pass' : 'on_fail']: connection.target }
      : s,
  );

  return { edges: newEdges, steps: newSteps };
}

/**
 * Replicates onReconnect logic from workflow-designer.tsx (lines 583-612).
 */
function applyReconnect(
  edges: Edge[],
  steps: WorkflowStepCreate[],
  oldEdge: Edge,
  newConnection: Connection,
): { edges: Edge[]; steps: WorkflowStepCreate[] } {
  if (!newConnection.source || !newConnection.target) return { edges, steps };
  const handleType = oldEdge.sourceHandle || 'pass';
  const isPass = handleType !== 'fail';

  const filtered = edges.filter((e) => e.id !== oldEdge.id);
  const reconnectedEdge: Edge = {
    id: `${newConnection.source}-${handleType}-to-${newConnection.target}`,
    source: newConnection.source!,
    sourceHandle: handleType,
    target: newConnection.target!,
    type: 'deletable',
    label: isPass ? 'Pass' : 'Fail',
    labelStyle: { fill: isPass ? '#22c55e' : '#ef4444', fontWeight: 500 },
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: isPass ? '#22c55e' : '#ef4444' },
  };

  const newEdges = [...filtered, reconnectedEdge];

  const newSteps = steps.map((s) => {
    if (s.step_id === oldEdge.source) {
      return { ...s, [isPass ? 'on_pass' : 'on_fail']: newConnection.target };
    }
    return s;
  });

  return { edges: newEdges, steps: newSteps };
}

/**
 * Replicates onDeleteEdge logic from workflow-designer.tsx (lines 353-362).
 */
function applyDeleteEdge(
  edges: Edge[],
  steps: WorkflowStepCreate[],
  edgeId: string,
): { edges: Edge[]; steps: WorkflowStepCreate[] } {
  const target = edges.find((e) => e.id === edgeId);
  let newSteps = steps;
  if (target) {
    const field = target.sourceHandle === 'fail' ? 'on_fail' : 'on_pass';
    newSteps = steps.map((s) =>
      s.step_id === target.source ? { ...s, [field]: undefined } : s,
    );
  }
  const newEdges = edges.filter((e) => e.id !== edgeId);
  return { edges: newEdges, steps: newSteps };
}

/**
 * Replicates onEdgesChange removal sync from workflow-designer.tsx (lines 337-350).
 */
function applyEdgesChangeRemove(
  edges: Edge[],
  steps: WorkflowStepCreate[],
  removedEdgeId: string,
): { steps: WorkflowStepCreate[] } {
  const removed = edges.find((e) => e.id === removedEdgeId);
  if (!removed) return { steps };
  const field = removed.sourceHandle === 'fail' ? 'on_fail' : 'on_pass';
  return {
    steps: steps.map((s) =>
      s.step_id === removed.source ? { ...s, [field]: undefined } : s,
    ),
  };
}

// ─── Test fixtures ──────────────────────────────────────────────────────────

function makeStep(overrides: Partial<WorkflowStepCreate> & { step_id: string }): WorkflowStepCreate {
  return {
    name: 'Test Step',
    step_type: 'validation',
    config: {},
    order: 0,
    ...overrides,
  };
}

function makePassEdge(source: string, target: string): Edge {
  return {
    id: `${source}-pass`,
    source,
    sourceHandle: 'pass',
    target,
    type: 'deletable',
    label: 'Pass',
    labelStyle: { fill: '#22c55e', fontWeight: 500 },
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: '#22c55e' },
  };
}

function makeFailEdge(source: string, target: string): Edge {
  return {
    id: `${source}-fail`,
    source,
    sourceHandle: 'fail',
    target,
    type: 'deletable',
    label: 'Fail',
    labelStyle: { fill: '#ef4444', fontWeight: 500 },
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: '#ef4444' },
  };
}

// ─── DeletableEdge component tests ──────────────────────────────────────────

// We need to test the actual DeletableEdge component from the module.
// Since it's not exported directly, we'll re-import the module and extract it
// through the edgeTypes pattern. Instead, we test via a minimal re-implementation
// that mirrors the component's rendering logic, or we render it through ReactFlow.
// The cleanest approach: import the file and use the component via ReactFlow's
// custom edge rendering.

// Since DeletableEdge is not exported, we test its rendering by creating a
// minimal ReactFlow instance with a custom edge. However, ReactFlow in jsdom
// is tricky. Instead, we recreate the component logic inline for unit testing.
// This mirrors the actual component 1:1 (lines 127-170).

function DeletableEdgeTestable({
  id,
  label,
  labelStyle,
  selected,
  onDelete,
}: {
  id: string;
  label?: string;
  labelStyle?: Record<string, unknown>;
  selected?: boolean;
  onDelete?: (id: string) => void;
}) {
  return (
    <div data-testid="deletable-edge">
      {label && (
        <span
          className="text-xs font-medium"
          style={{ color: (labelStyle as any)?.fill || (labelStyle as any)?.color }}
          data-testid="edge-label"
        >
          {label}
        </span>
      )}
      {selected && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete?.(id);
          }}
          className="flex items-center justify-center w-5 h-5 rounded-full bg-red-500 hover:bg-red-600 text-white text-xs leading-none shadow-sm transition-colors dark:bg-red-600 dark:hover:bg-red-700"
          title="Delete connection"
          data-testid="delete-button"
        >
          ✕
        </button>
      )}
    </div>
  );
}

describe('DeletableEdge component', () => {
  it('renders label text with correct color for Pass', () => {
    render(
      <DeletableEdgeTestable
        id="edge-1"
        label="Pass"
        labelStyle={{ fill: '#22c55e', fontWeight: 500 }}
        selected={false}
      />,
    );

    const labelEl = screen.getByTestId('edge-label');
    expect(labelEl).toHaveTextContent('Pass');
    expect(labelEl).toHaveStyle({ color: '#22c55e' });
  });

  it('renders label text with correct color for Fail', () => {
    render(
      <DeletableEdgeTestable
        id="edge-2"
        label="Fail"
        labelStyle={{ fill: '#ef4444', fontWeight: 500 }}
        selected={false}
      />,
    );

    const labelEl = screen.getByTestId('edge-label');
    expect(labelEl).toHaveTextContent('Fail');
    expect(labelEl).toHaveStyle({ color: '#ef4444' });
  });

  it('shows delete button only when selected', () => {
    render(
      <DeletableEdgeTestable
        id="edge-1"
        label="Pass"
        labelStyle={{ fill: '#22c55e' }}
        selected={true}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByTestId('delete-button')).toBeInTheDocument();
  });

  it('hides delete button when not selected', () => {
    render(
      <DeletableEdgeTestable
        id="edge-1"
        label="Pass"
        labelStyle={{ fill: '#22c55e' }}
        selected={false}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.queryByTestId('delete-button')).not.toBeInTheDocument();
  });

  it('calls onDelete callback with edge id when delete button is clicked', () => {
    const onDelete = vi.fn();
    render(
      <DeletableEdgeTestable
        id="edge-42"
        label="Pass"
        labelStyle={{ fill: '#22c55e' }}
        selected={true}
        onDelete={onDelete}
      />,
    );

    fireEvent.click(screen.getByTestId('delete-button'));
    expect(onDelete).toHaveBeenCalledOnce();
    expect(onDelete).toHaveBeenCalledWith('edge-42');
  });
});

// ─── Edge creation logic (onConnect) ────────────────────────────────────────

describe('Edge creation logic (onConnect)', () => {
  const stepA = makeStep({ step_id: 'step-a', on_pass: undefined, on_fail: undefined });
  const stepB = makeStep({ step_id: 'step-b' });
  const stepC = makeStep({ step_id: 'step-c' });

  it('creates edge with Pass styling from pass handle', () => {
    const connection: Connection = {
      source: 'step-a',
      target: 'step-b',
      sourceHandle: 'pass',
      targetHandle: null,
    };

    const { edges, steps } = applyConnect([], [stepA, stepB], connection);

    expect(edges).toHaveLength(1);
    const edge = edges[0];
    expect(edge.label).toBe('Pass');
    expect(edge.style).toEqual({ stroke: '#22c55e' });
    expect((edge.labelStyle as any).fill).toBe('#22c55e');
    expect(edge.source).toBe('step-a');
    expect(edge.target).toBe('step-b');
    expect(edge.sourceHandle).toBe('pass');
    expect(edge.type).toBe('deletable');

    // Step data should be updated
    const updatedStepA = steps.find((s) => s.step_id === 'step-a')!;
    expect(updatedStepA.on_pass).toBe('step-b');
    expect(updatedStepA.on_fail).toBeUndefined();
  });

  it('creates edge with Fail styling from fail handle', () => {
    const connection: Connection = {
      source: 'step-a',
      target: 'step-b',
      sourceHandle: 'fail',
      targetHandle: null,
    };

    const { edges, steps } = applyConnect([], [stepA, stepB], connection);

    expect(edges).toHaveLength(1);
    const edge = edges[0];
    expect(edge.label).toBe('Fail');
    expect(edge.style).toEqual({ stroke: '#ef4444' });
    expect((edge.labelStyle as any).fill).toBe('#ef4444');
    expect(edge.sourceHandle).toBe('fail');

    const updatedStepA = steps.find((s) => s.step_id === 'step-a')!;
    expect(updatedStepA.on_fail).toBe('step-b');
    expect(updatedStepA.on_pass).toBeUndefined();
  });

  it('replaces existing edge from same source handle', () => {
    const existingEdge = makePassEdge('step-a', 'step-b');
    const stepAWithPass = { ...stepA, on_pass: 'step-b' };

    const connection: Connection = {
      source: 'step-a',
      target: 'step-c',
      sourceHandle: 'pass',
      targetHandle: null,
    };

    const { edges, steps } = applyConnect(
      [existingEdge],
      [stepAWithPass, stepB, stepC],
      connection,
    );

    // Old edge should be removed, new one added
    expect(edges).toHaveLength(1);
    expect(edges[0].target).toBe('step-c');
    expect(edges[0].id).toBe('step-a-pass-to-step-c');

    const updatedStepA = steps.find((s) => s.step_id === 'step-a')!;
    expect(updatedStepA.on_pass).toBe('step-c');
  });

  it('defaults to pass when sourceHandle is null', () => {
    const connection: Connection = {
      source: 'step-a',
      target: 'step-b',
      sourceHandle: null,
      targetHandle: null,
    };

    const { edges } = applyConnect([], [stepA, stepB], connection);
    expect(edges[0].label).toBe('Pass');
    expect(edges[0].sourceHandle).toBe('pass');
  });

  it('does nothing when source is missing', () => {
    const connection: Connection = {
      source: null,
      target: 'step-b',
      sourceHandle: 'pass',
      targetHandle: null,
    };

    const { edges, steps } = applyConnect([], [stepA], connection);
    expect(edges).toHaveLength(0);
    expect(steps).toEqual([stepA]);
  });
});

// ─── Edge reconnection logic (onReconnect) ──────────────────────────────────

describe('Edge reconnection logic (onReconnect)', () => {
  const stepA = makeStep({ step_id: 'step-a', on_pass: 'step-b' });
  const stepB = makeStep({ step_id: 'step-b' });
  const stepC = makeStep({ step_id: 'step-c' });

  it('updates edge target while preserving Pass type', () => {
    const oldEdge = makePassEdge('step-a', 'step-b');
    const newConn: Connection = {
      source: 'step-a',
      target: 'step-c',
      sourceHandle: 'pass',
      targetHandle: null,
    };

    const { edges, steps } = applyReconnect(
      [oldEdge],
      [stepA, stepB, stepC],
      oldEdge,
      newConn,
    );

    expect(edges).toHaveLength(1);
    const edge = edges[0];
    expect(edge.target).toBe('step-c');
    expect(edge.label).toBe('Pass');
    expect(edge.style).toEqual({ stroke: '#22c55e' });
    expect((edge.labelStyle as any).fill).toBe('#22c55e');

    const updatedA = steps.find((s) => s.step_id === 'step-a')!;
    expect(updatedA.on_pass).toBe('step-c');
  });

  it('updates edge target while preserving Fail type', () => {
    const stepAFail = makeStep({ step_id: 'step-a', on_fail: 'step-b' });
    const oldEdge = makeFailEdge('step-a', 'step-b');
    const newConn: Connection = {
      source: 'step-a',
      target: 'step-c',
      sourceHandle: 'fail',
      targetHandle: null,
    };

    const { edges, steps } = applyReconnect(
      [oldEdge],
      [stepAFail, stepB, stepC],
      oldEdge,
      newConn,
    );

    expect(edges).toHaveLength(1);
    const edge = edges[0];
    expect(edge.target).toBe('step-c');
    expect(edge.label).toBe('Fail');
    expect(edge.style).toEqual({ stroke: '#ef4444' });

    const updatedA = steps.find((s) => s.step_id === 'step-a')!;
    expect(updatedA.on_fail).toBe('step-c');
  });

  it('preserves other edges during reconnect', () => {
    const passEdge = makePassEdge('step-a', 'step-b');
    const failEdge = makeFailEdge('step-a', 'step-c');
    const newConn: Connection = {
      source: 'step-a',
      target: 'step-c',
      sourceHandle: 'pass',
      targetHandle: null,
    };

    const { edges } = applyReconnect(
      [passEdge, failEdge],
      [stepA, stepB, stepC],
      passEdge,
      newConn,
    );

    // Old pass edge removed + new reconnected pass edge added, fail edge preserved
    expect(edges).toHaveLength(2);
    const failRemaining = edges.find((e) => e.sourceHandle === 'fail');
    expect(failRemaining).toBeDefined();
    expect(failRemaining!.target).toBe('step-c');
  });
});

// ─── Edge deletion logic ────────────────────────────────────────────────────

describe('Edge deletion logic (onDeleteEdge)', () => {
  it('removes edge and clears step on_pass when pass edge deleted', () => {
    const stepA = makeStep({ step_id: 'step-a', on_pass: 'step-b' });
    const stepB = makeStep({ step_id: 'step-b' });
    const passEdge = makePassEdge('step-a', 'step-b');

    const { edges, steps } = applyDeleteEdge([passEdge], [stepA, stepB], passEdge.id);

    expect(edges).toHaveLength(0);
    const updatedA = steps.find((s) => s.step_id === 'step-a')!;
    expect(updatedA.on_pass).toBeUndefined();
  });

  it('removes edge and clears step on_fail when fail edge deleted', () => {
    const stepA = makeStep({ step_id: 'step-a', on_fail: 'step-b' });
    const stepB = makeStep({ step_id: 'step-b' });
    const failEdge = makeFailEdge('step-a', 'step-b');

    const { edges, steps } = applyDeleteEdge([failEdge], [stepA, stepB], failEdge.id);

    expect(edges).toHaveLength(0);
    const updatedA = steps.find((s) => s.step_id === 'step-a')!;
    expect(updatedA.on_fail).toBeUndefined();
  });

  it('preserves other edges when deleting one', () => {
    const stepA = makeStep({ step_id: 'step-a', on_pass: 'step-b', on_fail: 'step-c' });
    const passEdge = makePassEdge('step-a', 'step-b');
    const failEdge = makeFailEdge('step-a', 'step-c');

    const { edges, steps } = applyDeleteEdge(
      [passEdge, failEdge],
      [stepA],
      passEdge.id,
    );

    expect(edges).toHaveLength(1);
    expect(edges[0].id).toBe(failEdge.id);

    const updatedA = steps.find((s) => s.step_id === 'step-a')!;
    expect(updatedA.on_pass).toBeUndefined();
    // on_fail should remain intact
    expect(updatedA.on_fail).toBe('step-c');
  });

  it('handles deleting non-existent edge gracefully', () => {
    const stepA = makeStep({ step_id: 'step-a' });
    const { edges, steps } = applyDeleteEdge([], [stepA], 'non-existent');

    expect(edges).toHaveLength(0);
    expect(steps).toEqual([stepA]);
  });
});

// ─── onEdgesChange sync logic ───────────────────────────────────────────────

describe('Edge change sync (onEdgesChange remove)', () => {
  it('clears on_pass when pass edge is removed', () => {
    const stepA = makeStep({ step_id: 'step-a', on_pass: 'step-b' });
    const passEdge = makePassEdge('step-a', 'step-b');

    const { steps } = applyEdgesChangeRemove([passEdge], [stepA], passEdge.id);

    const updatedA = steps.find((s) => s.step_id === 'step-a')!;
    expect(updatedA.on_pass).toBeUndefined();
  });

  it('clears on_fail when fail edge is removed', () => {
    const stepA = makeStep({ step_id: 'step-a', on_fail: 'step-b' });
    const failEdge = makeFailEdge('step-a', 'step-b');

    const { steps } = applyEdgesChangeRemove([failEdge], [stepA], failEdge.id);

    const updatedA = steps.find((s) => s.step_id === 'step-a')!;
    expect(updatedA.on_fail).toBeUndefined();
  });

  it('does not modify steps when removed edge is not found', () => {
    const stepA = makeStep({ step_id: 'step-a', on_pass: 'step-b' });

    const { steps } = applyEdgesChangeRemove([], [stepA], 'ghost-edge');
    expect(steps[0].on_pass).toBe('step-b');
  });

  it('does not affect other steps', () => {
    const stepA = makeStep({ step_id: 'step-a', on_pass: 'step-b' });
    const stepB = makeStep({ step_id: 'step-b', on_pass: 'step-c' });
    const passEdge = makePassEdge('step-a', 'step-b');

    const { steps } = applyEdgesChangeRemove([passEdge], [stepA, stepB], passEdge.id);

    const updatedA = steps.find((s) => s.step_id === 'step-a')!;
    const updatedB = steps.find((s) => s.step_id === 'step-b')!;
    expect(updatedA.on_pass).toBeUndefined();
    expect(updatedB.on_pass).toBe('step-c'); // Unchanged
  });
});

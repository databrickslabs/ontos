import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  GraphContextMenu,
  type GraphContextMenuProps,
  type ContextMenuTarget,
  type ContextMenuPosition,
} from './graph-context-menu';

// Mock react-i18next — return the key as the display text
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

// Mock navigator.clipboard
const mockWriteText = vi.fn().mockResolvedValue(undefined);

describe('GraphContextMenu', () => {
  const defaultPosition: ContextMenuPosition = { x: 100, y: 200 };

  const defaultCallbacks = {
    onClose: vi.fn(),
    onExpandNeighbors: vi.fn(),
    onExpandByType: vi.fn(),
    onCollapseNode: vi.fn(),
    onEditNode: vi.fn(),
    onDeleteNode: vi.fn(),
    onCenterOnNode: vi.fn(),
    onEditEdge: vi.fn(),
    onDeleteEdge: vi.fn(),
    onCreateNode: vi.fn(),
    onResetView: vi.fn(),
    onFitToScreen: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockWriteText.mockResolvedValue(undefined);
    // Ensure navigator.clipboard.writeText is our mock
    if (!navigator.clipboard || navigator.clipboard.writeText !== mockWriteText) {
      Object.defineProperty(global.navigator, 'clipboard', {
        value: { writeText: mockWriteText },
        writable: true,
        configurable: true,
      });
    }
  });

  function renderMenu(overrides: Partial<GraphContextMenuProps> = {}) {
    return render(
      <GraphContextMenu
        position={defaultPosition}
        target={null}
        {...defaultCallbacks}
        {...overrides}
      />,
    );
  }

  // -------------------------------------------------------------------
  // Visibility
  // -------------------------------------------------------------------
  it('renders nothing when position is null', () => {
    const { container } = renderMenu({ position: null });
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when target is null', () => {
    const { container } = renderMenu({ target: null });
    expect(container.innerHTML).toBe('');
  });

  // -------------------------------------------------------------------
  // Node context menu
  // -------------------------------------------------------------------
  describe('node context menu', () => {
    const nodeTarget: ContextMenuTarget = {
      type: 'node',
      id: 'node-1',
      label: 'Alice',
      nodeType: 'Person',
      isExpanded: false,
      connectedEdgeTypes: ['KNOWS', 'WORKS_AT'],
    };

    it('renders node menu items', () => {
      renderMenu({ target: nodeTarget });
      // Header
      expect(screen.getByText(/Alice/)).toBeInTheDocument();
      // Expand all neighbors
      expect(screen.getByText('contextMenu.expandAll')).toBeInTheDocument();
      // Edit, Delete, Center, Copy
      expect(screen.getByText('contextMenu.editNode')).toBeInTheDocument();
      expect(screen.getByText('contextMenu.deleteNode')).toBeInTheDocument();
      expect(screen.getByText('contextMenu.centerOnNode')).toBeInTheDocument();
      expect(screen.getByText('contextMenu.copyNodeId')).toBeInTheDocument();
    });

    it('calls onExpandNeighbors with "both" when expand all is clicked', async () => {
      const user = userEvent.setup();
      renderMenu({ target: nodeTarget });
      await user.click(screen.getByText('contextMenu.expandAll'));
      expect(defaultCallbacks.onExpandNeighbors).toHaveBeenCalledWith('node-1', 'both');
      expect(defaultCallbacks.onClose).toHaveBeenCalled();
    });

    it('calls onEditNode when edit is clicked', async () => {
      const user = userEvent.setup();
      renderMenu({ target: nodeTarget });
      await user.click(screen.getByText('contextMenu.editNode'));
      expect(defaultCallbacks.onEditNode).toHaveBeenCalledWith('node-1');
      expect(defaultCallbacks.onClose).toHaveBeenCalled();
    });

    it('calls onDeleteNode when delete is clicked', async () => {
      const user = userEvent.setup();
      renderMenu({ target: nodeTarget });
      await user.click(screen.getByText('contextMenu.deleteNode'));
      expect(defaultCallbacks.onDeleteNode).toHaveBeenCalledWith('node-1');
      expect(defaultCallbacks.onClose).toHaveBeenCalled();
    });

    it('calls onCenterOnNode when center is clicked', async () => {
      const user = userEvent.setup();
      renderMenu({ target: nodeTarget });
      await user.click(screen.getByText('contextMenu.centerOnNode'));
      expect(defaultCallbacks.onCenterOnNode).toHaveBeenCalledWith('node-1');
      expect(defaultCallbacks.onClose).toHaveBeenCalled();
    });

    it('copies node ID to clipboard when copy is clicked', async () => {
      renderMenu({ target: nodeTarget });
      fireEvent.click(screen.getByText('contextMenu.copyNodeId'));
      // navigator.clipboard.writeText returns a Promise, so wait a tick
      await vi.waitFor(() => {
        expect(mockWriteText).toHaveBeenCalledWith('node-1');
      });
      expect(defaultCallbacks.onClose).toHaveBeenCalled();
    });

    it('shows collapse instead of expand sub-menu when node is expanded', () => {
      const expandedTarget: ContextMenuTarget = { ...nodeTarget, isExpanded: true };
      renderMenu({ target: expandedTarget });
      expect(screen.getByText('contextMenu.collapse')).toBeInTheDocument();
      // Expand all should still be present (re-expand)
      expect(screen.getByText('contextMenu.expandAll')).toBeInTheDocument();
    });

    it('calls onCollapseNode when collapse is clicked', async () => {
      const user = userEvent.setup();
      const expandedTarget: ContextMenuTarget = { ...nodeTarget, isExpanded: true };
      renderMenu({ target: expandedTarget });
      await user.click(screen.getByText('contextMenu.collapse'));
      expect(defaultCallbacks.onCollapseNode).toHaveBeenCalledWith('node-1');
      expect(defaultCallbacks.onClose).toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------
  // Edge context menu
  // -------------------------------------------------------------------
  describe('edge context menu', () => {
    const edgeTarget: ContextMenuTarget = {
      type: 'edge',
      id: 'edge-1',
      relationshipType: 'KNOWS',
    };

    it('renders edge menu items', () => {
      renderMenu({ target: edgeTarget });
      expect(screen.getByText('KNOWS')).toBeInTheDocument();
      expect(screen.getByText('contextMenu.editEdge')).toBeInTheDocument();
      expect(screen.getByText('contextMenu.deleteEdge')).toBeInTheDocument();
      expect(screen.getByText('contextMenu.copyEdgeDetails')).toBeInTheDocument();
    });

    it('calls onEditEdge when edit is clicked', async () => {
      const user = userEvent.setup();
      renderMenu({ target: edgeTarget });
      await user.click(screen.getByText('contextMenu.editEdge'));
      expect(defaultCallbacks.onEditEdge).toHaveBeenCalledWith('edge-1');
      expect(defaultCallbacks.onClose).toHaveBeenCalled();
    });

    it('calls onDeleteEdge when delete is clicked', async () => {
      const user = userEvent.setup();
      renderMenu({ target: edgeTarget });
      await user.click(screen.getByText('contextMenu.deleteEdge'));
      expect(defaultCallbacks.onDeleteEdge).toHaveBeenCalledWith('edge-1');
      expect(defaultCallbacks.onClose).toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------
  // Canvas context menu
  // -------------------------------------------------------------------
  describe('canvas context menu', () => {
    const canvasTarget: ContextMenuTarget = { type: 'canvas' };

    it('renders canvas menu items', () => {
      renderMenu({ target: canvasTarget });
      expect(screen.getByText('contextMenu.createNode')).toBeInTheDocument();
      expect(screen.getByText('contextMenu.fitToScreen')).toBeInTheDocument();
      expect(screen.getByText('contextMenu.resetView')).toBeInTheDocument();
    });

    it('calls onCreateNode when create node is clicked', async () => {
      const user = userEvent.setup();
      renderMenu({ target: canvasTarget });
      await user.click(screen.getByText('contextMenu.createNode'));
      expect(defaultCallbacks.onCreateNode).toHaveBeenCalled();
      expect(defaultCallbacks.onClose).toHaveBeenCalled();
    });

    it('calls onFitToScreen when fit to screen is clicked', async () => {
      const user = userEvent.setup();
      renderMenu({ target: canvasTarget });
      await user.click(screen.getByText('contextMenu.fitToScreen'));
      expect(defaultCallbacks.onFitToScreen).toHaveBeenCalled();
      expect(defaultCallbacks.onClose).toHaveBeenCalled();
    });

    it('calls onResetView when reset view is clicked', async () => {
      const user = userEvent.setup();
      renderMenu({ target: canvasTarget });
      await user.click(screen.getByText('contextMenu.resetView'));
      expect(defaultCallbacks.onResetView).toHaveBeenCalled();
      expect(defaultCallbacks.onClose).toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------
  // Dismiss behavior
  // -------------------------------------------------------------------
  describe('dismiss behavior', () => {
    it('calls onClose when Escape is pressed', async () => {
      renderMenu({ target: { type: 'canvas' } });
      // Wait for the event listener to be attached (setTimeout(0) in the component)
      await vi.waitFor(() => {
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(defaultCallbacks.onClose).toHaveBeenCalled();
      });
    });

    it('calls onClose when clicking outside the menu', async () => {
      renderMenu({ target: { type: 'canvas' } });
      // Wait for the event listener to be attached
      await vi.waitFor(() => {
        fireEvent.mouseDown(document.body);
        expect(defaultCallbacks.onClose).toHaveBeenCalled();
      });
    });
  });

  // -------------------------------------------------------------------
  // Position adjustment
  // -------------------------------------------------------------------
  describe('position adjustment', () => {
    it('renders at the provided position', () => {
      const { container } = renderMenu({
        target: { type: 'canvas' },
        position: { x: 150, y: 250 },
      });
      const menuEl = container.firstElementChild as HTMLElement;
      expect(menuEl.style.left).toBe('150px');
      expect(menuEl.style.top).toBe('250px');
    });
  });
});

/**
 * Context menu for Graph Explorer.
 *
 * Renders a positioned menu overlay triggered by right-click on nodes, edges,
 * or the canvas background. Since the graph is rendered on a <canvas>, Radix
 * context-menu (DOM trigger-based) can't be used directly, so we build a custom
 * positioned menu with Shadcn-consistent styling.
 */

import React, { useEffect, useRef, useCallback } from 'react';
import { cn } from '@/lib/utils';
import {
  Expand,
  ArrowUpRight,
  ArrowDownLeft,
  Shrink,
  Pencil,
  Trash2,
  Copy,
  Crosshair,
  Maximize,
  Plus,
  ChevronRight,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ContextMenuTargetType = 'node' | 'edge' | 'canvas';

export interface ContextMenuTarget {
  type: ContextMenuTargetType;
  /** Node or edge ID */
  id?: string;
  /** Node label for display */
  label?: string;
  /** Node type for display */
  nodeType?: string;
  /** Edge relationship type for display */
  relationshipType?: string;
  /** Whether this node is currently expanded (has neighbor data loaded) */
  isExpanded?: boolean;
  /** Edge types connected to this node (for "Expand by Type" submenu) */
  connectedEdgeTypes?: string[];
}

export interface ContextMenuPosition {
  x: number;
  y: number;
}

interface MenuItemProps {
  icon?: React.ReactNode;
  label: string;
  onClick: () => void;
  variant?: 'default' | 'destructive';
  disabled?: boolean;
}

interface SubMenuProps {
  icon?: React.ReactNode;
  label: string;
  children: React.ReactNode;
}

// ---------------------------------------------------------------------------
// Menu item and sub-menu components
// ---------------------------------------------------------------------------

function MenuItem({ icon, label, onClick, variant = 'default', disabled = false }: MenuItemProps) {
  return (
    <button
      className={cn(
        'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none transition-colors',
        'hover:bg-accent hover:text-accent-foreground',
        'focus-visible:bg-accent focus-visible:text-accent-foreground',
        variant === 'destructive' && 'text-destructive hover:bg-destructive/10 hover:text-destructive',
        disabled && 'pointer-events-none opacity-50',
      )}
      onClick={(e) => {
        e.stopPropagation();
        if (!disabled) onClick();
      }}
      disabled={disabled}
    >
      {icon && <span className="flex-shrink-0 w-4 h-4">{icon}</span>}
      <span>{label}</span>
    </button>
  );
}

function SubMenu({ icon, label, children }: SubMenuProps) {
  const [isOpen, setIsOpen] = React.useState(false);
  const subMenuRef = useRef<HTMLDivElement>(null);

  return (
    <div
      className="relative"
      onMouseEnter={() => setIsOpen(true)}
      onMouseLeave={() => setIsOpen(false)}
    >
      <div
        className={cn(
          'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm cursor-default',
          'hover:bg-accent hover:text-accent-foreground',
          isOpen && 'bg-accent text-accent-foreground',
        )}
      >
        {icon && <span className="flex-shrink-0 w-4 h-4">{icon}</span>}
        <span className="flex-1">{label}</span>
        <ChevronRight className="h-3.5 w-3.5 ml-auto opacity-60" />
      </div>

      {isOpen && (
        <div
          ref={subMenuRef}
          className={cn(
            'absolute left-full top-0 z-50 ml-0.5 min-w-[160px] rounded-md border bg-popover p-1 shadow-md',
            'animate-in fade-in-0 zoom-in-95',
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

function MenuSeparator() {
  return <div className="-mx-1 my-1 h-px bg-border" />;
}

// ---------------------------------------------------------------------------
// Main context menu
// ---------------------------------------------------------------------------

export interface GraphContextMenuProps {
  position: ContextMenuPosition | null;
  target: ContextMenuTarget | null;
  onClose: () => void;
  /** Expand neighbors of a node in a given direction */
  onExpandNeighbors?: (nodeId: string, direction: 'outgoing' | 'incoming' | 'both') => void;
  /** Expand neighbors filtered by a specific edge type */
  onExpandByType?: (nodeId: string, edgeType: string) => void;
  /** Collapse a previously expanded node */
  onCollapseNode?: (nodeId: string) => void;
  /** Edit a node */
  onEditNode?: (nodeId: string) => void;
  /** Delete a node */
  onDeleteNode?: (nodeId: string) => void;
  /** Center the view on a node */
  onCenterOnNode?: (nodeId: string) => void;
  /** Edit an edge */
  onEditEdge?: (edgeId: string) => void;
  /** Delete an edge */
  onDeleteEdge?: (edgeId: string) => void;
  /** Create a new node (canvas action) */
  onCreateNode?: () => void;
  /** Reset view / fit to screen */
  onResetView?: () => void;
  /** Fit graph to screen */
  onFitToScreen?: () => void;
}

export function GraphContextMenu({
  position,
  target,
  onClose,
  onExpandNeighbors,
  onExpandByType,
  onCollapseNode,
  onEditNode,
  onDeleteNode,
  onCenterOnNode,
  onEditEdge,
  onDeleteEdge,
  onCreateNode,
  onResetView,
  onFitToScreen,
}: GraphContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const { t } = useTranslation('graph-explorer');

  // Close on click outside
  useEffect(() => {
    if (!position) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };

    // Delay attaching to prevent the right-click from immediately closing
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleKeyDown);
    }, 0);

    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [position, onClose]);

  // Adjust position to stay on-screen
  const adjustedPosition = React.useMemo(() => {
    if (!position) return null;
    const menuWidth = 220;
    const menuHeight = 300;
    const padding = 8;

    let { x, y } = position;
    if (typeof window !== 'undefined') {
      if (x + menuWidth + padding > window.innerWidth) {
        x = window.innerWidth - menuWidth - padding;
      }
      if (y + menuHeight + padding > window.innerHeight) {
        y = window.innerHeight - menuHeight - padding;
      }
    }
    return { x: Math.max(padding, x), y: Math.max(padding, y) };
  }, [position]);

  const handleAction = useCallback(
    (action: () => void) => {
      action();
      onClose();
    },
    [onClose],
  );

  if (!position || !target || !adjustedPosition) return null;

  return (
    <div
      ref={menuRef}
      className={cn(
        'fixed z-[100] min-w-[180px] rounded-md border bg-popover p-1 shadow-lg',
        'animate-in fade-in-0 zoom-in-95',
      )}
      style={{ left: adjustedPosition.x, top: adjustedPosition.y }}
      onContextMenu={(e) => e.preventDefault()}
    >
      {/* --------- Node context menu --------- */}
      {target.type === 'node' && target.id && (
        <>
          {/* Header */}
          <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground truncate">
            {target.label || target.id}
            {target.nodeType && (
              <span className="ml-1 text-muted-foreground/60">({target.nodeType})</span>
            )}
          </div>
          <MenuSeparator />

          {/* Expand / Collapse */}
          {!target.isExpanded ? (
            <>
              <MenuItem
                icon={<Expand className="h-4 w-4" />}
                label={t('contextMenu.expandAll')}
                onClick={() => handleAction(() => onExpandNeighbors?.(target.id!, 'both'))}
              />
              <SubMenu
                icon={<Expand className="h-4 w-4" />}
                label={t('contextMenu.expandByType')}
              >
                <MenuItem
                  icon={<ArrowUpRight className="h-4 w-4" />}
                  label={t('contextMenu.expandOutgoing')}
                  onClick={() => handleAction(() => onExpandNeighbors?.(target.id!, 'outgoing'))}
                />
                <MenuItem
                  icon={<ArrowDownLeft className="h-4 w-4" />}
                  label={t('contextMenu.expandIncoming')}
                  onClick={() => handleAction(() => onExpandNeighbors?.(target.id!, 'incoming'))}
                />
                {target.connectedEdgeTypes && target.connectedEdgeTypes.length > 0 && (
                  <>
                    <MenuSeparator />
                    {target.connectedEdgeTypes.map((edgeType) => (
                      <MenuItem
                        key={edgeType}
                        label={edgeType}
                        onClick={() => handleAction(() => onExpandByType?.(target.id!, edgeType))}
                      />
                    ))}
                  </>
                )}
              </SubMenu>
            </>
          ) : (
            <>
              <MenuItem
                icon={<Expand className="h-4 w-4" />}
                label={t('contextMenu.expandAll')}
                onClick={() => handleAction(() => onExpandNeighbors?.(target.id!, 'both'))}
              />
              <MenuItem
                icon={<Shrink className="h-4 w-4" />}
                label={t('contextMenu.collapse')}
                onClick={() => handleAction(() => onCollapseNode?.(target.id!))}
              />
            </>
          )}

          <MenuSeparator />

          {/* Actions */}
          <MenuItem
            icon={<Crosshair className="h-4 w-4" />}
            label={t('contextMenu.centerOnNode')}
            onClick={() => handleAction(() => onCenterOnNode?.(target.id!))}
          />
          <MenuItem
            icon={<Pencil className="h-4 w-4" />}
            label={t('contextMenu.editNode')}
            onClick={() => handleAction(() => onEditNode?.(target.id!))}
          />
          <MenuItem
            icon={<Copy className="h-4 w-4" />}
            label={t('contextMenu.copyNodeId')}
            onClick={() =>
              handleAction(() => {
                navigator.clipboard.writeText(target.id!);
              })
            }
          />

          <MenuSeparator />

          <MenuItem
            icon={<Trash2 className="h-4 w-4" />}
            label={t('contextMenu.deleteNode')}
            onClick={() => handleAction(() => onDeleteNode?.(target.id!))}
            variant="destructive"
          />
        </>
      )}

      {/* --------- Edge context menu --------- */}
      {target.type === 'edge' && target.id && (
        <>
          <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground truncate">
            {target.relationshipType || target.id}
          </div>
          <MenuSeparator />

          <MenuItem
            icon={<Pencil className="h-4 w-4" />}
            label={t('contextMenu.editEdge')}
            onClick={() => handleAction(() => onEditEdge?.(target.id!))}
          />
          <MenuItem
            icon={<Copy className="h-4 w-4" />}
            label={t('contextMenu.copyEdgeDetails')}
            onClick={() =>
              handleAction(() => {
                const text = `${target.relationshipType || ''} (${target.id})`;
                navigator.clipboard.writeText(text);
              })
            }
          />

          <MenuSeparator />

          <MenuItem
            icon={<Trash2 className="h-4 w-4" />}
            label={t('contextMenu.deleteEdge')}
            onClick={() => handleAction(() => onDeleteEdge?.(target.id!))}
            variant="destructive"
          />
        </>
      )}

      {/* --------- Canvas context menu --------- */}
      {target.type === 'canvas' && (
        <>
          <MenuItem
            icon={<Plus className="h-4 w-4" />}
            label={t('contextMenu.createNode')}
            onClick={() => handleAction(() => onCreateNode?.())}
          />

          <MenuSeparator />

          <MenuItem
            icon={<Maximize className="h-4 w-4" />}
            label={t('contextMenu.fitToScreen')}
            onClick={() => handleAction(() => onFitToScreen?.())}
          />
          <MenuItem
            icon={<Crosshair className="h-4 w-4" />}
            label={t('contextMenu.resetView')}
            onClick={() => handleAction(() => onResetView?.())}
          />
        </>
      )}
    </div>
  );
}

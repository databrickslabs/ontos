/**
 * Graph Context Menu
 * Custom positioned context menu for right-click actions on graph nodes/background.
 * Uses fixed positioning at mouse coordinates since canvas elements can't be
 * wrapped in Radix ContextMenuTrigger.
 */
import React, { useEffect, useRef } from 'react';
import { Pencil, Trash2, Link, Eye, Plus } from 'lucide-react';
import { Separator } from '@/components/ui/separator';
import type { OntologyConcept } from '@/types/ontology';

interface GraphContextMenuProps {
  /** Position to render at, or null to hide */
  position: { x: number; y: number } | null;
  /** Concept that was right-clicked, or null for background click */
  concept?: OntologyConcept | null;
  onClose: () => void;
  onViewDetails?: (concept: OntologyConcept) => void;
  onEdit?: (concept: OntologyConcept) => void;
  onDelete?: (concept: OntologyConcept) => void;
  onCreateLink?: (concept: OntologyConcept) => void;
  onCreateConcept?: () => void;
}

export const GraphContextMenu: React.FC<GraphContextMenuProps> = ({
  position,
  concept,
  onClose,
  onViewDetails,
  onEdit,
  onDelete,
  onCreateLink,
  onCreateConcept,
}) => {
  const menuRef = useRef<HTMLDivElement>(null);

  // Close on click-away or Escape
  useEffect(() => {
    if (!position) return;

    const handleClickAway = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };

    // Delay listener attach to avoid immediate close from the triggering right-click
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handleClickAway);
      document.addEventListener('keydown', handleEscape);
    }, 0);

    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handleClickAway);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [position, onClose]);

  // Adjust position to keep menu within viewport
  useEffect(() => {
    if (!position || !menuRef.current) return;
    const rect = menuRef.current.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    if (rect.right > vw) {
      menuRef.current.style.left = `${position.x - rect.width}px`;
    }
    if (rect.bottom > vh) {
      menuRef.current.style.top = `${position.y - rect.height}px`;
    }
  }, [position]);

  if (!position) return null;

  const menuItems: Array<{
    icon: React.ReactNode;
    label: string;
    onClick: () => void;
    destructive?: boolean;
  }> = [];

  if (concept) {
    // Node right-click menu
    if (onViewDetails) {
      menuItems.push({
        icon: <Eye className="h-4 w-4" />,
        label: 'View Details',
        onClick: () => { onViewDetails(concept); onClose(); },
      });
    }
    if (onEdit) {
      menuItems.push({
        icon: <Pencil className="h-4 w-4" />,
        label: 'Edit Concept',
        onClick: () => { onEdit(concept); onClose(); },
      });
    }
    if (onCreateLink) {
      menuItems.push({
        icon: <Link className="h-4 w-4" />,
        label: 'Create Link From...',
        onClick: () => { onCreateLink(concept); onClose(); },
      });
    }
    if (onDelete) {
      menuItems.push({
        icon: <Trash2 className="h-4 w-4" />,
        label: 'Delete Concept',
        onClick: () => { onDelete(concept); onClose(); },
        destructive: true,
      });
    }
  } else {
    // Background right-click menu
    if (onCreateConcept) {
      menuItems.push({
        icon: <Plus className="h-4 w-4" />,
        label: 'Create New Concept',
        onClick: () => { onCreateConcept(); onClose(); },
      });
    }
  }

  if (menuItems.length === 0) return null;

  return (
    <div
      ref={menuRef}
      className="fixed z-[200] min-w-[180px] rounded-md border bg-popover p-1 text-popover-foreground shadow-md animate-in fade-in-0 zoom-in-95"
      style={{ left: position.x, top: position.y }}
    >
      {concept && (
        <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground truncate max-w-[220px]">
          {concept.label || concept.iri.split(/[/#]/).pop()}
        </div>
      )}
      {concept && <Separator className="my-1" />}
      {menuItems.map((item, i) => (
        <React.Fragment key={item.label}>
          {item.destructive && i > 0 && <Separator className="my-1" />}
          <button
            className={`relative flex w-full cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none transition-colors hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground ${
              item.destructive ? 'text-destructive hover:text-destructive' : ''
            }`}
            onClick={item.onClick}
          >
            {item.icon}
            {item.label}
          </button>
        </React.Fragment>
      ))}
    </div>
  );
};

export default GraphContextMenu;

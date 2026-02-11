/**
 * Diagram Manager for Graph Explorer.
 *
 * Allows users to save, name, and restore curated subgraph snapshots.
 * Diagrams are persisted in localStorage, keyed by table name so each
 * dataset has its own diagram collection.
 */

import React, { useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Save, FolderOpen, Trash2, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { GraphData } from '@/types/graph-explorer';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SavedDiagram {
  id: string;
  name: string;
  /** ISO timestamp */
  savedAt: string;
  nodeCount: number;
  edgeCount: number;
  data: GraphData;
}

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

const STORAGE_PREFIX = 'graph-explorer-diagrams:';

export function getDiagrams(tableName: string): SavedDiagram[] {
  try {
    const raw = localStorage.getItem(`${STORAGE_PREFIX}${tableName}`);
    if (!raw) return [];
    return JSON.parse(raw) as SavedDiagram[];
  } catch {
    return [];
  }
}

export function saveDiagrams(tableName: string, diagrams: SavedDiagram[]): void {
  localStorage.setItem(`${STORAGE_PREFIX}${tableName}`, JSON.stringify(diagrams));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface DiagramManagerProps {
  tableName: string;
  currentData: GraphData;
  onRestoreDiagram: (data: GraphData) => void;
  disabled?: boolean;
  className?: string;
}

export function DiagramManager({
  tableName,
  currentData,
  onRestoreDiagram,
  disabled = false,
  className,
}: DiagramManagerProps) {
  const { t } = useTranslation('graph-explorer');

  const [diagrams, setDiagrams] = useState<SavedDiagram[]>(() => getDiagrams(tableName));
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [diagramName, setDiagramName] = useState('');

  // Reload diagrams when tableName changes
  React.useEffect(() => {
    setDiagrams(getDiagrams(tableName));
  }, [tableName]);

  const handleSave = useCallback(() => {
    const name = diagramName.trim() || `Diagram ${diagrams.length + 1}`;
    const newDiagram: SavedDiagram = {
      id: `diag-${Date.now()}`,
      name,
      savedAt: new Date().toISOString(),
      nodeCount: currentData.nodes.length,
      edgeCount: currentData.edges.length,
      data: currentData,
    };
    const updated = [newDiagram, ...diagrams];
    setDiagrams(updated);
    saveDiagrams(tableName, updated);
    setDiagramName('');
    setSaveDialogOpen(false);
  }, [diagramName, diagrams, currentData, tableName]);

  const handleDelete = useCallback(
    (diagramId: string) => {
      const updated = diagrams.filter((d) => d.id !== diagramId);
      setDiagrams(updated);
      saveDiagrams(tableName, updated);
    },
    [diagrams, tableName],
  );

  const handleRestore = useCallback(
    (diagram: SavedDiagram) => {
      onRestoreDiagram(diagram.data);
    },
    [onRestoreDiagram],
  );

  const formatDate = (iso: string) => {
    try {
      return new Date(iso).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return iso;
    }
  };

  return (
    <Card className={cn('', className)}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">{t('diagrams.title')}</CardTitle>
          <Dialog open={saveDialogOpen} onOpenChange={setSaveDialogOpen}>
            <DialogTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                disabled={disabled || currentData.nodes.length === 0}
              >
                <Plus className="h-3 w-3 mr-1" />
                {t('diagrams.save')}
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-[400px]">
              <DialogHeader>
                <DialogTitle>{t('diagrams.saveTitle')}</DialogTitle>
                <DialogDescription>
                  {t('diagrams.saveDescription', {
                    nodeCount: currentData.nodes.length,
                    edgeCount: currentData.edges.length,
                  })}
                </DialogDescription>
              </DialogHeader>
              <Input
                placeholder={t('diagrams.namePlaceholder')}
                value={diagramName}
                onChange={(e) => setDiagramName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSave();
                }}
                autoFocus
              />
              <DialogFooter>
                <Button variant="outline" onClick={() => setSaveDialogOpen(false)}>
                  {t('common:actions.cancel', 'Cancel')}
                </Button>
                <Button onClick={handleSave}>
                  <Save className="h-3.5 w-3.5 mr-1" />
                  {t('diagrams.save')}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>

      <CardContent className="space-y-1.5 max-h-[200px] overflow-y-auto">
        {diagrams.length === 0 ? (
          <p className="text-xs text-muted-foreground py-2">{t('diagrams.empty')}</p>
        ) : (
          diagrams.map((d) => (
            <div
              key={d.id}
              className="flex items-center gap-2 rounded-md border px-2 py-1.5 text-xs group hover:bg-muted/50 transition-colors"
            >
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{d.name}</div>
                <div className="text-muted-foreground">
                  {d.nodeCount}n / {d.edgeCount}e &middot; {formatDate(d.savedAt)}
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                onClick={() => handleRestore(d)}
                title={t('diagrams.restore')}
              >
                <FolderOpen className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity text-destructive"
                onClick={() => handleDelete(d.id)}
                title={t('diagrams.delete')}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

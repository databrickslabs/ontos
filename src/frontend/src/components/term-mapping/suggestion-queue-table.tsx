import { useMemo, useState } from 'react';
import { ColumnDef, RowSelectionState } from '@tanstack/react-table';
import { CheckCircle2, ExternalLink, Loader2, Pencil, XCircle } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { DataTable } from '@/components/ui/data-table';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';
import { useApi } from '@/hooks/use-api';

import type {
  Suggestion,
  SuggestionDecision,
  SuggestionDecisionResult,
} from '@/types/term-mapping';
import { bucketConfidence } from '@/types/term-mapping';

interface SuggestionQueueTableProps {
  runId: string;
  suggestions: Suggestion[];
  loading: boolean;
  /** Called after a decide call so the parent can re-fetch. */
  onChanged: () => void;
  /** True when the run is already applied / undone (readonly). */
  readonly?: boolean;
}

export default function SuggestionQueueTable({
  runId,
  suggestions,
  loading,
  onChanged,
  readonly = false,
}: SuggestionQueueTableProps) {
  const { toast } = useToast();
  const { post } = useApi();
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [submitting, setSubmitting] = useState(false);
  const [editing, setEditing] = useState<Suggestion | null>(null);
  const [customIri, setCustomIri] = useState<string>('');

  const selectedIds = useMemo(
    () => Object.keys(rowSelection).filter((id) => rowSelection[id]),
    [rowSelection],
  );

  const sendDecisions = async (
    decisions: SuggestionDecision[],
    successLabel: string,
  ) => {
    if (decisions.length === 0) return;
    setSubmitting(true);
    try {
      const res = await post<SuggestionDecisionResult>(
        `/api/term-mappings/runs/${runId}/decisions`,
        { decisions },
      );
      if (res.error) throw new Error(res.error);
      const data = res.data;
      toast({
        title: successLabel,
        description: `${data.accepted} accepted, ${data.rejected} rejected, ${data.skipped} skipped${
          data.errors && data.errors.length > 0 ? `, ${data.errors.length} errors` : ''
        }.`,
      });
      setRowSelection({});
      onChanged();
    } catch (e) {
      toast({
        title: 'Decision failed',
        description: e instanceof Error ? e.message : 'Unknown error',
        variant: 'destructive',
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleAcceptSelected = () =>
    sendDecisions(
      selectedIds.map((id) => ({ id, decision: 'accept' as const })),
      'Suggestions accepted',
    );

  const handleRejectSelected = () =>
    sendDecisions(
      selectedIds.map((id) => ({ id, decision: 'reject' as const })),
      'Suggestions rejected',
    );

  const handleSubmitCustomIri = async () => {
    if (!editing) return;
    const iri = customIri.trim();
    if (!iri) {
      toast({
        title: 'Custom IRI required',
        description: 'Type the concept IRI to assign, or cancel.',
        variant: 'destructive',
      });
      return;
    }
    await sendDecisions(
      [{ id: editing.id, decision: 'accept', custom_iri: iri }],
      'Custom IRI accepted',
    );
    setEditing(null);
    setCustomIri('');
  };

  const columns = useMemo<ColumnDef<Suggestion>[]>(() => {
    const cols: ColumnDef<Suggestion>[] = [
      {
        accessorKey: 'source_entity_type',
        header: 'Type',
        cell: ({ row }) => (
          <Badge variant="outline" className="text-xs">
            {row.original.source_entity_type}
          </Badge>
        ),
      },
      {
        accessorKey: 'source_label',
        header: 'Source',
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="text-sm font-medium">
              {row.original.source_label || row.original.source_entity_id}
            </span>
            <span className="text-xs text-muted-foreground font-mono truncate max-w-xs">
              {row.original.source_entity_id}
            </span>
          </div>
        ),
      },
      {
        accessorKey: 'target_concept_label',
        header: 'Suggested concept',
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="text-sm">
              {row.original.target_concept_label || '(unlabelled)'}
            </span>
            <a
              href={row.original.target_concept_iri}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="text-xs text-muted-foreground font-mono truncate max-w-md hover:underline inline-flex items-center gap-1"
              title={row.original.target_concept_iri}
            >
              {row.original.target_concept_iri}
              <ExternalLink className="h-3 w-3 inline opacity-60" />
            </a>
          </div>
        ),
      },
      {
        accessorKey: 'confidence',
        header: 'Confidence',
        cell: ({ row }) => {
          const c = row.original.confidence;
          const bucket = bucketConfidence(c);
          const variant: 'default' | 'secondary' | 'outline' =
            bucket === 'high' ? 'default' : bucket === 'medium' ? 'secondary' : 'outline';
          return (
            <div className="flex items-center gap-2">
              <Badge variant={variant} className="text-xs">
                {(c * 100).toFixed(0)}%
              </Badge>
              {row.original.auto_apply && (
                <Badge variant="default" className="text-[10px] bg-emerald-600 hover:bg-emerald-600">
                  auto
                </Badge>
              )}
            </div>
          );
        },
      },
      {
        accessorKey: 'reason',
        header: 'Why',
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground max-w-md truncate block" title={row.original.reason}>
            {row.original.reason}
          </span>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => {
          const s = row.original.status;
          const variant =
            s === 'applied'
              ? 'default'
              : s === 'rejected'
                ? 'destructive'
                : s === 'accepted'
                  ? 'secondary'
                  : 'outline';
          return (
            <Badge variant={variant} className="text-xs">
              {s}
            </Badge>
          );
        },
      },
    ];

    if (!readonly) {
      cols.push({
        id: 'rowActions',
        enableHiding: false,
        cell: ({ row }) => {
          const s = row.original;
          if (s.status !== 'pending') return null;
          return (
            <div className="flex justify-end gap-1">
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                title="Accept"
                onClick={(e) => {
                  e.stopPropagation();
                  sendDecisions([{ id: s.id, decision: 'accept' }], 'Suggestion accepted');
                }}
              >
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                title="Reject"
                onClick={(e) => {
                  e.stopPropagation();
                  sendDecisions([{ id: s.id, decision: 'reject' }], 'Suggestion rejected');
                }}
              >
                <XCircle className="h-4 w-4 text-destructive" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                title="Override with custom IRI"
                onClick={(e) => {
                  e.stopPropagation();
                  setEditing(s);
                  setCustomIri(s.target_concept_iri);
                }}
              >
                <Pencil className="h-4 w-4" />
              </Button>
            </div>
          );
        },
      });
    }
    return cols;
  }, [readonly, sendDecisions]);

  return (
    <div>
      {loading ? (
        <div className="flex justify-center items-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : suggestions.length === 0 ? (
        <div className="text-sm text-muted-foreground py-8 text-center border rounded-md">
          No suggestions in this view.
        </div>
      ) : (
        <DataTable
          columns={columns}
          data={suggestions}
          rowSelection={rowSelection}
          onRowSelectionChange={setRowSelection}
          bulkActions={
            readonly
              ? undefined
              : () => (
                  <div className="flex gap-2">
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={selectedIds.length === 0 || submitting}
                      onClick={handleRejectSelected}
                    >
                      <XCircle className="h-4 w-4 mr-2" />
                      Reject {selectedIds.length}
                    </Button>
                    <Button
                      size="sm"
                      disabled={selectedIds.length === 0 || submitting}
                      onClick={handleAcceptSelected}
                    >
                      <CheckCircle2 className="h-4 w-4 mr-2" />
                      Accept {selectedIds.length}
                    </Button>
                  </div>
                )
          }
        />
      )}

      <Dialog
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) {
            setEditing(null);
            setCustomIri('');
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Override suggested concept</DialogTitle>
            <DialogDescription>
              Replace the suggested IRI with one you pick. The override will still go through
              the customer-ontology validation on apply.
            </DialogDescription>
          </DialogHeader>
          {editing && (
            <div className="space-y-3">
              <div className="text-sm">
                <div className="text-muted-foreground">Source</div>
                <div className="font-medium">
                  {editing.source_label || editing.source_entity_id}
                </div>
              </div>
              <div>
                <Label htmlFor="tm-custom-iri" className="text-sm">
                  Concept IRI
                </Label>
                <Input
                  id="tm-custom-iri"
                  value={customIri}
                  onChange={(e) => setCustomIri(e.target.value)}
                  placeholder="https://example.com/ontology#Customer"
                  className="font-mono text-xs"
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)} disabled={submitting}>
              Cancel
            </Button>
            <Button onClick={handleSubmitCustomIri} disabled={submitting}>
              {submitting ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
              Accept with custom IRI
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

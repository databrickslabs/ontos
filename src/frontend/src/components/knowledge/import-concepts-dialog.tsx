import React, { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { cn } from '@/lib/utils';
import type { KnowledgeCollection } from '@/types/ontology';
import { Loader2, Upload, FileUp, X, Info } from 'lucide-react';

const ACCEPTED_EXTENSIONS = '.ttl,.rdf,.xml,.owl,.n3,.nt,.jsonld,.json';

// Import supports two placement strategies. Conflict/dedup across schemes is
// intentionally NOT handled here — it is reconciled later in the Review Board.
type SchemeStrategy = 'merge' | 'perfile';

interface ImportConceptsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  collections: KnowledgeCollection[];
  onImported: () => void;
}

// Per-file structural summary once imported. `triples_imported` is what the
// backend actually returns today; the richer breakdown (concepts by type,
// top-level vs child, dangling refs) is a TODO (see CB-10 note below).
interface FileImportOutcome {
  name: string;
  ok: boolean;
  triplesImported?: number;
  error?: string;
}

export const ImportConceptsDialog: React.FC<ImportConceptsDialogProps> = ({
  open,
  onOpenChange,
  collections,
  onImported,
}) => {
  const { t } = useTranslation(['semantic-models', 'common']);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [schemeStrategy, setSchemeStrategy] = useState<SchemeStrategy>('merge');
  // Merge mode: single target collection for all files.
  const [selectedCollectionIri, setSelectedCollectionIri] = useState<string>('');
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outcomes, setOutcomes] = useState<FileImportOutcome[] | null>(null);

  const editableCollections = collections.filter((c) => c.is_editable);

  const flattenCollections = (
    colls: KnowledgeCollection[],
    level = 0
  ): Array<{ iri: string; label: string; level: number }> => {
    let items: Array<{ iri: string; label: string; level: number }> = [];
    for (const c of colls) {
      if (c.is_editable) {
        items.push({ iri: c.iri, label: c.label, level });
      }
      if (c.child_collections?.length) {
        items = items.concat(flattenCollections(c.child_collections, level + 1));
      }
    }
    return items;
  };

  const flatOptions = flattenCollections(collections);

  const resetState = () => {
    setSelectedFiles([]);
    setSchemeStrategy('merge');
    setSelectedCollectionIri('');
    setError(null);
    setOutcomes(null);
    setIsUploading(false);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) resetState();
    onOpenChange(nextOpen);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const incoming = Array.from(e.target.files ?? []);
    if (incoming.length) {
      setSelectedFiles((prev) => {
        // De-dupe by name so re-adding the same file is a no-op.
        const seen = new Set(prev.map((f) => f.name));
        return [...prev, ...incoming.filter((f) => !seen.has(f.name))];
      });
    }
    setError(null);
    setOutcomes(null);
    // Clear the input so selecting the same file again re-fires change.
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleRemoveFile = (name: string) => {
    setSelectedFiles((prev) => prev.filter((f) => f.name !== name));
  };

  const importOneFile = async (file: File, targetIri: string): Promise<number> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(
      `/api/knowledge/collections/${encodeURIComponent(targetIri)}/import`,
      { method: 'POST', body: formData }
    );
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Import failed (${response.status})`);
    }
    const data = await response.json();
    // TODO(cb-v2): needs structural summary from import endpoint.
    // The endpoint returns { success, triples_imported } only — no per-type
    // concept counts, top-level vs child breakdown, or dangling-ref detection.
    return data.triples_imported ?? 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedFiles.length === 0) return;
    // Merge strategy needs a target collection. Per-file strategy relies on the
    // backend deriving one scheme per file — but the current endpoint imports
    // into an EXISTING collection only (no create-per-file), so we still require
    // a target and TODO the true per-file behavior.
    if (!selectedCollectionIri) return;

    setIsUploading(true);
    setError(null);
    setOutcomes(null);

    // CB-6 (atomic save): the backend has no batch/transaction endpoint, so we
    // cannot make a multi-file import truly atomic here. We validate/parse each
    // file server-side before it commits (the endpoint 400s on invalid RDF), and
    // we surface per-file results so a partial failure is visible for manual
    // rollback in the Review Board.
    // TODO(cb-v2): true atomic multi-file import (validate-all-then-commit +
    // server-side rollback) requires a batch import endpoint.
    const results: FileImportOutcome[] = [];
    for (const file of selectedFiles) {
      try {
        const triples = await importOneFile(file, selectedCollectionIri);
        results.push({ name: file.name, ok: true, triplesImported: triples });
      } catch (err: any) {
        results.push({ name: file.name, ok: false, error: err.message });
      }
    }

    setOutcomes(results);
    setIsUploading(false);
    if (results.some((r) => r.ok)) {
      onImported();
    }
    if (results.every((r) => !r.ok)) {
      setError(
        t(
          'semantic-models:import.allFailed',
          'No files could be imported. See per-file errors below.'
        )
      );
    }
  };

  const canSubmit =
    selectedFiles.length > 0 && !!selectedCollectionIri && !isUploading;
  const totalTriples = (outcomes ?? [])
    .filter((r) => r.ok)
    .reduce((sum, r) => sum + (r.triplesImported ?? 0), 0);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{t('semantic-models:import.title', 'Import files')}</DialogTitle>
          <DialogDescription>
            {t(
              'semantic-models:import.descriptionMulti',
              'Drop one or more ontology files, then choose how they land. The file is just a carrier.'
            )}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit}>
          <div className="grid gap-4 py-4">
            {/* File picker (multiple) */}
            <div className="grid gap-2">
              <Label>{t('semantic-models:import.sourceFiles', 'Source files')}</Label>
              <Button
                type="button"
                variant="outline"
                className="w-full justify-start text-muted-foreground"
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload className="h-4 w-4 mr-2" />
                {selectedFiles.length > 0
                  ? t('semantic-models:import.addMoreFiles', 'Add more files…')
                  : t('semantic-models:import.chooseFiles', 'Choose files…')}
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={ACCEPTED_EXTENSIONS}
                className="hidden"
                onChange={handleFileSelect}
              />
              {selectedFiles.length > 0 && (
                <div className="flex flex-col gap-1.5 mt-1">
                  {selectedFiles.map((file) => (
                    <div
                      key={file.name}
                      className="flex items-center gap-2 rounded-md border px-3 py-2"
                    >
                      <FileUp className="h-4 w-4 text-muted-foreground shrink-0" />
                      <span className="text-sm truncate flex-1 font-mono">{file.name}</span>
                      <span className="text-xs text-muted-foreground shrink-0">
                        {(file.size / 1024).toFixed(1)} KB
                      </span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 shrink-0"
                        onClick={() => handleRemoveFile(file.name)}
                        aria-label={t('common:actions.remove', 'Remove')}
                      >
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              <p className="text-xs text-muted-foreground">
                {t(
                  'semantic-models:import.supportedFormats',
                  'Supported: Turtle (.ttl), RDF/XML (.rdf, .xml), OWL (.owl), N-Triples (.nt), N3 (.n3), JSON-LD (.jsonld, .json)'
                )}
              </p>
            </div>

            {/* Scheme strategy */}
            <div className="grid gap-2">
              <Label>{t('semantic-models:import.howLand', 'How should these land?')}</Label>
              <RadioGroup
                value={schemeStrategy}
                onValueChange={(v) => setSchemeStrategy(v as SchemeStrategy)}
                className="grid grid-cols-2 gap-2"
              >
                <label
                  htmlFor="scheme-merge"
                  className={cn(
                    'flex items-start gap-2 rounded-md border p-3 cursor-pointer',
                    schemeStrategy === 'merge' && 'border-primary ring-1 ring-primary'
                  )}
                >
                  <RadioGroupItem value="merge" id="scheme-merge" className="mt-0.5" />
                  <span>
                    <span className="block text-sm font-medium">
                      {t('semantic-models:import.oneScheme', 'One scheme')}
                    </span>
                    <span className="block text-xs text-muted-foreground mt-0.5">
                      {t(
                        'semantic-models:import.oneSchemeDesc',
                        'Merge every file into a single concept scheme.'
                      )}
                    </span>
                  </span>
                </label>
                <label
                  htmlFor="scheme-perfile"
                  className={cn(
                    'flex items-start gap-2 rounded-md border p-3 cursor-pointer',
                    schemeStrategy === 'perfile' && 'border-primary ring-1 ring-primary'
                  )}
                >
                  <RadioGroupItem value="perfile" id="scheme-perfile" className="mt-0.5" />
                  <span>
                    <span className="block text-sm font-medium">
                      {t('semantic-models:import.oneSchemePerFile', 'One scheme per file')}
                    </span>
                    <span className="block text-xs text-muted-foreground mt-0.5">
                      {t(
                        'semantic-models:import.oneSchemePerFileDesc',
                        'Each file becomes its own concept scheme.'
                      )}
                    </span>
                  </span>
                </label>
              </RadioGroup>
              {schemeStrategy === 'perfile' && (
                <p className="text-xs text-muted-foreground">
                  {/* TODO(cb-v2): the import endpoint imports into an existing
                      collection only; it does not create one scheme per file.
                      Until a per-file/create endpoint exists, all files land in
                      the target collection selected below. */}
                  {t(
                    'semantic-models:import.perFileTodo',
                    'One-scheme-per-file needs a backend that creates a scheme per file; for now all files land in the collection below.'
                  )}
                </p>
              )}
            </div>

            {/* Target collection (merge strategy — and current fallback for per-file) */}
            <div className="grid gap-2">
              <Label>
                {t('semantic-models:import.targetCollection', 'Target concept scheme')}
              </Label>
              <Select value={selectedCollectionIri} onValueChange={setSelectedCollectionIri}>
                <SelectTrigger>
                  <SelectValue
                    placeholder={t('semantic-models:import.selectCollection', 'Select a collection…')}
                  />
                </SelectTrigger>
                <SelectContent>
                  {flatOptions.map((opt) => (
                    <SelectItem key={opt.iri} value={opt.iri}>
                      {'—'.repeat(opt.level)}
                      {opt.level > 0 ? ' ' : ''}
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {editableCollections.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  {t(
                    'semantic-models:import.noEditableCollections',
                    'No editable collections available. Create one first.'
                  )}
                </p>
              )}
            </div>

            {/* Conflicts-reconciled-later note */}
            <div className="flex items-start gap-2 rounded-md border bg-muted/50 p-3 text-xs text-muted-foreground leading-relaxed">
              <Info className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
              <span>
                {t(
                  'semantic-models:import.reconcileNote',
                  'Overlapping or duplicate terms across schemes are reconciled later in the Review Board. Import just brings the graph in.'
                )}
              </span>
            </div>

            {/* Error */}
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {/* Per-file outcomes + structural summary (CB-10, partial) */}
            {outcomes && (
              <div className="grid gap-2">
                {outcomes.some((r) => r.ok) && (
                  <Alert>
                    <AlertDescription>
                      {t('semantic-models:import.summary', {
                        files: outcomes.filter((r) => r.ok).length,
                        count: totalTriples,
                        defaultValue:
                          'Imported {{files}} file(s), {{count}} triples total.',
                      })}
                      {/* TODO(cb-v2): needs structural summary from import
                          endpoint — # concepts by type, top-level vs child,
                          dangling refs. Endpoint returns triples_imported only. */}
                    </AlertDescription>
                  </Alert>
                )}
                <div className="flex flex-col gap-1">
                  {outcomes.map((r) => (
                    <div
                      key={r.name}
                      className="flex items-center gap-2 text-xs rounded-md border px-3 py-1.5"
                    >
                      <span className="font-mono truncate flex-1">{r.name}</span>
                      {r.ok ? (
                        <span className="text-muted-foreground shrink-0">
                          {t('semantic-models:import.fileOk', {
                            count: r.triplesImported ?? 0,
                            defaultValue: '{{count}} triples',
                          })}
                        </span>
                      ) : (
                        <span className="text-destructive shrink-0 truncate max-w-[220px]">
                          {r.error}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={isUploading}
            >
              {outcomes
                ? t('common:actions.close', 'Close')
                : t('common:actions.cancel', 'Cancel')}
            </Button>
            {!outcomes && (
              <Button type="submit" disabled={!canSubmit}>
                {isUploading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                <Upload className="h-4 w-4 mr-2" />
                {t('semantic-models:import.submitMulti', {
                  count: selectedFiles.length,
                  defaultValue: 'Import {{count}} file(s)',
                })}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default ImportConceptsDialog;

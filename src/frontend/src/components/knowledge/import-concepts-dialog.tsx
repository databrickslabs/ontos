import React, { useState, useRef, useEffect } from 'react';
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
import { Input } from '@/components/ui/input';
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
// NEW: `status` tracks 'applied' | 'held' for governed uploads; review_request_id if present.
interface FileImportOutcome {
  name: string;
  ok: boolean;
  triplesImported?: number;
  status?: 'applied' | 'held';
  review_request_id?: string;
  error?: string;
}

// A diff preview returned when re-uploading into a scheme that already has
// content (P0-4 + P1-0). The steward reviews it and applies via confirm.
interface UploadPreviewConcept {
  iri: string;
  label?: string | null;
  reference_count?: number | null;
}
interface UploadPreview {
  preview_token: string;
  context_name: string;
  summary: { unchanged: number; modified: number; new: number; removed: number };
  modified: UploadPreviewConcept[];
  new: UploadPreviewConcept[];
  removed: UploadPreviewConcept[];
  fileName: string;
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
  // "Create new scheme" inline path: when the target selector picks this
  // sentinel, we show a name field and create the scheme before importing.
  const [newSchemeName, setNewSchemeName] = useState<string>('');
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outcomes, setOutcomes] = useState<FileImportOutcome[] | null>(null);
  // STAGED diff previews for a re-upload, computed when files are selected
  // against a scheme that already has content — shown BEFORE the Import button
  // so the user sees the diff and decides whether to import. Applied (confirmed)
  // only when Import is clicked. Empty/new schemes have nothing to diff.
  const [previews, setPreviews] = useState<UploadPreview[]>([]);
  const [previewing, setPreviewing] = useState(false);
  // Conflict resolution UI state
  interface ConflictItem {
    iri: string;
    existing_label: string;
    existing_context: string;
  }
  const [conflicts, setConflicts] = useState<ConflictItem[]>([]);
  const [conflictMode, setConflictMode] = useState<'skip' | 'update'>('update');

  const editableCollections = collections.filter((c) => c.is_editable);

  // Find a collection anywhere in the (possibly nested) tree by IRI, so we can
  // read its concept_count and decide whether a diff preview is meaningful.
  const findCollection = (
    colls: KnowledgeCollection[],
    iri: string,
  ): KnowledgeCollection | undefined => {
    for (const c of colls) {
      if (c.iri === iri) return c;
      const nested = c.child_collections?.length
        ? findCollection(c.child_collections, iri)
        : undefined;
      if (nested) return nested;
    }
    return undefined;
  };

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

  // Sentinel value for the "create a new scheme" option in the target selector.
  const CREATE_NEW = '__create_new_scheme__';
  const creatingNew = selectedCollectionIri === CREATE_NEW;

  // A re-upload only produces a meaningful diff when the target scheme already
  // has concepts. Creating a new scheme (or an empty one) has nothing to diff.
  const targetCollection = creatingNew
    ? undefined
    : findCollection(collections, selectedCollectionIri);
  const targetHasContent = (targetCollection?.concept_count ?? 0) > 0;

  // Preview-on-select: whenever files + a non-empty target are chosen, ask the
  // backend for the diff WITHOUT applying it, so the user sees "modifies N /
  // adds M / removes K" and decides before clicking Import. Runs against the
  // /import route, which returns {mode:'preview', ...} for non-empty schemes.
  useEffect(() => {
    if (!open) return;
    // Nothing to check against a target: no files, no chosen target,
    // creating-new (scheme not yet created — conflicts surface on submit), or
    // per-file (each file makes its own fresh scheme — no target to diff/conflict).
    if (
      selectedFiles.length === 0 || !selectedCollectionIri || creatingNew ||
      schemeStrategy === 'perfile'
    ) {
      setPreviews([]);
      setConflicts([]);
      return;
    }
    let cancelled = false;
    setPreviewing(true);
    setError(null);
    (async () => {
      const staged: UploadPreview[] = [];
      const foundConflicts: ConflictItem[] = [];
      for (const file of selectedFiles) {
        // Cross-scheme IRI conflicts (block/skip/update) — check for ANY target,
        // empty or not, since the collision is against OTHER schemes.
        const c = await detectConflicts(file, selectedCollectionIri);
        for (const item of c) {
          if (!foundConflicts.some((f) => f.iri === item.iri)) foundConflicts.push(item);
        }
        // Same-scheme re-upload diff preview (only meaningful for a non-empty target).
        if (targetHasContent) {
          try {
            const data = await importOneFile(file, selectedCollectionIri);
            if (data?.mode === 'preview') staged.push({ ...data, fileName: file.name });
          } catch {
            // A parse/preview error surfaces on submit; don't block the panel here.
          }
        }
      }
      if (!cancelled) {
        setPreviews(staged);
        setConflicts(foundConflicts);
        setPreviewing(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, selectedFiles, selectedCollectionIri, creatingNew, targetHasContent, schemeStrategy]);

  const resetState = () => {
    setSelectedFiles([]);
    setSchemeStrategy('merge');
    setSelectedCollectionIri('');
    setNewSchemeName('');
    setError(null);
    setOutcomes(null);
    setPreviews([]);
    setIsUploading(false);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  // Create a new (ontology-type) scheme and return its IRI. Used by the inline
  // "create new scheme" path so a user can import into a fresh scheme without
  // leaving the dialog. Ontology type matches imported RDF (classes/properties).
  const createScheme = async (label: string): Promise<string> => {
    const res = await fetch('/api/knowledge/collections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        label,
        collection_type: 'ontology',
        scope_level: 'enterprise',
        description: `Imported scheme: ${label}`,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err?.detail || 'Failed to create the new scheme');
    }
    const created = await res.json();
    return created.iri as string;
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

  // Returns the raw response. First import into an empty scheme →
  // {mode:'imported', triples_imported}. Re-upload into a scheme with content →
  // {mode:'preview', preview_token, summary, ...} (nothing applied yet).
  const importOneFile = async (file: File, targetIri: string, conflictModeParam?: 'skip' | 'update' | 'block'): Promise<any> => {
    const formData = new FormData();
    formData.append('file', file);
    const params = new URLSearchParams();
    if (conflictModeParam) {
      params.append('conflict_mode', conflictModeParam);
    }
    const url = `/api/knowledge/collections/${encodeURIComponent(targetIri)}/import${params.size > 0 ? '?' + params : ''}`;
    const response = await fetch(url, { method: 'POST', body: formData });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Import failed (${response.status})`);
    }
    return response.json();
  };

  // Pre-check a file for cross-scheme IRI conflicts (subjects that already live
  // in ANOTHER scheme). The /import route RAISES on such conflicts in block mode
  // (so they never come back in the response body); this dedicated endpoint
  // returns them so we can surface the block/skip/update choice up front rather
  // than dead-ending on "No files could be imported". Returns [] on any error
  // (parse issues surface on the real import).
  const detectConflicts = async (file: File, targetIri: string): Promise<ConflictItem[]> => {
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(
        `/api/knowledge/collections/${encodeURIComponent(targetIri)}/import/conflicts`,
        { method: 'POST', body: formData },
      );
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data?.conflicts) ? data.conflicts : [];
    } catch {
      return [];
    }
  };

  // Apply a staged preview by its token (the server holds the parsed content;
  // confirm applies it). Returns the response payload which may include status ('applied' | 'held')
  // and review_request_id if governed. Used internally by the single Import action.
  const confirmPreviewToken = async (token: string, conflictModeParam?: 'skip' | 'update'): Promise<any> => {
    const params = new URLSearchParams();
    if (conflictModeParam) {
      params.append('conflict_mode', conflictModeParam);
    }
    const url = `/api/semantic-models/uploads/preview/${encodeURIComponent(token)}/confirm${params.size > 0 ? '?' + params : ''}`;
    const res = await fetch(url, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Import failed (${res.status})`);
    }
    return res.json();
  };

  // Derive a scheme label from a file name: drop the extension, turn
  // separators into spaces (e.g. "sales_glossary.ttl" -> "sales glossary").
  const schemeLabelFromFile = (fileName: string): string =>
    fileName.replace(/\.[^./]+$/, '').replace(/[-_]+/g, ' ').trim() || fileName;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedFiles.length === 0) return;
    // Per-file needs no pre-selected target — each file makes its own scheme.
    if (schemeStrategy !== 'perfile' && !selectedCollectionIri) return;
    if (creatingNew && !newSchemeName.trim()) return;

    // If conflicts are shown, require a resolution choice before proceeding.
    if (conflicts.length > 0 && !conflictMode) {
      setError(t('semantic-models:import.conflict.mustChoose', 'Select how to handle conflicts.'));
      return;
    }

    setIsUploading(true);
    setError(null);
    setOutcomes(null);

    // PER-FILE: each file becomes its own new scheme (named from the file), then
    // imports into it. Composed client-side from create-scheme + import — no
    // dedicated backend endpoint needed.
    if (schemeStrategy === 'perfile') {
      const results: FileImportOutcome[] = [];
      for (const file of selectedFiles) {
        try {
          const label = schemeLabelFromFile(file.name);
          const iri = await createScheme(label);
          const data = await importOneFile(file, iri, 'skip');
          results.push({
            name: file.name,
            ok: true,
            triplesImported: data?.triples_imported ?? 0,
            status: data?.status || 'applied',
          });
        } catch (err: any) {
          results.push({ name: file.name, ok: false, error: err.message });
        }
      }
      setOutcomes(results);
      setIsUploading(false);
      if (results.some((r) => r.ok)) onImported();
      if (results.every((r) => !r.ok)) {
        setError(t('semantic-models:import.allFailed',
          'No files could be imported. See per-file errors below.'));
      }
      return;
    }

    // Re-upload into a scheme with content: the diff is ALREADY staged and shown
    // (previews). Import just confirms those tokens — the user reviewed the diff
    // before clicking, so there is no second step.
    if (previews.length > 0) {
      const results: FileImportOutcome[] = [];
      for (const pv of previews) {
        try {
          // Thread the conflict mode into confirm if conflicts exist
          const confirmResponse = await confirmPreviewToken(
            pv.preview_token,
            conflicts.length > 0 ? conflictMode : undefined
          );
          results.push({
            name: pv.fileName,
            ok: true,
            status: confirmResponse?.status || 'applied',
            review_request_id: confirmResponse?.review_request_id,
          });
        } catch (err: any) {
          results.push({ name: pv.fileName, ok: false, error: err.message });
        }
      }
      setOutcomes(results);
      setIsUploading(false);
      if (results.some((r) => r.ok)) onImported();
      if (results.every((r) => !r.ok)) {
        setError(t('semantic-models:import.allFailed',
          'No files could be imported. See per-file errors below.'));
      }
      return;
    }

    // Empty / new scheme: nothing to diff — plain import (concepts stamped Draft).
    let targetIri = selectedCollectionIri;
    if (creatingNew) {
      try {
        targetIri = await createScheme(newSchemeName.trim());
      } catch (err: any) {
        setError(err.message || 'Failed to create the new scheme');
        setIsUploading(false);
        return;
      }
    }

    const results: FileImportOutcome[] = [];
    for (const file of selectedFiles) {
      try {
        // Thread conflict mode if conflicts were detected
        const data = await importOneFile(
          file,
          targetIri,
          conflicts.length > 0 ? conflictMode : 'block'
        );
        // If import returns conflicts, show resolution UI and halt.
        if (data?.conflicts && data.conflicts.length > 0) {
          setConflicts(data.conflicts);
          setIsUploading(false);
          setError(null);
          return;
        }
        // A brand-new/empty scheme should return {mode:'imported'}. If the target
        // turned out non-empty and returned a preview, confirm it (edge case).
        if (data?.mode === 'preview') {
          const confirmResponse = await confirmPreviewToken(data.preview_token, conflictMode);
          results.push({
            name: file.name,
            ok: true,
            status: confirmResponse?.status || 'applied',
            review_request_id: confirmResponse?.review_request_id,
          });
        } else {
          results.push({
            name: file.name,
            ok: true,
            triplesImported: data.triples_imported ?? 0,
            status: data?.status || 'applied',
          });
        }
      } catch (err: any) {
        // A block-mode cross-scheme conflict raises here (the /import route does
        // not return the conflicts in its body). If we haven't already surfaced
        // the resolution choice, pre-check and show it instead of dead-ending.
        const isConflict = /already exist in another scheme|Import blocked/i.test(err?.message || '');
        if (isConflict && conflicts.length === 0) {
          const detected = await detectConflicts(file, targetIri);
          if (detected.length > 0) {
            setConflicts(detected);
            setIsUploading(false);
            setError(null);
            return;
          }
        }
        results.push({ name: file.name, ok: false, error: err.message });
      }
    }

    setOutcomes(results);
    setIsUploading(false);
    if (results.some((r) => r.ok)) onImported();
    if (results.every((r) => !r.ok)) {
      setError(t('semantic-models:import.allFailed',
        'No files could be imported. See per-file errors below.'));
    }
  };

  const canSubmit =
    selectedFiles.length > 0 &&
    // Per-file derives a scheme from each file, so no target selection needed.
    (schemeStrategy === 'perfile' || !!selectedCollectionIri) &&
    (!creatingNew || !!newSchemeName.trim()) &&
    !previewing &&
    !isUploading;
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
                  {t(
                    'semantic-models:import.perFileNote',
                    'Each file creates a new scheme named after the file. No target selection needed.'
                  )}
                </p>
              )}
            </div>

            {/* Target collection — only for the merge strategy. Per-file derives
                a scheme per file, so no target selection is shown. */}
            {schemeStrategy !== 'perfile' && (
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
                  {/* Create-new-scheme path: no need to leave the dialog. */}
                  <SelectItem value={CREATE_NEW}>
                    {t('semantic-models:import.createNewScheme', '＋ Create a new scheme…')}
                  </SelectItem>
                  {flatOptions.map((opt) => (
                    <SelectItem key={opt.iri} value={opt.iri}>
                      {'—'.repeat(opt.level)}
                      {opt.level > 0 ? ' ' : ''}
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {creatingNew && (
                <Input
                  autoFocus
                  value={newSchemeName}
                  onChange={(e) => setNewSchemeName(e.target.value)}
                  placeholder={t('semantic-models:import.newSchemeName', 'New scheme name (e.g. Finance Ontology)')}
                  className="mt-1"
                />
              )}
              {editableCollections.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  {t(
                    'semantic-models:import.noEditableCollections',
                    'No editable collections available. Create one first.'
                  )}
                </p>
              )}
            </div>
            )}

            {/* Conflicts-reconciled-later note — hidden when a hard IRI conflict
                needs resolving HERE (the resolution UI below takes over), since
                that note implies "handled later" which would be contradictory. */}
            {conflicts.length === 0 && (
              <div className="flex items-start gap-2 rounded-md border bg-muted/50 p-3 text-xs text-muted-foreground leading-relaxed">
                <Info className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                <span>
                  {t(
                    'semantic-models:import.reconcileNote',
                    'Overlapping or duplicate terms across schemes are reconciled later in the Review Board. Import just brings the graph in.'
                  )}
                </span>
              </div>
            )}

            {/* Error */}
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {/* Conflict resolution UI */}
            {conflicts.length > 0 && (
              <div className="grid gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
                <div className="flex items-center gap-2">
                  <Info className="h-4 w-4 text-amber-600 shrink-0" />
                  <span className="text-sm font-medium text-amber-700 dark:text-amber-300">
                    {t('semantic-models:import.conflict.title', 'Concept IRI conflicts detected')}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {t(
                    'semantic-models:import.conflict.description',
                    'The following concepts already exist in this scheme. Choose how to handle them:'
                  )}
                </p>
                <ul className="space-y-1 text-xs">
                  {conflicts.slice(0, 5).map((c) => (
                    <li key={c.iri} className="flex items-start gap-2 pl-2">
                      <span className="shrink-0 mt-0.5">•</span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-medium">{c.existing_label || c.iri}</div>
                        <div className="text-muted-foreground truncate">{c.existing_context}</div>
                      </div>
                    </li>
                  ))}
                  {conflicts.length > 5 && (
                    <li className="text-muted-foreground pl-2">
                      {t('semantic-models:import.conflict.more', { count: conflicts.length - 5, defaultValue: 'and {{count}} more' })}
                    </li>
                  )}
                </ul>
                <div className="space-y-2 pt-2 border-t">
                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="radio"
                      name="conflict-mode"
                      value="update"
                      checked={conflictMode === 'update'}
                      onChange={() => setConflictMode('update')}
                      className="mt-1"
                    />
                    <div>
                      <div className="text-xs font-medium">{t('semantic-models:import.conflict.update', 'Update existing')}</div>
                      <div className="text-xs text-muted-foreground">
                        {t('semantic-models:import.conflict.updateDesc', 'Overwrite existing concepts with new definitions')}
                      </div>
                    </div>
                  </label>
                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="radio"
                      name="conflict-mode"
                      value="skip"
                      checked={conflictMode === 'skip'}
                      onChange={() => setConflictMode('skip')}
                      className="mt-1"
                    />
                    <div>
                      <div className="text-xs font-medium">{t('semantic-models:import.conflict.skip', 'Import only new')}</div>
                      <div className="text-xs text-muted-foreground">
                        {t('semantic-models:import.conflict.skipDesc', 'Skip conflicting IRIs, import the rest')}
                      </div>
                    </div>
                  </label>
                </div>
              </div>
            )}

            {/* Per-file outcomes + structural summary (CB-10, partial) */}
            {outcomes && (
              <div className="grid gap-2">
                {outcomes.some((r) => r.ok) && (
                  <Alert>
                    <AlertDescription>
                      {outcomes.some((r) => r.ok && r.status === 'held')
                        ? t('semantic-models:import.summaryPending', {
                            files: outcomes.filter((r) => r.ok).length,
                            defaultValue: 'Upload submitted for approval ({{files}} file(s))',
                          })
                        : t('semantic-models:import.summary', {
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
                        <div className="flex items-center gap-2 shrink-0">
                          {r.status === 'held' ? (
                            <span className="text-amber-600 dark:text-amber-400">
                              {t('semantic-models:import.filePending', 'Pending approval')}
                              {r.review_request_id && (
                                <span className="text-muted-foreground ml-1 font-mono text-[10px]">
                                  ({r.review_request_id.substring(0, 8)})
                                </span>
                              )}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">
                              {t('semantic-models:import.fileOk', {
                                count: r.triplesImported ?? 0,
                                defaultValue: '{{count}} triples',
                              })}
                            </span>
                          )}
                        </div>
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

            {/* Computing the diff while files are being staged against a
                non-empty scheme. */}
            {previewing && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground rounded-md border bg-muted/30 px-3 py-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {t('semantic-models:import.computingDiff', 'Computing changes…')}
              </div>
            )}

            {/* Diff panel. Shown BEFORE Import (review the changes, then decide);
                once imported (outcomes set), the same panel reads as a summary of
                what was applied. Import applies exactly what is shown here. */}
            {previews.map((pv) => (
              <div key={pv.preview_token} className="grid gap-2 rounded-md border bg-muted/30 p-3">
                <div className="flex items-center gap-2">
                  <Info className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="text-sm font-medium">
                    {outcomes
                      ? t('semantic-models:import.changelogTitle', 'Changes applied from {{file}}', { file: pv.fileName })
                      : t('semantic-models:import.previewTitle', 'Changes from {{file}}', { file: pv.fileName })}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {t('semantic-models:import.changelogSummary', {
                    modified: pv.summary.modified,
                    added: pv.summary.new,
                    removed: pv.summary.removed,
                    unchanged: pv.summary.unchanged,
                    defaultValue:
                      'Modifies {{modified}}, adds {{added}}, removes {{removed}} ({{unchanged}} unchanged).',
                  })}
                </p>
                {(['modified', 'new', 'removed'] as const).map((bucket) => {
                  const items = pv[bucket];
                  if (!items.length) return null;
                  const labelForBucket =
                    bucket === 'modified'
                      ? t('semantic-models:import.bucketModified', 'Modified (new version)')
                      : bucket === 'new'
                      ? t('semantic-models:import.bucketNew', 'New')
                      : t('semantic-models:import.bucketRemoved', 'Removed (deprecated, not deleted)');
                  return (
                    <div key={bucket} className="text-xs">
                      <div className="font-medium text-muted-foreground mb-0.5">{labelForBucket}</div>
                      <ul className="space-y-0.5">
                        {items.map((c) => (
                          <li key={c.iri} className="flex items-center gap-2">
                            <span className="truncate">{c.label || c.iri}</span>
                            {bucket === 'removed' && (c.reference_count ?? 0) > 0 && (
                              <span className="text-amber-600 shrink-0">
                                {t('semantic-models:import.stillReferenced', {
                                  count: c.reference_count ?? 0,
                                  defaultValue: 'used by {{count}}',
                                })}
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>

          <DialogFooter>
            {/* Single action: one Import button. On a re-upload the diff is shown
                ABOVE (review, then decide) and Import applies exactly that; on a
                first import there is nothing to diff. Once done → Close. */}
            {(() => {
              const done = !!outcomes;
              return (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => handleOpenChange(false)}
                    disabled={isUploading}
                  >
                    {done
                      ? t('common:actions.close', 'Close')
                      : t('common:actions.cancel', 'Cancel')}
                  </Button>
                  {!done && (
                    <Button type="submit" disabled={!canSubmit}>
                      {isUploading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                      <Upload className="h-4 w-4 mr-2" />
                      {t('semantic-models:import.submitMulti', {
                        count: selectedFiles.length,
                        defaultValue: 'Import {{count}} file(s)',
                      })}
                    </Button>
                  )}
                </>
              );
            })()}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default ImportConceptsDialog;

import React from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Loader2 } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useApi } from '@/hooks/use-api';

export type MarkdownImportStatus =
  'added' | 'updated' | 'unchanged' | 'unlinked' | 'failed' | 'removed';

export interface MarkdownImportFileResult {
  path: string;
  status: MarkdownImportStatus;
  title?: string | null;
  targets: { entity_type: string; entity_id: string; name?: string | null }[];
  unresolved: { kind: string; value: string; reason: string }[];
  /** Documents removed because the changed file no longer names their entity. */
  removed?: number;
  reason?: string | null;
}

export interface MarkdownImportResult {
  path: string;
  added: number;
  updated: number;
  unchanged: number;
  unlinked: number;
  failed: number;
  /** Files imported from this folder before that are gone (their documents were removed). */
  removed: number;
  /** Codes, e.g. empty_folder (nothing listed, so nothing was removed). */
  warnings?: string[];
  files: MarkdownImportFileResult[];
}

const STATUSES: MarkdownImportStatus[] = [
  'added', 'updated', 'unchanged', 'unlinked', 'failed', 'removed',
];

// Codes the import answers with; any other error shows the server's text.
const ERROR_CODES = new Set([
  'markdown_import_path_invalid',
  'markdown_import_path_not_found',
  'markdown_import_access_denied',
  'markdown_import_too_many_files',
]);

const UNRESOLVED_KEYS: Record<string, string> = {
  not_found: 'notFound',
  ambiguous: 'ambiguous',
  forbidden: 'forbidden',
};

type BadgeVariant = 'default' | 'secondary' | 'outline' | 'destructive';

const STATUS_VARIANT: Record<MarkdownImportStatus, BadgeVariant> = {
  added: 'default',
  updated: 'default',
  unchanged: 'secondary',
  unlinked: 'outline',
  failed: 'destructive',
  removed: 'secondary',
};

const targetNames = (file: MarkdownImportFileResult) =>
  file.targets.map(target => target.name || target.entity_id).join(', ');

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after an import that added or updated documents. */
  onImported?: (result: MarkdownImportResult) => void;
}

/** Import the Markdown files of a volume folder as documents on the entities they name. */
const MarkdownImportDialog: React.FC<Props> = ({ open, onOpenChange, onImported }) => {
  const { t } = useTranslation(['metadata', 'common']);
  const { post } = useApi();
  const [path, setPath] = React.useState('');
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<MarkdownImportResult | null>(null);

  React.useEffect(() => {
    if (!open) {
      setError(null);
      setResult(null);
      setRunning(false);
    }
  }, [open]);

  const runImport = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    const response = await post<MarkdownImportResult>(
      '/api/metadata/markdown-import', { path: path.trim() },
    );
    setRunning(false);
    if (response.error) {
      const code = response.errorCode;
      setError(code && ERROR_CODES.has(code)
        ? t(`markdownImport.errors.${code}`, {
          ...(response.errorParams || {}), defaultValue: response.error,
        })
        : response.error || t('markdownImport.errors.failed'));
      return;
    }
    setResult(response.data);
    const { added, updated, removed } = response.data;
    if (added || updated || removed) onImported?.(response.data);
  };

  const describeUnresolved = (file: MarkdownImportFileResult) => file.unresolved
    .map(u => {
      const key = UNRESOLVED_KEYS[u.reason] ?? 'notFound';
      return t(`markdownImport.unresolved.${key}`, {
        kind: t(`markdownImport.kinds.${u.kind}`, { defaultValue: u.kind }),
        value: u.value,
      });
    })
    .join('; ');

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('markdownImport.title')}</DialogTitle>
          <DialogDescription>{t('markdownImport.description')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="markdown-import-path">{t('markdownImport.pathLabel')}</Label>
          <Input
            id="markdown-import-path"
            value={path}
            placeholder="/Volumes/catalog/schema/volume/docs"
            onChange={e => setPath(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && path.trim() && !running) runImport(); }}
            disabled={running}
          />
          <p className="text-xs text-muted-foreground">{t('markdownImport.frontMatterHint')}</p>
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {result && (
          <div className="space-y-3" data-testid="markdown-import-result">
            <div className="flex flex-wrap gap-2">
              {STATUSES.map(status => (
                <Badge key={status} variant={result[status] ? STATUS_VARIANT[status] : 'outline'}>
                  {t(`markdownImport.summary.${status}`, { count: result[status] })}
                </Badge>
              ))}
            </div>
            {(result.warnings ?? []).map(code => (
              <Alert key={code}>
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  {t(`markdownImport.warnings.${code}`, { defaultValue: code })}
                </AlertDescription>
              </Alert>
            ))}
            {result.files.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('markdownImport.noFiles')}</p>
            ) : (
              <ScrollArea className="max-h-72 rounded border">
                <ul className="divide-y text-sm">
                  {result.files.map(file => (
                    <li key={file.path} className="p-2 space-y-1">
                      <div className="flex items-center gap-2">
                        <Badge variant={STATUS_VARIANT[file.status]} className="shrink-0">
                          {t(`markdownImport.status.${file.status}`)}
                        </Badge>
                        <span className="font-mono text-xs truncate" title={file.path}>
                          {file.path}
                        </span>
                      </div>
                      {file.targets.length > 0 && (
                        <div className="text-xs text-muted-foreground">
                          {t('markdownImport.linkedTo', { targets: targetNames(file) })}
                        </div>
                      )}
                      {(file.removed ?? 0) > 0 && (
                        <div className="text-xs text-muted-foreground">
                          {t(file.status === 'removed'
                            ? 'markdownImport.reasons.gone'
                            : 'markdownImport.removed', { count: file.removed })}
                        </div>
                      )}
                      {file.unresolved.length > 0 && (
                        <div className="text-xs text-muted-foreground">
                          {describeUnresolved(file)}
                        </div>
                      )}
                      {file.status === 'unlinked' && file.unresolved.length === 0 && (
                        <div className="text-xs text-muted-foreground">
                          {t('markdownImport.noTargets')}
                        </div>
                      )}
                      {file.reason && (
                        <div className="text-xs text-destructive">
                          {t(`markdownImport.reasons.${file.reason}`, {
                            defaultValue: file.reason,
                          })}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </ScrollArea>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('markdownImport.close')}
          </Button>
          <Button onClick={runImport} disabled={!path.trim() || running}>
            {running && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {running ? t('markdownImport.importing') : t('markdownImport.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default MarkdownImportDialog;

import { useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Loader2, FileUp, AlertCircle } from 'lucide-react';
import type { ModelImportRunDetail } from '@/types/model-import';

/**
 * Upload step of an erwin model import (PRD #1718). The file is parsed into a
 * previewed run on the server; review, options and confirm happen on the run
 * page, so a large preview has room and survives a reload. Nothing is
 * imported before the steward confirms there.
 */
interface ModelImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Which layers to preselect: contracts from the contracts page, concepts from Concepts. */
  layers?: { logical: boolean; physical: boolean };
}

export default function ModelImportDialog({ open, onOpenChange, layers }: ModelImportDialogProps) {
  const { t } = useTranslation('model-import');
  const navigate = useNavigate();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = async (files: File[]) => {
    const file = files[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append('file', file);
      if (layers) {
        form.append('options', JSON.stringify({
          import_logical: layers.logical,
          import_physical: layers.physical,
        }));
      }
      const res = await fetch('/api/model-import/runs', { method: 'POST', body: form });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        const detail = body?.detail;
        setError(typeof detail === 'string' ? detail : t('upload.failed'));
        return;
      }
      const run = body as ModelImportRunDetail;
      onOpenChange(false);
      navigate(`/model-imports/${run.id}`);
    } catch {
      setError(t('upload.failed'));
    } finally {
      setUploading(false);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: upload,
    multiple: false,
    disabled: uploading,
    accept: { 'application/xml': ['.xml'], 'text/xml': ['.xml'] },
  });

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!uploading) { setError(null); onOpenChange(o); } }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('upload.title')}</DialogTitle>
          <DialogDescription>{t('upload.description')}</DialogDescription>
        </DialogHeader>
        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
            isDragActive ? 'border-primary bg-primary/5' : 'border-muted-foreground/25 hover:border-primary/50'
          }`}
        >
          <input {...getInputProps()} aria-label={t('upload.title')} />
          {uploading ? (
            <div className="flex flex-col items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-6 w-6 animate-spin" />
              {t('upload.parsing')}
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <FileUp className="h-6 w-6 text-muted-foreground" />
              <p className="text-sm">{isDragActive ? t('upload.dropActive') : t('upload.dropInactive')}</p>
              <p className="text-xs text-muted-foreground">{t('upload.formats')}</p>
            </div>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{t('upload.howToExport')}</p>
        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription className="break-words">{error}</AlertDescription>
          </Alert>
        )}
      </DialogContent>
    </Dialog>
  );
}

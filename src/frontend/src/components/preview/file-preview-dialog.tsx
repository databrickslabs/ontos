import React from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Loader2 } from 'lucide-react';

type FilePreviewSource = {
  title?: string;
  contentType?: string | null;
  storagePath?: string; // UC Volumes path if applicable
  originalFilename?: string;
  downloadUrl?: string; // optional signed URL if available
};

interface FilePreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  source: FilePreviewSource | null;
  fetchUrl?: (() => Promise<string | undefined>) | null;
}

const isImage = (ct?: string | null) => !!ct && ct.startsWith('image/');
const isPdf = (ct?: string | null) => ct === 'application/pdf';
const isText = (ct?: string | null) => !!ct && (ct.startsWith('text/') || ct.includes('json') || ct.includes('csv'));

export const FilePreviewDialog: React.FC<FilePreviewDialogProps> = ({ open, onOpenChange, source, fetchUrl }) => {
  const { t } = useTranslation(['data-catalog', 'common']);
  const title = source?.title || source?.originalFilename || t('data-catalog:preview.title');
  const ct = source?.contentType;
  const [url, setUrl] = React.useState<string | undefined>(source?.downloadUrl);
  const [fetching, setFetching] = React.useState<boolean>(false);
  const [loading, setLoading] = React.useState<boolean>(false);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);

  React.useEffect(() => {
    setUrl(source?.downloadUrl);
    setLoading(!!source);
    setErrorMsg(null);
  }, [source?.downloadUrl, source?.storagePath]);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!url && fetchUrl) {
        try {
          setFetching(true);
          setLoading(true);
          const u = await fetchUrl();
          if (!cancelled) {
            if (u) {
              setUrl(u);
              setErrorMsg(null);
            } else {
              setErrorMsg(t('data-catalog:preview.notAvailable'));
            }
          }
        } catch {
          if (!cancelled) setErrorMsg(t('data-catalog:preview.fetchFailed'));
        } finally {
          if (!cancelled) setFetching(false);
        }
      }
    })();
    return () => { cancelled = true };
  }, [url, fetchUrl]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="relative min-h-[320px] flex items-center justify-center">
          {url ? (
            isImage(ct) ? (
              <img
                src={url}
                alt={title}
                className="max-h-[70vh] max-w-full rounded"
                onLoad={() => { setLoading(false); setErrorMsg(null); }}
                onError={() => { setLoading(false); setErrorMsg(t('data-catalog:preview.loadImageFailed')); }}
              />
            ) : isPdf(ct) ? (
              <object
                data={url}
                type="application/pdf"
                className="w-full h-[70vh] rounded"
                onLoad={() => { setLoading(false); setErrorMsg(null); }}
              >
                <p className="text-sm text-muted-foreground">{t('data-catalog:preview.pdfNotSupported')} <a className="underline" href={url} target="_blank" rel="noreferrer">{t('common:actions.open')}</a></p>
              </object>
            ) : isText(ct) ? (
              <iframe
                src={url}
                title={t('data-catalog:preview.textPreviewTitle')}
                className="w-full h-[70vh] rounded bg-background"
                onLoad={() => { setLoading(false); setErrorMsg(null); }}
              />
            ) : (
              <div className="text-sm text-muted-foreground">{t('data-catalog:preview.noInlinePreview')} {url && (<a className="underline ml-1" href={url} target="_blank" rel="noreferrer">{t('common:actions.download')}</a>)}
              </div>
            )
          ) : (!fetching && !loading && !fetchUrl) ? (
            <div className="text-sm text-muted-foreground">
              {t('data-catalog:preview.noPreviewUrl', { filename: source?.originalFilename, path: source?.storagePath })}
            </div>
          ) : null}
          {(fetching || loading) && (
            <div className="absolute inset-0 flex items-center justify-center">
              <Loader2 className="h-12 w-12 animate-spin text-primary" />
            </div>
          )}
          {!fetching && !loading && errorMsg && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-sm text-destructive bg-background/80 p-2 rounded">{errorMsg}</div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default FilePreviewDialog;



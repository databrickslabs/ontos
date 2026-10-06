import React from 'react';
import { useDropzone, Accept } from 'react-dropzone';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Loader2 } from 'lucide-react';

/**
 * Shared upload dialog for ODCS Data Contracts and ODPS Data Products.
 *
 * The two pages previously hand-rolled their own dialogs, which drifted apart
 * (one had a dropzone + paste box, the other a bare "Choose file(s)" button and
 * a subtitle). This single component keeps them identical: subtitle, the three
 * import toggles, a drag-&-drop zone, and an optional "paste JSON" box. Each page
 * supplies its own copy (`labels`), toggle state, and upload/paste handlers so
 * the per-feature i18n namespaces and backend calls stay where they belong.
 */

export interface ImportEntityDialogLabels {
  title: string;
  description: string;
  createMissingDomains: string;
  createMissingDomainsHint: string;
  adoptIds: string;
  adoptIdsHint: string;
  duplicatesAsNew: string;
  duplicatesAsNewHint: string;
  dropActive: string;
  dropInactive: string;
  supportedFormats: string;
  /** Paste section (optional — omit `paste` prop to hide it). */
  pasteLabel?: string;
  pastePlaceholder?: string;
  pasteButton?: string;
}

export interface ImportEntityToggleState {
  createMissingDomains: boolean;
  setCreateMissingDomains: (v: boolean) => void;
  adoptIds: boolean;
  setAdoptIds: (v: boolean) => void;
  duplicatesAsNew: boolean;
  setDuplicatesAsNew: (v: boolean) => void;
}

export interface ImportEntityPaste {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  submitting: boolean;
}

interface ImportEntityDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  labels: ImportEntityDialogLabels;
  toggles: ImportEntityToggleState;
  /** react-dropzone accept map; restrict to the structured formats you support. */
  accept: Accept;
  /** Called with the dropped/selected files. */
  onFiles: (files: File[]) => void;
  uploading: boolean;
  disabled?: boolean;
  /** Optional paste-JSON section. */
  paste?: ImportEntityPaste;
  /** Optional alert/summary node rendered at the top of the dialog body. */
  alert?: React.ReactNode;
}

export function ImportEntityDialog({
  open,
  onOpenChange,
  labels,
  toggles,
  accept,
  onFiles,
  uploading,
  disabled = false,
  paste,
  alert,
}: ImportEntityDialogProps) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept,
    multiple: true,
    disabled: uploading || disabled,
    onDrop: (acceptedFiles) => {
      if (acceptedFiles.length > 0) onFiles(acceptedFiles);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{labels.title}</DialogTitle>
          <DialogDescription>{labels.description}</DialogDescription>
        </DialogHeader>

        {alert}

        <div className="flex items-center justify-between rounded-md border p-3">
          <div className="pr-3">
            <Label htmlFor="ied-createMissingDomains" className="cursor-pointer">{labels.createMissingDomains}</Label>
            <p className="text-xs text-muted-foreground mt-1">{labels.createMissingDomainsHint}</p>
          </div>
          <Switch
            id="ied-createMissingDomains"
            checked={toggles.createMissingDomains}
            onCheckedChange={toggles.setCreateMissingDomains}
            disabled={uploading}
          />
        </div>
        <div className="flex items-center justify-between rounded-md border p-3">
          <div className="pr-3">
            <Label htmlFor="ied-adoptIds" className="cursor-pointer">{labels.adoptIds}</Label>
            <p className="text-xs text-muted-foreground mt-1">{labels.adoptIdsHint}</p>
          </div>
          <Switch id="ied-adoptIds" checked={toggles.adoptIds} onCheckedChange={toggles.setAdoptIds} disabled={uploading} />
        </div>
        <div className="flex items-center justify-between rounded-md border p-3">
          <div className="pr-3">
            <Label htmlFor="ied-duplicatesAsNew" className="cursor-pointer">{labels.duplicatesAsNew}</Label>
            <p className="text-xs text-muted-foreground mt-1">{labels.duplicatesAsNewHint}</p>
          </div>
          <Switch id="ied-duplicatesAsNew" checked={toggles.duplicatesAsNew} onCheckedChange={toggles.setDuplicatesAsNew} disabled={uploading} />
        </div>

        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-md p-6 text-center cursor-pointer ${
            isDragActive ? 'border-primary bg-primary/5' : 'border-muted-foreground/25'
          }`}
        >
          <input {...getInputProps()} />
          {uploading ? (
            <div className="flex justify-center">
              <Loader2 className="animate-spin h-8 w-8 text-primary" />
            </div>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">{isDragActive ? labels.dropActive : labels.dropInactive}</p>
              <p className="text-xs text-muted-foreground mt-2">{labels.supportedFormats}</p>
            </>
          )}
        </div>

        {paste && (
          <div className="mt-2">
            <Label htmlFor="ied-paste">{labels.pasteLabel}</Label>
            <textarea
              id="ied-paste"
              placeholder={labels.pastePlaceholder}
              className="flex min-h-[120px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              value={paste.value}
              onChange={(e) => paste.onChange(e.target.value)}
              disabled={paste.submitting || uploading}
            />
            <Button
              className="mt-2 w-full"
              disabled={!paste.value.trim() || paste.submitting || uploading}
              onClick={paste.onSubmit}
            >
              {paste.submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {labels.pasteButton}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default ImportEntityDialog;

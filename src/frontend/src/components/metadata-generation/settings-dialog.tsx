import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Loader2 } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type {
  MetadataGenerationSettings,
  MetadataGenerationSettingsResponse,
} from '@/types/metadata-generation';

interface Props {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

const SETTINGS_URL = '/api/metadata-generation/settings';

/** Feature admins: limits, data sampling and allowed serving endpoints of Generation Runs. */
export default function SettingsDialog({ isOpen, onOpenChange }: Props) {
  const { t } = useTranslation(['metadata-generation', 'common']);
  const { get, put } = useApi();
  const { toast } = useToast();
  const [loaded, setLoaded] = useState<MetadataGenerationSettingsResponse | null>(null);
  const [maxTables, setMaxTables] = useState('500');
  const [maxActive, setMaxActive] = useState('1');
  const [allowSampling, setAllowSampling] = useState(false);
  const [sampleSize, setSampleSize] = useState('5');
  const [sendMetadata, setSendMetadata] = useState(true);
  const [endpoints, setEndpoints] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      // Load afresh next time
      setLoaded(null);
      setError(null);
    }
    onOpenChange(open);
  };

  useEffect(() => {
    if (!isOpen) return;
    void (async () => {
      const res = await get<MetadataGenerationSettingsResponse>(SETTINGS_URL);
      if (res.error || !res.data) {
        setError(res.error || t('settings.loadFailed'));
        return;
      }
      const s = res.data;
      setLoaded(s);
      setMaxTables(String(s.max_tables_per_run));
      setMaxActive(String(s.max_active_runs_per_user));
      setAllowSampling(s.allow_data_sampling);
      setSampleSize(String(s.sample_size));
      setSendMetadata(s.send_column_metadata);
      setEndpoints(s.allowed_endpoints.join('\n'));
    })();
  }, [isOpen, get, t]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    const body: MetadataGenerationSettings = {
      max_tables_per_run: Number(maxTables),
      max_active_runs_per_user: Number(maxActive),
      allow_data_sampling: allowSampling,
      sample_size: Number(sampleSize),
      send_column_metadata: sendMetadata,
      allowed_endpoints: endpoints
        .split(/[\n,]/)
        .map((e) => e.trim())
        .filter(Boolean),
    };
    const res = await put<MetadataGenerationSettingsResponse>(SETTINGS_URL, body);
    setSaving(false);
    if (res.error) {
      setError(res.error);
      return;
    }
    toast({ title: t('settings.saved') });
    handleOpenChange(false);
  };

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>{t('settings.title')}</DialogTitle>
          <DialogDescription>{t('settings.description')}</DialogDescription>
        </DialogHeader>

        {!loaded && !error ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label htmlFor="metagen-max-tables">{t('settings.maxTables')}</Label>
                <Input
                  id="metagen-max-tables"
                  type="number"
                  min={1}
                  max={5000}
                  value={maxTables}
                  onChange={(e) => setMaxTables(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="metagen-max-active">{t('settings.maxActiveRuns')}</Label>
                <Input
                  id="metagen-max-active"
                  type="number"
                  min={1}
                  max={20}
                  value={maxActive}
                  onChange={(e) => setMaxActive(e.target.value)}
                />
              </div>
            </div>

            <div className="flex items-start justify-between gap-4">
              <div className="grid gap-0.5">
                <Label htmlFor="metagen-send-metadata">{t('settings.sendColumnMetadata')}</Label>
                <p className="text-xs text-muted-foreground">{t('settings.sendColumnMetadataHint')}</p>
              </div>
              <Switch id="metagen-send-metadata" checked={sendMetadata} onCheckedChange={setSendMetadata} />
            </div>

            <div className="flex items-start justify-between gap-4">
              <div className="grid gap-0.5">
                <Label htmlFor="metagen-allow-sampling">{t('settings.allowSampling')}</Label>
                <p className="text-xs text-muted-foreground">{t('settings.allowSamplingHint')}</p>
              </div>
              <Switch id="metagen-allow-sampling" checked={allowSampling} onCheckedChange={setAllowSampling} />
            </div>
            {allowSampling && (
              <div className="space-y-1 max-w-[200px]">
                <Label htmlFor="metagen-sample-size">{t('settings.sampleSize')}</Label>
                <Input
                  id="metagen-sample-size"
                  type="number"
                  min={1}
                  max={50}
                  value={sampleSize}
                  onChange={(e) => setSampleSize(e.target.value)}
                />
              </div>
            )}

            <div className="space-y-1">
              <Label htmlFor="metagen-endpoints">{t('settings.allowedEndpoints')}</Label>
              <Textarea
                id="metagen-endpoints"
                rows={3}
                className="font-mono text-sm"
                value={endpoints}
                onChange={(e) => setEndpoints(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {t('settings.allowedEndpointsHint', { endpoint: loaded?.default_endpoint ?? '' })}
              </p>
            </div>
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription className="break-words">{error}</AlertDescription>
          </Alert>
        )}

        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={saving}>
              {t('common:actions.cancel')}
            </Button>
          </DialogClose>
          <Button onClick={() => void handleSave()} disabled={saving || !loaded}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('common:actions.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Loader2, Save, Truck } from 'lucide-react';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import { useToast } from '@/hooks/use-toast';

interface DeliveryModeSettings {
  deliveryModeDirect: boolean;
  deliveryModeIndirect: boolean;
  deliveryModeManual: boolean;
  deliveryDirectDryRun: boolean;
}

export default function DeliverySettings() {
  const { t } = useTranslation(['settings', 'common']);
  const { hasPermission } = usePermissions();
  const { toast } = useToast();

  const hasWriteAccess = hasPermission('settings-delivery', FeatureAccessLevel.READ_WRITE);

  const [settings, setSettings] = useState<DeliveryModeSettings>({
    deliveryModeDirect: false,
    deliveryModeIndirect: false,
    deliveryModeManual: true,
    deliveryDirectDryRun: false,
  });
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    const fetchSettings = async () => {
      setIsLoading(true);
      try {
        const response = await fetch('/api/settings');
        if (response.ok) {
          const data = await response.json();
          setSettings({
            deliveryModeDirect: data.delivery_mode_direct || false,
            deliveryModeIndirect: data.delivery_mode_indirect || false,
            deliveryModeManual: data.delivery_mode_manual ?? true,
            deliveryDirectDryRun: data.delivery_direct_dry_run || false,
          });
        }
      } catch (error) {
        console.error('Failed to fetch delivery settings:', error);
      } finally {
        setIsLoading(false);
      }
    };
    fetchSettings();
  }, []);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          delivery_mode_direct: settings.deliveryModeDirect,
          delivery_mode_indirect: settings.deliveryModeIndirect,
          delivery_mode_manual: settings.deliveryModeManual,
          delivery_direct_dry_run: settings.deliveryDirectDryRun,
        }),
      });
      if (response.ok) {
        toast({
          title: t('settings:delivery.saveButton', 'Delivery settings saved successfully'),
        });
      } else {
        throw new Error('Failed to save delivery settings');
      }
    } catch (error) {
      toast({
        title: t('settings:general.messages.saveError', 'Failed to save settings'),
        variant: 'destructive',
      });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <>
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Truck className="w-8 h-8" />
          {t('settings:delivery.title', 'Delivery Modes')}
        </h1>
        <p className="text-muted-foreground mt-1">
          {t('settings:delivery.description', 'Configure how governance changes are propagated to external systems. Multiple modes can be active simultaneously.')}
        </p>
      </div>

      <div className="space-y-6">
        {/* Direct Mode */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="delivery-direct" className="text-base font-medium">
                {t('settings:delivery.direct.label', 'Direct Mode')}
              </Label>
              <p className="text-sm text-muted-foreground">
                {t('settings:delivery.direct.description', 'Apply changes directly to Unity Catalog via SDK (GRANTs, tag assignments).')}
              </p>
            </div>
            <Switch
              id="delivery-direct"
              checked={settings.deliveryModeDirect}
              onCheckedChange={(checked) => setSettings(prev => ({ ...prev, deliveryModeDirect: checked }))}
              disabled={!hasWriteAccess || isLoading}
            />
          </div>

          {settings.deliveryModeDirect && (
            <div className="ml-6 flex items-center space-x-2">
              <Switch
                id="delivery-direct-dry-run"
                checked={settings.deliveryDirectDryRun}
                onCheckedChange={(checked) => setSettings(prev => ({ ...prev, deliveryDirectDryRun: checked }))}
                disabled={!hasWriteAccess || isLoading}
              />
              <Label htmlFor="delivery-direct-dry-run" className="text-sm">
                {t('settings:delivery.direct.dryRun', 'Dry-run mode (log changes without applying)')}
              </Label>
            </div>
          )}
        </div>

        <Separator />

        {/* Indirect Mode */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="delivery-indirect" className="text-base font-medium">
                {t('settings:delivery.indirect.label', 'Indirect Mode')}
              </Label>
              <p className="text-sm text-muted-foreground">
                {t('settings:delivery.indirect.description', 'Persist changes as YAML files in a Git repository for CI/CD integration.')}
              </p>
            </div>
            <Switch
              id="delivery-indirect"
              checked={settings.deliveryModeIndirect}
              onCheckedChange={(checked) => setSettings(prev => ({ ...prev, deliveryModeIndirect: checked }))}
              disabled={!hasWriteAccess || isLoading}
            />
          </div>

          {settings.deliveryModeIndirect && (
            <div className="ml-6 p-4 bg-muted/50 rounded-lg space-y-3">
              <p className="text-sm text-muted-foreground">
                {t('settings:delivery.indirect.gitInfo', 'Configure Git repository in the Git tab. Changes will be exported to the configured UC Volume under /git-export/.')}
              </p>
            </div>
          )}
        </div>

        <Separator />

        {/* Manual Mode */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="delivery-manual" className="text-base font-medium">
                {t('settings:delivery.manual.label', 'Manual Mode')}
              </Label>
              <p className="text-sm text-muted-foreground">
                {t('settings:delivery.manual.description', 'Generate notifications for admins to apply changes manually in external systems.')}
              </p>
            </div>
            <Switch
              id="delivery-manual"
              checked={settings.deliveryModeManual}
              onCheckedChange={(checked) => setSettings(prev => ({ ...prev, deliveryModeManual: checked }))}
              disabled={!hasWriteAccess || isLoading}
            />
          </div>
        </div>
        {hasWriteAccess && (
          <div className="pt-4">
            <Button onClick={handleSave} disabled={isSaving}>
              {isSaving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              {t('settings:delivery.saveButton', 'Save Delivery Settings')}
            </Button>
          </div>
        )}
      </div>
    </>
  );
}

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Undo2, Wand2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useApi, type ApiResponse } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { features, getNavFeatureId } from '@/config/features';
import { usePermissions } from '@/stores/permissions-store';
import {
  NAVIGATION_PRESETS_URL,
  type NavigationPreset,
  type NavigationPresetApplyResult,
  type NavigationPresetRolePreview,
  type NavigationPresetsResponse,
  type NavigationPresetUndoResult,
} from '@/types/navigation-presets';

/** Errors the preset endpoints send with a code, each with its own translated text. */
const CODED_ERRORS = ['navigation_preset_nothing_to_undo', 'navigation_preset_unknown'];

interface NavigationPresetsCardProps {
  /** Called after an apply or an undo: the roles list and the role store need a refresh. */
  onChanged?: () => void | Promise<void>;
}

type Confirming = 'apply' | 'undo' | null;

/**
 * Settings > Roles: set the menus and home page of the default roles from a preset (#1325).
 * Shows what each preset would do to each role before it is applied; applying changes only
 * menus and home pages, never access levels, and the last application can be undone.
 */
export default function NavigationPresetsCard({ onChanged }: NavigationPresetsCardProps) {
  const { t, i18n } = useTranslation(['settings', 'common', 'features']);
  const { get, post } = useApi();
  const { toast } = useToast();
  const { fetchNavigation } = usePermissions();
  const [data, setData] = useState<NavigationPresetsResponse | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [selectedId, setSelectedId] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<Confirming>(null);

  const show = useCallback((response: ApiResponse<NavigationPresetsResponse>) => {
    if (response.error || !response.data?.presets) {
      setLoadError(true);
      return;
    }
    const presets = response.data.presets;
    setLoadError(false);
    setData(response.data);
    setSelectedId((current) =>
      presets.some((p) => p.id === current) ? current : presets[0]?.id ?? '',
    );
  }, []);

  const load = useCallback(
    async () => show(await get<NavigationPresetsResponse>(NAVIGATION_PRESETS_URL)),
    [get, show],
  );

  useEffect(() => {
    let cancelled = false;
    get<NavigationPresetsResponse>(NAVIGATION_PRESETS_URL).then((response) => {
      if (!cancelled) show(response);
    });
    return () => {
      cancelled = true;
    };
  }, [get, show]);

  const selected: NavigationPreset | undefined = data?.presets.find((p) => p.id === selectedId);
  const changedCount = selected?.roles.filter((r) => r.changed).length ?? 0;
  const lastApplied = data?.last_applied ?? null;

  const presetName = (id: string) =>
    t(`settings:navigationPresets.presets.${id}.name`, { defaultValue: id });

  const entryName = (navId: string) => {
    const feature = features.find((f) => getNavFeatureId(f) === navId);
    return feature
      ? t(`features:${feature.id}.name`, { defaultValue: feature.name })
      : navId;
  };

  const sectionName = (section: string) =>
    t(`settings:roles.privileges.homeSections.labels.${section}`, { defaultValue: section });

  const errorText = (response: { error?: string | null; errorCode?: string | null }) =>
    response.errorCode && CODED_ERRORS.includes(response.errorCode)
      ? t(`settings:navigationPresets.errors.${response.errorCode}`)
      : response.error || t('settings:navigationPresets.errors.generic');

  const afterChange = async () => {
    await load();
    await Promise.all([Promise.resolve(onChanged?.()), fetchNavigation?.()]);
  };

  const apply = async () => {
    setConfirming(null);
    setBusy(true);
    const response = await post<NavigationPresetApplyResult>(
      `${NAVIGATION_PRESETS_URL}/${selectedId}/apply`, {},
    );
    if (response.error) {
      toast({
        title: t('settings:navigationPresets.applyFailed'),
        description: errorText(response),
        variant: 'destructive',
      });
      await load();
    } else {
      const result = response.data;
      toast({
        title: result.changed_roles.length > 0
          ? t('settings:navigationPresets.applied', { preset: presetName(result.preset_id) })
          : t('settings:navigationPresets.nothingChanged'),
        description: t('settings:navigationPresets.appliedSummary', {
          changed: result.changed_roles.length,
          unchanged: result.unchanged_roles.length,
          missing: result.missing_roles.length,
        }),
      });
      await afterChange();
    }
    setBusy(false);
  };

  const undo = async () => {
    setConfirming(null);
    setBusy(true);
    const response = await post<NavigationPresetUndoResult>(`${NAVIGATION_PRESETS_URL}/undo`, {});
    if (response.error) {
      toast({
        title: t('settings:navigationPresets.undoFailed'),
        description: errorText(response),
        variant: 'destructive',
      });
      await load();
    } else {
      const result = response.data;
      toast({
        title: t('settings:navigationPresets.undone', { preset: presetName(result.preset_id) }),
        description: t('settings:navigationPresets.undoneSummary', {
          restored: result.restored_roles.length,
          missing: result.missing_roles.length,
        }),
      });
      await afterChange();
    }
    setBusy(false);
  };

  const lastAppliedText = useMemo(() => {
    if (!lastApplied) return '';
    const when = new Date(lastApplied.applied_at);
    return t('settings:navigationPresets.lastApplied', {
      preset: presetName(lastApplied.preset_id),
      user: lastApplied.applied_by || t('settings:navigationPresets.unknownUser'),
      date: Number.isNaN(when.getTime())
        ? lastApplied.applied_at
        : when.toLocaleString(i18n.language),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastApplied, t, i18n.language]);

  const renderRole = (role: NavigationPresetRolePreview) => {
    const menu = role.shown.filter((id) => !role.no_access.includes(id));
    return (
      <TableRow key={role.role_name} data-testid={`preset-role-${role.role_name}`}>
        <TableCell className="font-medium">{role.role_name}</TableCell>
        <TableCell>
          {role.found && (
            <>
              <div>
                {menu.length > 0
                  ? menu.map(entryName).join(', ')
                  : t('settings:navigationPresets.preview.menuEmpty')}
              </div>
              {role.no_access.length > 0 && (
                <div className="text-xs text-muted-foreground" data-testid="preset-no-access">
                  {t('settings:navigationPresets.preview.noAccess', {
                    features: role.no_access.map(entryName).join(', '),
                  })}
                </div>
              )}
            </>
          )}
        </TableCell>
        <TableCell>
          {role.found && (role.home_sections && role.home_sections.length > 0
            ? role.home_sections.map(sectionName).join(', ')
            : t('settings:navigationPresets.preview.homeUnchanged'))}
        </TableCell>
        <TableCell>
          {!role.found ? (
            <Badge variant="outline">{t('settings:navigationPresets.status.notFound')}</Badge>
          ) : role.changed ? (
            <Badge>{t('settings:navigationPresets.status.changes')}</Badge>
          ) : (
            <Badge variant="secondary">{t('settings:navigationPresets.status.noChange')}</Badge>
          )}
        </TableCell>
      </TableRow>
    );
  };

  return (
    <Card className="mb-6" data-testid="navigation-presets-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <Wand2 className="h-5 w-5" />
          {t('settings:navigationPresets.title')}
        </CardTitle>
        <CardDescription data-testid="navigation-presets-help">
          {t('settings:navigationPresets.help')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {loadError && (
          <p className="text-sm text-destructive">{t('settings:navigationPresets.loadFailed')}</p>
        )}
        {!data && !loadError && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
        {data && (
          <>
            <RadioGroup value={selectedId} onValueChange={setSelectedId} className="gap-3">
              {data.presets.map((preset) => (
                <div key={preset.id} className="flex items-start gap-3">
                  <RadioGroupItem
                    value={preset.id}
                    id={`preset-${preset.id}`}
                    className="mt-1"
                  />
                  <Label htmlFor={`preset-${preset.id}`} className="font-normal">
                    <span className="font-medium">{presetName(preset.id)}</span>
                    <span className="block text-xs text-muted-foreground">
                      {t(`settings:navigationPresets.presets.${preset.id}.description`, {
                        defaultValue: '',
                      })}
                    </span>
                  </Label>
                </div>
              ))}
            </RadioGroup>

            {selected && (
              <Table data-testid="navigation-presets-preview">
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('settings:navigationPresets.preview.role')}</TableHead>
                    <TableHead>{t('settings:navigationPresets.preview.menu')}</TableHead>
                    <TableHead>{t('settings:navigationPresets.preview.home')}</TableHead>
                    <TableHead>{t('settings:navigationPresets.preview.status')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>{selected.roles.map(renderRole)}</TableBody>
              </Table>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <Button
                size="sm"
                disabled={busy || !selected || changedCount === 0}
                onClick={() => setConfirming('apply')}
                title={
                  changedCount === 0 ? t('settings:navigationPresets.nothingToApply') : undefined
                }
              >
                {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {t('settings:navigationPresets.actions.apply')}
              </Button>
              {lastApplied && (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => setConfirming('undo')}
                  >
                    <Undo2 className="mr-2 h-4 w-4" />
                    {t('settings:navigationPresets.actions.undo')}
                  </Button>
                  <span className="text-xs text-muted-foreground" data-testid="preset-last-applied">
                    {lastAppliedText}
                  </span>
                </>
              )}
            </div>
          </>
        )}
      </CardContent>

      <AlertDialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirming === 'undo'
                ? t('settings:navigationPresets.confirm.undoTitle')
                : t('settings:navigationPresets.confirm.applyTitle', {
                  preset: presetName(selectedId),
                })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirming === 'undo'
                ? t('settings:navigationPresets.confirm.undoDescription', {
                  preset: lastApplied ? presetName(lastApplied.preset_id) : '',
                  count: lastApplied?.roles.length ?? 0,
                })
                : t('settings:navigationPresets.confirm.applyDescription', {
                  count: changedCount,
                })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:actions.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={confirming === 'undo' ? undo : apply}>
              {confirming === 'undo'
                ? t('settings:navigationPresets.actions.undo')
                : t('settings:navigationPresets.actions.apply')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}

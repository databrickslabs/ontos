import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, Pencil, Plus, Star, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { ListItemSkeleton } from '@/components/common/list-view-skeleton';
import StageBadge from '@/components/lifecycle/stage-badge';
import LifecycleStageGroupEditor, {
  initialEditorState,
  toWrite,
} from '@/components/lifecycle/lifecycle-stage-group-editor';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { useLifecycleStageGroups } from '@/hooks/use-lifecycle-stage-groups';
import {
  groupDescription, groupName, lifecycleErrorText, orderedStages,
} from '@/lib/lifecycle-stages';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import {
  LIFECYCLE_ENTITY_TYPES,
  type LifecycleEntityType,
  type LifecycleStageGroup,
} from '@/types/lifecycle-stage-groups';

const FEATURE_ID = 'settings-lifecycle-stage-groups';

/**
 * Settings > Lifecycle Stage Groups: the groups of each entity type, the
 * type's default first. With write access: create, edit, make default and
 * delete (the backend refuses a default or assigned group, with a coded error).
 */
export default function LifecycleStageGroupsSettings() {
  const { t } = useTranslation(['lifecycle', 'common']);
  const { toast } = useToast();
  const { put, delete: apiDelete } = useApi();
  const { hasPermission } = usePermissions();
  const canWrite = hasPermission(FEATURE_ID, FeatureAccessLevel.READ_WRITE);
  const [entityType, setEntityType] = useState<LifecycleEntityType>('data_product');
  const { groups, loading, error, reload } = useLifecycleStageGroups(entityType);
  const [editing, setEditing] = useState<LifecycleStageGroup | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [deleting, setDeleting] = useState<LifecycleStageGroup | null>(null);

  const openEditor = (group: LifecycleStageGroup | null) => {
    setEditing(group);
    setEditorOpen(true);
  };

  const failed = (response: Parameters<typeof lifecycleErrorText>[0]) =>
    toast({
      title: t('common:status.error'),
      description: lifecycleErrorText(response, t),
      variant: 'destructive',
    });

  const makeDefault = async (group: LifecycleStageGroup) => {
    const body = { ...toWrite(initialEditorState(group), entityType), is_default_for_type: true };
    const response = await put(`/api/lifecycle-stage-groups/${group.id}`, body);
    if (response.error) return failed(response);
    toast({ title: t('lifecycle:settings.madeDefault', { name: groupName(group, t) }) });
    reload();
  };

  const remove = async () => {
    const group = deleting;
    setDeleting(null);
    if (!group?.id) return;
    const response = await apiDelete(`/api/lifecycle-stage-groups/${group.id}`);
    if (response.error) return failed(response);
    toast({ title: t('lifecycle:settings.deleted', { name: groupName(group, t) }) });
    reload();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">{t('lifecycle:settings.title')}</h2>
          <p className="text-sm text-muted-foreground">{t('lifecycle:settings.description')}</p>
        </div>
        {canWrite && (
          <Button size="sm" onClick={() => openEditor(null)}>
            <Plus className="h-4 w-4 mr-1" /> {t('lifecycle:settings.addGroup')}
          </Button>
        )}
      </div>

      <Tabs value={entityType} onValueChange={(v) => setEntityType(v as LifecycleEntityType)}>
        <TabsList>
          {LIFECYCLE_ENTITY_TYPES.map((type) => (
            <TabsTrigger key={type} value={type}>
              {t(`lifecycle:entityType.${type}`)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {loading ? (
        <ListItemSkeleton count={2} height="h-16" className="space-y-2" />
      ) : error ? (
        <p className="text-sm text-destructive" role="alert">{error}</p>
      ) : groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('lifecycle:settings.empty')}</p>
      ) : (
        <ul className="space-y-3" aria-label={t('lifecycle:settings.groupList')}>
          {groups.map((group) => {
            const name = groupName(group, t);
            const editable = canWrite && Boolean(group.id);
            return (
              <li key={group.id ?? group.name} className="rounded-md border p-4 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{name}</span>
                  {group.is_default_for_type && (
                    <Badge variant="secondary" className="gap-1">
                      <Star className="h-3 w-3" /> {t('lifecycle:settings.default')}
                    </Badge>
                  )}
                  <div className="ml-auto flex gap-1">
                    {editable && !group.is_default_for_type && (
                      <Button size="sm" variant="ghost" onClick={() => makeDefault(group)}>
                        {t('lifecycle:settings.makeDefault')}
                      </Button>
                    )}
                    <Button
                      size="icon" variant="ghost" className="h-8 w-8"
                      onClick={() => openEditor(group)}
                      aria-label={t(
                        editable ? 'lifecycle:settings.edit' : 'lifecycle:settings.view', { name },
                      )}
                    >
                      {editable ? <Pencil className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </Button>
                    {editable && !group.is_default_for_type && (
                      <Button
                        size="icon" variant="ghost" className="h-8 w-8 text-destructive"
                        onClick={() => setDeleting(group)}
                        aria-label={t('lifecycle:settings.delete', { name })}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                </div>
                {group.description && (
                  <p className="text-sm text-muted-foreground">{groupDescription(group, t)}</p>
                )}
                <div className="flex flex-wrap gap-1">
                  {orderedStages(group).map((stage) => (
                    <StageBadge key={stage.key} stage={stage} />
                  ))}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <LifecycleStageGroupEditor
        open={editorOpen}
        onOpenChange={setEditorOpen}
        entityType={entityType}
        group={editing}
        readOnly={!canWrite || (editing !== null && !editing.id)}
        onSaved={(saved) => {
          setEditorOpen(false);
          toast({ title: t('lifecycle:settings.saved', { name: groupName(saved, t) }) });
          reload();
        }}
      />

      <AlertDialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('lifecycle:settings.deleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('lifecycle:settings.deleteDescription', {
                name: deleting ? groupName(deleting, t) : '',
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:actions.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={remove}>{t('common:actions.delete')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

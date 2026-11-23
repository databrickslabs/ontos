import React from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Tags, Pencil, RefreshCcw } from 'lucide-react';
import TagSelector from '@/components/ui/tag-selector';
import TagChip, { AssignedTag } from '@/components/ui/tag-chip';
import { ContentSkeleton } from '@/components/common/content-skeleton';
import { useApi } from '@/hooks/use-api';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/feature-access-levels';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from 'react-i18next';
import { ActionSpinner } from '@/components/ui/action-spinner';

// Stands in for the tags while they load (see ContentSkeleton)
const sampleTag = (id: string, name: string): AssignedTag => ({
  tag_id: id, tag_name: name, namespace_id: 'sample', namespace_name: 'default', status: 'active',
  fully_qualified_name: `default/${name}`, assigned_at: '2026-01-01T00:00:00Z',
});
const TAGS_SAMPLE: AssignedTag[] = [sampleTag('t1', 'sample-tag'), sampleTag('t2', 'pii'), sampleTag('t3', 'finance')];

interface Props {
  /** Stable identifier of the entity the tags are assigned to (e.g. a table's full path). */
  entityId: string;
  /** Polymorphic entity type understood by the tags backend (e.g. 'catalog-object'). */
  entityType: string;
}

/**
 * Surfaces the generic entity-tag assignment API
 * (GET/POST /api/entities/{entityType}/{entityId}/tags) so that a user can view
 * and apply tags to any polymorphic entity, including Unity Catalog objects in
 * the Catalog Commander Info panel.
 */
const EntityTagsPanel: React.FC<Props> = ({ entityId, entityType }) => {
  const { get, post, loading: saving } = useApi();
  const { toast } = useToast();
  const { t } = useTranslation('metadata');
  const { hasPermission } = usePermissions();
  const canEditTags = hasPermission('tags', FeatureAccessLevel.READ_WRITE);

  const [assignedTags, setAssignedTags] = React.useState<AssignedTag[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState<(string | AssignedTag)[]>([]);

  const fetchTags = React.useCallback(async () => {
    if (!entityId) return;
    try {
      setLoading(true);
      const resp = await get<AssignedTag[]>(`/api/entities/${entityType}/${encodeURIComponent(entityId)}/tags`);
      setAssignedTags(Array.isArray(resp.data) ? resp.data : []);
    } catch (e: any) {
      // A missing assignment is not an error; only surface real failures.
      setAssignedTags([]);
    } finally {
      setLoading(false);
    }
  }, [entityId, entityType, get]);

  React.useEffect(() => { fetchTags(); }, [fetchTags]);

  const startEditing = () => {
    setDraft(assignedTags.map(tag => tag.fully_qualified_name));
    setEditing(true);
  };

  const handleSave = async () => {
    try {
      // The backend accepts a list of FQN strings or {tag_fqn} objects.
      const payload = draft.map(tag => (typeof tag === 'string' ? { tag_fqn: tag } : { tag_fqn: tag.fully_qualified_name }));
      const resp = await post<AssignedTag[]>(`/api/entities/${entityType}/${encodeURIComponent(entityId)}/tags:set`, payload);
      if (resp.error) throw new Error(resp.error);
      setAssignedTags(Array.isArray(resp.data) ? resp.data : []);
      setEditing(false);
      toast({ title: t('tags.messages.saveSuccess') || 'Tags updated' });
    } catch (e: any) {
      toast({ title: t('tags.messages.saveFailed') || 'Failed to update tags', description: e.message, variant: 'destructive' });
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-medium flex items-center gap-2">
          <Tags className="h-5 w-5 text-primary" />
          {t('tags.title') || 'Tags'}
          <TooltipProvider>
            <div className="flex items-center gap-1 border rounded-md bg-muted/40 px-1 py-0.5 ml-1">
              {canEditTags && !editing && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" aria-label={t('tags.edit') || 'Edit tags'} onClick={startEditing}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('tags.edit') || 'Edit tags'}</TooltipContent>
                </Tooltip>
              )}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" aria-label={t('tags.refresh') || 'Refresh'} onClick={fetchTags} disabled={editing}>
                    <RefreshCcw className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('tags.refresh') || 'Refresh'}</TooltipContent>
              </Tooltip>
            </div>
          </TooltipProvider>
        </CardTitle>
        <CardDescription>{t('tags.description') || 'Apply governance tags to this object.'}</CardDescription>
      </CardHeader>
      <CardContent>
        {editing ? (
          <div className="space-y-3">
            <TagSelector
              value={draft}
              onChange={setDraft}
              placeholder={t('tags.placeholder') || 'Search and select tags...'}
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={handleSave} disabled={saving}>
                {saving && <ActionSpinner className="mr-1" />}
                {t('tags.save') || 'Save'}
              </Button>
              <Button size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saving}>
                {t('tags.cancel') || 'Cancel'}
              </Button>
            </div>
          </div>
        ) : (
          <ContentSkeleton
            loading={loading}
            empty={assignedTags.length === 0}
            emptyMessage={<div className="text-sm text-muted-foreground">{t('tags.noTags') || 'No tags applied.'}</div>}
          >
            <div className="flex flex-wrap gap-1">
              {(loading ? TAGS_SAMPLE : assignedTags).map(tag => (
                <TagChip key={tag.tag_id} tag={tag} size="sm" displayFormat="long" />
              ))}
            </div>
          </ContentSkeleton>
        )}
      </CardContent>
    </Card>
  );
};

export default EntityTagsPanel;

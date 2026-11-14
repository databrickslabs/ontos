import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import ConceptSelectDialog from '@/components/semantic/concept-select-dialog';
import LinkedConceptChips from '@/components/semantic/linked-concept-chips';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import type { EntitySemanticLink } from '@/types/semantic-link';

interface Props {
  /** AR version_family_id — links are family-scoped so they survive version bumps. */
  familyId: string;
}

/** Business Concepts this AR governs; feeds find_authority_for_concept. */
export default function ArConceptLinks({ familyId }: Props) {
  const { t } = useTranslation(['authority-resolution', 'common']);
  const { get, post, delete: del } = useApi();
  const { toast } = useToast();
  const [links, setLinks] = useState<EntitySemanticLink[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchLinks = useCallback(async () => {
    const { data } = await get<EntitySemanticLink[]>(
      `/api/semantic-links/entity/authority_relation/${encodeURIComponent(familyId)}`,
    );
    return Array.isArray(data) ? data : [];
  }, [get, familyId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const data = await fetchLinks();
      if (!cancelled) { setLinks(data); setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [fetchLinks]);

  const addIri = async (iri: string) => {
    const res = await post<EntitySemanticLink>('/api/semantic-links/', {
      entity_id: familyId, entity_type: 'authority_relation', iri,
    });
    if (res.error) {
      toast({ title: t('conceptLinks.failedLink'), description: res.error, variant: 'destructive' });
      return;
    }
    setDialogOpen(false);
    setLinks(await fetchLinks());
  };

  const removeLink = async (linkId: string) => {
    const res = await del(`/api/semantic-links/${linkId}`);
    if (res.error) {
      toast({ title: t('conceptLinks.failedUnlink'), description: res.error, variant: 'destructive' });
      return;
    }
    setLinks(await fetchLinks());
  };

  if (loading) {
    return (
      <div className="flex flex-wrap gap-2">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-6 w-24" />
        <Skeleton className="h-8 w-28" />
      </div>
    );
  }

  return (
    <>
      <LinkedConceptChips
        links={links}
        onRemove={removeLink}
        trailing={<Button size="sm" variant="outline" onClick={() => setDialogOpen(true)}>{t('conceptLinks.buttonAddConcept')}</Button>}
      />
      <ConceptSelectDialog isOpen={dialogOpen} onOpenChange={setDialogOpen} onSelect={addIri} />
    </>
  );
}

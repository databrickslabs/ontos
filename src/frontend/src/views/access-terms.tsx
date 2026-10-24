import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AlertCircle, FileSignature } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { DetailViewSkeleton } from '@/components/common/list-view-skeleton';
import AccessStatusBadge from '@/components/access-policies/access-status-badge';
import DutiesPanel from '@/components/access-policies/duties-panel';
import { describeConstraint, describeRef } from '@/components/access-policies/odrl-helpers';
import { useApi } from '@/hooks/use-api';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import type { AgreementForParty } from '@/types/access-policy';

/** A consumer's view of their Agreement: what it grants, the terms it binds, and the duties to fulfil. */
export default function AccessTerms() {
  const { agreementId } = useParams<{ agreementId: string }>();
  const { t } = useTranslation(['access-policies', 'common']);
  const { get } = useApi();
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((s) => s.setDynamicTitle);
  const [agreement, setAgreement] = useState<AgreementForParty | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const res = await get<AgreementForParty>(`/api/access-policies/agreements/${agreementId}`);
    setAgreement(res.data && !res.error ? res.data : null);
    setLoading(false);
  }, [agreementId, get]);

  useEffect(() => {
    setStaticSegments([{ label: t('access-policies:terms.myRequests'), path: '/my-requests' }]);
    setDynamicTitle(t('access-policies:terms.title'));
    load();
    return () => setDynamicTitle(null);
  }, [load, setStaticSegments, setDynamicTitle, t]);

  if (loading) return <DetailViewSkeleton />;
  if (!agreement) {
    return (
      <Alert variant="destructive" className="mt-6">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{t('access-policies:terms.notFound')}</AlertDescription>
      </Alert>
    );
  }

  const rules = (items: AgreementForParty['permissions']) =>
    items.map((r, i) => (
      <li key={i} className="text-sm">
        <span className="font-medium">{r.action}</span> · <span className="font-mono text-xs">{describeRef(r.target, () => null)}</span>
        {r.constraint.length > 0 && (
          <span className="text-muted-foreground"> — {r.constraint.map((c) => describeConstraint(c)).join(' AND ')}</span>
        )}
      </li>
    ));

  return (
    <div className="space-y-6 py-6">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <CardTitle className="flex items-center text-2xl font-bold">
                <FileSignature className="mr-3 h-7 w-7 shrink-0 text-primary" />
                <span className="truncate">{agreement.name}</span>
              </CardTitle>
              <CardDescription className="pt-1">{agreement.description}</CardDescription>
            </div>
            <AccessStatusBadge status={agreement.status} />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <div className="mb-1 text-sm font-medium">{t('access-policies:terms.grants')}</div>
            <ul className="list-inside list-disc space-y-1">{rules(agreement.permissions)}</ul>
          </div>
          {agreement.prohibitions.length > 0 && (
            <div>
              <div className="mb-1 text-sm font-medium">{t('access-policies:terms.prohibitions')}</div>
              <ul className="list-inside list-disc space-y-1">{rules(agreement.prohibitions)}</ul>
            </div>
          )}
          {agreement.obligations.length > 0 && (
            <div>
              <div className="mb-1 text-sm font-medium">{t('access-policies:terms.obligations')}</div>
              <ul className="list-inside list-disc space-y-1">{rules(agreement.obligations)}</ul>
            </div>
          )}
        </CardContent>
      </Card>
      <DutiesPanel agreementId={agreement.id} initial={agreement.duties} onChange={() => load()} />
    </div>
  );
}

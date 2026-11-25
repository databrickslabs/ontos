import DomainBadgeList from '@/components/ui/domain-badge-list';
import { Label } from '@/components/ui/label';
import type { DataProduct } from '@/types/data-product';
import { useDomains } from '@/hooks/use-domains';
import { useTranslation } from 'react-i18next';

interface ProductDomainBadgesProps {
  product: Pick<DataProduct, 'domain' | 'domain_ids' | 'primary_domain_id' | 'domains'>;
  onDomainClick: (domainId: string) => void;
}

export default function ProductDomainBadges({ product, onDomainClick }: ProductDomainBadgesProps) {
  const { t } = useTranslation(['data-products']);
  const { getDomainIdByName } = useDomains();
  // Older or partially migrated product payloads may carry only the primary domain name.
  const legacyDomainId = product.domain ? getDomainIdByName(product.domain) : undefined;
  const domainIds = product.domain_ids ?? (legacyDomainId ? [legacyDomainId] : []);
  const primaryDomainId = product.primary_domain_id ?? legacyDomainId ?? domainIds[0] ?? null;
  const hasDomains = Boolean(product.domains?.length || domainIds.length);

  return (
    <div className="flex min-w-0 items-start gap-2 md:col-span-2">
      <Label className="text-xs text-muted-foreground min-w-[4rem]">
        {t('data-products:form.fields.domains')}:
      </Label>
      {hasDomains ? (
        <DomainBadgeList
          domains={product.domains}
          domainIds={domainIds}
          primaryDomainId={primaryDomainId}
          onDomainClick={onDomainClick}
          maxVisible={4}
          className="w-full max-w-[20rem] min-w-0"
        />
      ) : product.domain ? (
        <span className="text-xs text-muted-foreground truncate">{product.domain}</span>
      ) : (
        <span className="text-xs text-muted-foreground">—</span>
      )}
    </div>
  );
}

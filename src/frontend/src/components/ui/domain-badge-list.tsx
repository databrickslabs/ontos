import React from 'react';
import { Star } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { useDomains } from '@/hooks/use-domains';
import { AssignedDomain } from '@/types/data-domain';

export interface DomainBadgeListProps {
  /** Assigned domain IDs (any order). The primary is rendered first with a star. */
  domainIds?: (string | null | undefined)[] | null;
  /** Which domain id is primary. */
  primaryDomainId?: string | null;
  /** Pre-resolved assigned domains (preferred when available — avoids a name lookup). */
  domains?: AssignedDomain[] | null;
  /** Optional click handler (e.g. navigate to the domain). */
  onDomainClick?: (domainId: string) => void;
  className?: string;
}

/**
 * Renders an entity's assigned data domains as badges, with the primary distinguished
 * (accent + star) and listed first (issue #520 story 12). Resolves names from the shared
 * `useDomains` cache when only IDs are supplied.
 */
const DomainBadgeList: React.FC<DomainBadgeListProps> = ({
  domainIds,
  primaryDomainId,
  domains,
  onDomainClick,
  className,
}) => {
  const { getDomainName } = useDomains();

  // Build a normalized [{id, name, isPrimary}] list, primary first.
  let entries: { id: string; name: string; isPrimary: boolean }[] = [];
  if (domains && domains.length > 0) {
    entries = domains
      .filter(d => d.domain_id)
      .map(d => ({
        id: d.domain_id,
        name: d.domain_name || getDomainName(d.domain_id) || d.domain_id,
        isPrimary: d.is_primary,
      }));
  } else if (domainIds && domainIds.length > 0) {
    entries = domainIds
      .filter((id): id is string => Boolean(id))
      .map(id => ({ id, name: getDomainName(id) || id, isPrimary: id === primaryDomainId }));
  }
  if (entries.length === 0) return null;

  // Primary first, then stable by name.
  entries.sort((a, b) => (a.isPrimary === b.isPrimary ? a.name.localeCompare(b.name) : a.isPrimary ? -1 : 1));

  return (
    <div className={cn('flex flex-wrap gap-1', className)}>
      {entries.map(({ id, name, isPrimary }) => (
        <Badge
          key={id}
          variant={isPrimary ? 'default' : 'secondary'}
          className={cn('gap-1', onDomainClick && 'cursor-pointer hover:opacity-80')}
          title={isPrimary ? `${name} (primary domain)` : name}
          onClick={onDomainClick ? (e) => { e.stopPropagation(); onDomainClick(id); } : undefined}
        >
          {isPrimary && <Star className="h-3 w-3 fill-current" />}
          <span className="truncate max-w-[10rem]">{name}</span>
        </Badge>
      ))}
    </div>
  );
};

export default DomainBadgeList;

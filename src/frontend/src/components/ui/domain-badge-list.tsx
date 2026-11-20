import React from 'react';
import { Star } from 'lucide-react';
import { Badge, badgeVariants } from '@/components/ui/badge';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
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
  /** Maximum badge slots to render. The final slot opens any remaining domains. */
  maxVisible?: number;
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
  maxVisible,
  className,
}) => {
  const { getDomainName } = useDomains();

  // Build a normalized [{id, name, isPrimary}] list, primary first.
  let entries: { id: string; name: string; isPrimary: boolean }[] = [];
  if (domains && domains.length > 0) {
    entries = domains
      .filter((d) => d.domain_id)
      .map((d) => ({
        id: d.domain_id,
        name: d.domain_name || getDomainName(d.domain_id) || d.domain_id,
        isPrimary: d.is_primary,
      }));
  } else if (domainIds && domainIds.length > 0) {
    entries = domainIds
      .filter((id): id is string => Boolean(id))
      .map((id) => ({ id, name: getDomainName(id) || id, isPrimary: id === primaryDomainId }));
  }
  if (entries.length === 0) return null;

  // Primary first, then stable by name.
  entries.sort((a, b) =>
    a.isPrimary === b.isPrimary ? a.name.localeCompare(b.name) : a.isPrimary ? -1 : 1
  );

  const hasOverflow = maxVisible !== undefined && maxVisible > 1 && entries.length > maxVisible;
  const visibleEntries = hasOverflow ? entries.slice(0, maxVisible - 1) : entries;
  const overflowEntries = hasOverflow ? entries.slice(maxVisible - 1) : [];

  const renderBadge = ({ id, name, isPrimary }: (typeof entries)[number], inPopover = false) => (
    <Badge
      key={id}
      variant={isPrimary ? 'default' : 'secondary'}
      className={cn(
        'min-w-0 gap-1',
        !inPopover && maxVisible && 'w-full',
        onDomainClick && 'cursor-pointer hover:opacity-80'
      )}
      title={isPrimary ? `${name} (primary domain)` : name}
      onClick={
        onDomainClick
          ? (e) => {
              e.stopPropagation();
              onDomainClick(id);
            }
          : undefined
      }
    >
      {isPrimary && <Star className="h-3 w-3 shrink-0 fill-current" />}
      <span className="min-w-0 truncate">{name}</span>
    </Badge>
  );

  return (
    <div className={cn(maxVisible ? 'grid grid-cols-2 gap-1' : 'flex flex-wrap gap-1', className)}>
      {visibleEntries.map((entry) => renderBadge(entry))}
      {hasOverflow && (
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              className={cn(badgeVariants({ variant: 'outline' }), 'w-full justify-center')}
              title={overflowEntries.map((entry) => entry.name).join(', ')}
            >
              +{overflowEntries.length}
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-64 p-2">
            <div className="flex max-h-60 flex-col gap-1 overflow-y-auto">
              {overflowEntries.map((entry) => renderBadge(entry, true))}
            </div>
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
};

export default DomainBadgeList;

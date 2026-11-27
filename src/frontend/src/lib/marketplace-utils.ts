import type { DataProduct } from '@/types/data-product';
import type { DataDomain } from '@/types/data-domain';

/**
 * Domain to centre the marketplace graph on when it opens (#1591): the selected domain
 * when exactly one is selected, else the nearest common ancestor of the selection (null
 * when the selected domains have no common ancestor). Returns null for an empty selection.
 */
export function graphFocusForSelection(
  selectedIds: string[],
  domains: Pick<DataDomain, 'id' | 'parent_id'>[],
): string | null {
  const byId = new Map(domains.map(d => [d.id, d]));
  const known = selectedIds.filter(id => byId.has(id));
  if (known.length === 0) return null;
  if (known.length === 1) return known[0];

  const chainOf = (id: string): string[] => {
    const chain: string[] = [];
    const seen = new Set<string>();
    let cur: string | null | undefined = id;
    while (cur && byId.has(cur) && !seen.has(cur)) {
      seen.add(cur);
      chain.push(cur); // the domain itself counts as its own ancestor
      cur = byId.get(cur)!.parent_id;
    }
    return chain;
  };

  const [first, ...rest] = known.map(chainOf);
  const restSets = rest.map(c => new Set(c));
  return first.find(id => restSets.every(s => s.has(id))) ?? null;
}

/** ids of the root domains (no parent), in the given order */
export function rootDomainIds(domains: Pick<DataDomain, 'id' | 'parent_id'>[]): string[] {
  return domains.filter(d => !d.parent_id).map(d => d.id);
}

/**
 * Who to show as the owner of a marketplace card: a person's display name (plus role when
 * known), else the owning team. Never an email or an email prefix. Null when nothing
 * readable resolves.
 */
export function productOwnerLabel(product: DataProduct): string | null {
  const looksLikeEmail = (v: string) => v.includes('@');
  const members = product.team?.members ?? [];
  const person =
    members.find(m => m.role?.toLowerCase().includes('owner') && m.name?.trim()) ??
    members.find(m => m.name?.trim());
  const personName = person?.name?.trim();
  if (personName && !looksLikeEmail(personName)) {
    const role = person?.role?.trim();
    return role && !looksLikeEmail(role) ? `${personName} (${role})` : personName;
  }
  const team = product.owner_team_name?.trim() || product.team?.name?.trim();
  if (team && !looksLikeEmail(team)) return team;
  return null;
}

export type TrustSignal =
  | { kind: 'retiring'; replacementId: string | null }
  | { kind: 'certified' }
  | { kind: 'preview' }
  | null;

/**
 * The single trust signal a card shows (#1600): Retiring wins over Certified, Certified over
 * Preview; an active, uncertified product shows none.
 */
export function productTrustSignal(product: DataProduct): TrustSignal {
  const status = (product.status || '').toLowerCase();
  if (status === 'deprecated' || status === 'retired') {
    return { kind: 'retiring', replacementId: product.replacement_product_id ?? null };
  }
  const level = Math.max(
    product.certification_level ?? 0,
    product.inherited_certification_level ?? 0,
  );
  if (level > 0) return { kind: 'certified' };
  if (status && status !== 'active') return { kind: 'preview' };
  return null;
}

/** Index ids of products in `/api/search` results (`product::<uuid>`), in rank order. */
export function productIdsFromSearch(items: { id?: string; type?: string }[]): string[] {
  const ids: string[] = [];
  for (const item of items) {
    if (item?.type !== 'data-product' || !item.id?.startsWith('product::')) continue;
    ids.push(item.id.slice('product::'.length));
  }
  return ids;
}

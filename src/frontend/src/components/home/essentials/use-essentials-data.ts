import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  features,
  isHiddenInNav,
  type FeatureConfig,
  type FeatureMaturity,
} from '@/config/features';
import { FeatureAccessLevel } from '@/types/settings';
import {
  ReviewRequestStatus,
  ReviewedAssetStatus,
  type DataAssetReviewRequest,
} from '@/types/data-asset-review';

/**
 * Data for the Essentials home. Every call goes to an existing endpoint:
 * - GET /api/assets?limit=1            total assets (Understand)
 * - GET /api/data-asset-reviews        review requests (Trust, Publish, Maintain)
 * - GET /api/assets?owned_by_me=true   the user's assets, one page at a time (Publish)
 * - GET /api/access-grants/my-requests the user's access requests (Maintain)
 */

/** Review requests read to compute statuses (the endpoint pages at 100 by default). */
export const REVIEWS_LIMIT = 500;

const OPEN_REVIEW_STATUSES: string[] = [
  ReviewRequestStatus.QUEUED,
  ReviewRequestStatus.IN_REVIEW,
  ReviewRequestStatus.NEEDS_REVIEW,
];

export interface OwnedAsset {
  id: string;
  name: string;
  location?: string | null;
  description?: string | null;
}

export interface AssetGaps {
  asset: OwnedAsset;
  missingDescription: boolean;
  /** `null` when the user can't read reviews, so the review state is unknown. */
  missingReview: boolean | null;
}

export interface AccessRequestItem {
  id: string;
  entity_name?: string | null;
  entity_id: string;
  entity_type: string;
  status: string;
  created_at: string;
}

interface Loadable<T> {
  data: T;
  loading: boolean;
}

/**
 * Lookups of the features the journey home may link to: `shown` = in the menus (maturity
 * filter and not hidden by the user's roles, #1325); `feature` = shown and readable with the
 * sidebar's check.
 */
export function useEssentialsFeature(
  allowedMaturities: FeatureMaturity[],
  hiddenFeatures: ReadonlySet<string>,
  hasPermission: (featureId: string, level: FeatureAccessLevel) => boolean,
) {
  return useMemo(() => {
    const shown = (id: string): FeatureConfig | null => {
      const f = features.find((x) => x.id === id);
      return f && allowedMaturities.includes(f.maturity) && !isHiddenInNav(f, hiddenFeatures)
        ? f
        : null;
    };
    const feature = (
      id: string,
      level: FeatureAccessLevel = FeatureAccessLevel.READ_ONLY,
    ): FeatureConfig | null => {
      const f = shown(id);
      return f && hasPermission(f.permissionId || f.id, level) ? f : null;
    };
    return { shown, feature };
  }, [allowedMaturities, hiddenFeatures, hasPermission]);
}

async function getJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/**
 * Run `load(key)` whenever `key` changes; `key === null` means disabled. The result is
 * kept with its key, so a stale or disabled key reads as `fallback` (loading while pending).
 */
function useLoad<T>(
  key: string | null,
  load: (key: string) => Promise<T | null>,
  fallback: T,
): Loadable<T> {
  const [result, setResult] = useState<{ key: string; data: T } | null>(null);
  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    load(key).then((data) => {
      if (!cancelled) setResult({ key, data: data ?? fallback });
    });
    return () => {
      cancelled = true;
    };
    // `load` and `fallback` are constants per call site.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const current = key !== null && result?.key === key;
  return { data: current ? result.data : fallback, loading: key !== null && !current };
}

function useJson<T>(url: string | null, fallback: T): Loadable<T> {
  return useLoad<T>(url, getJson, fallback);
}

const EMPTY_REVIEWS: DataAssetReviewRequest[] = [];
const EMPTY_REQUESTS: AccessRequestItem[] = [];

export function useAssetTotal(enabled: boolean): Loadable<number | null> {
  const res = useJson<{ total?: number } | null>(enabled ? '/api/assets?limit=1' : null, null);
  return { data: res.data?.total ?? null, loading: res.loading };
}

/** Review requests; the endpoint returns a list, or `{items: []}` when there are none. */
export function useReviewRequests(enabled: boolean): Loadable<DataAssetReviewRequest[]> {
  const res = useJson<DataAssetReviewRequest[] | { items?: DataAssetReviewRequest[] }>(
    enabled ? `/api/data-asset-reviews?limit=${REVIEWS_LIMIT}` : null,
    EMPTY_REVIEWS,
  );
  const data = Array.isArray(res.data) ? res.data : res.data?.items ?? EMPTY_REVIEWS;
  return { data, loading: res.loading };
}

export function useMyAccessRequests(enabled: boolean): Loadable<AccessRequestItem[]> {
  const res = useJson<{ requests?: AccessRequestItem[] }>(
    enabled ? '/api/access-grants/my-requests' : null,
    { requests: EMPTY_REQUESTS },
  );
  return { data: res.data?.requests ?? EMPTY_REQUESTS, loading: res.loading };
}

interface AssetPage {
  items: OwnedAsset[];
  total: number;
}

const ownedPageUrl = (skip: number, limit: number) =>
  `/api/assets?owned_by_me=true&skip=${skip}&limit=${limit}`;

export interface OwnedAssets extends Loadable<OwnedAsset[]> {
  total: number;
  /** More pages exist on the server (`skip + limit < total`). */
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => void;
}

/**
 * The assets the user owns, `pageSize` at a time, from one paginated call. A new page
 * size starts over from the first page.
 */
export function useOwnedAssets(enabled: boolean, pageSize: number): OwnedAssets {
  const key = enabled ? ownedPageUrl(0, pageSize) : null;
  const first = useJson<AssetPage | null>(key, null);
  const [more, setMore] = useState<{ key: string; items: OwnedAsset[]; loading: boolean }>();
  const extra = key && more?.key === key ? more : undefined;
  const items = useMemo(
    () => [...(first.data?.items ?? []), ...(extra?.items ?? [])],
    [first.data, extra],
  );
  const total = first.data?.total ?? 0;
  const loadingMore = !!extra?.loading;

  const loadMore = useCallback(() => {
    if (!key || loadingMore) return;
    const skip = items.length;
    const keep = (m?: { key: string; items: OwnedAsset[] }) => (m?.key === key ? m.items : []);
    setMore((m) => ({ key, items: keep(m), loading: true }));
    getJson<AssetPage>(ownedPageUrl(skip, pageSize)).then((page) =>
      setMore((m) => ({ key, items: [...keep(m), ...(page?.items ?? [])], loading: false })),
    );
  }, [key, loadingMore, items.length, pageSize]);

  return {
    data: items,
    loading: first.loading,
    total,
    hasMore: !first.loading && items.length < total,
    loadingMore,
    loadMore,
  };
}

/** Count of reviewed assets per status, across all review requests. */
export function reviewStatusCounts(
  reviews: DataAssetReviewRequest[],
): Record<ReviewedAssetStatus, number> {
  const counts = {
    [ReviewedAssetStatus.APPROVED]: 0,
    [ReviewedAssetStatus.PENDING]: 0,
    [ReviewedAssetStatus.NEEDS_CLARIFICATION]: 0,
    [ReviewedAssetStatus.REJECTED]: 0,
  };
  reviews.forEach((r) =>
    (r.assets || []).forEach((a) => {
      if (a.status in counts) counts[a.status] += 1;
    }),
  );
  return counts;
}

/** Latest reviewed assets (by update time), one row per asset FQN. */
export function latestReviewedAssets(
  reviews: DataAssetReviewRequest[],
  limit: number,
): { fqn: string; status: ReviewedAssetStatus; requestId: string }[] {
  const byFqn = new Map<string, { fqn: string; status: ReviewedAssetStatus;
    requestId: string; at: string }>();
  reviews.forEach((r) =>
    (r.assets || []).forEach((a) => {
      const prev = byFqn.get(a.asset_fqn);
      const at = a.updated_at || r.updated_at || '';
      if (!prev || at > prev.at) {
        byFqn.set(a.asset_fqn, { fqn: a.asset_fqn, status: a.status, requestId: r.id, at });
      }
    }),
  );
  return Array.from(byFqn.values())
    .sort((a, b) => b.at.localeCompare(a.at))
    .slice(0, limit)
    .map(({ fqn, status, requestId }) => ({ fqn, status, requestId }));
}

/** Open review requests the user asked for or has to review. */
export function myOpenReviews(
  reviews: DataAssetReviewRequest[],
  email: string | null | undefined,
): DataAssetReviewRequest[] {
  if (!email) return [];
  const me = email.toLowerCase();
  return reviews.filter(
    (r) =>
      OPEN_REVIEW_STATUSES.includes(r.status) &&
      [r.requester_email, r.reviewer_email].some((e) => (e || '').toLowerCase() === me),
  );
}

/**
 * Owned assets with a documentation or review gap. An asset counts as reviewed when its
 * location (UC full name) or name appears in a review request.
 */
export function assetGaps(
  assets: OwnedAsset[],
  reviews: DataAssetReviewRequest[] | null,
): AssetGaps[] {
  const reviewed = reviews
    ? new Set(reviews.flatMap((r) => (r.assets || []).map((a) => a.asset_fqn.toLowerCase())))
    : null;
  return assets
    .map((asset) => ({
      asset,
      missingDescription: !asset.description?.trim(),
      missingReview: reviewed
        ? ![asset.location, asset.name].some((k) => !!k && reviewed.has(k.toLowerCase()))
        : null,
    }))
    .filter((g) => g.missingDescription || g.missingReview === true);
}

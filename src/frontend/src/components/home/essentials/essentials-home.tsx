import { type ReactNode, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  BookOpen,
  ClipboardCheck,
  Inbox,
  Search,
  ShieldCheck,
  TrendingUp,
  UploadCloud,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import SearchBar from '@/components/ui/search-bar';
import { UnityCatalogLogo } from '@/components/unity-catalog-logo';
import ConnectedOverviewTile from '@/components/home/connected-overview-tile';
import OverviewTile from '@/components/home/overview-tile';
import RequiredActionsSection from '@/components/home/required-actions-section';
import CreateReviewRequestDialog from
  '@/components/data-asset-reviews/create-review-request-dialog';
import { useNavHiddenFeatures } from '@/hooks/use-nav-hidden-features';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { useApi } from '@/hooks/use-api';
import {
  PUBLISH_PAGE_SIZES,
  useEssentialsHomePreferencesStore,
} from '@/stores/essentials-home-preferences-store';
import { usePermissions } from '@/stores/permissions-store';
import { useUserStore } from '@/stores/user-store';
import { useUICustomizationStore } from '@/stores/ui-customization-store';
import { tileRegistry } from '@/tiles';
import { FeatureAccessLevel } from '@/types/settings';
import { ReviewedAssetStatus } from '@/types/data-asset-review';
import {
  assetGaps,
  latestReviewedAssets,
  myOpenReviews,
  reviewStatusCounts,
  useAssetTotal,
  useEssentialsFeature,
  useMyAccessRequests,
  useOwnedAssets,
  useOwnedBelowFirstLevel,
  useReviewRequests,
  type OwnedAsset,
} from './use-essentials-data';

export interface EssentialsHomeProps {
  /**
   * Seam for the asset maturity badge (#1316): rendered next to each of the user's assets
   * in Publish. Not passed yet, so no badge is shown.
   */
  renderAssetBadge?: (asset: OwnedAsset) => ReactNode;
}

const LIST_LIMIT = 5;

const STATUS_ORDER: ReviewedAssetStatus[] = [
  ReviewedAssetStatus.APPROVED,
  ReviewedAssetStatus.PENDING,
  ReviewedAssetStatus.NEEDS_CLARIFICATION,
  ReviewedAssetStatus.REJECTED,
];

const STATUS_VARIANT: Record<ReviewedAssetStatus, 'default' | 'secondary' | 'destructive'> = {
  [ReviewedAssetStatus.APPROVED]: 'default',
  [ReviewedAssetStatus.PENDING]: 'secondary',
  [ReviewedAssetStatus.NEEDS_CLARIFICATION]: 'secondary',
  [ReviewedAssetStatus.REJECTED]: 'destructive',
};

interface JourneyCardProps {
  id: string;
  icon: ReactNode;
  title: string;
  description: string;
  className?: string;
  children: ReactNode;
}

function JourneyCard({ id, icon, title, description, className, children }: JourneyCardProps) {
  return (
    <Card className={`h-full ${className ?? ''}`} data-testid={`essentials-section-${id}`}>
      <CardHeader>
        <div className="flex items-center gap-2">
          <span className="text-primary">{icon}</span>
          <CardTitle className="text-lg">{title}</CardTitle>
        </div>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

/**
 * Journey home (#1347), shown for the roles whose home sections include JOURNEY: Find,
 * Understand and Trust for data consumers; Publish and Maintain for producers. Each section
 * shows only when the user can read what it needs, and links only to features the user's
 * menus show (maturity filter and the role's "show in navigation" flag, #1325).
 */
export default function EssentialsHome({ renderAssetBadge }: EssentialsHomeProps) {
  const { t } = useTranslation(['home', 'data-asset-reviews']);
  const appName = useUICustomizationStore((s) => s.getAppName());
  const { hasPermission } = usePermissions();
  const allowedMaturities = useFeatureVisibilityStore((s) => s.allowedMaturities);
  const hiddenFeatures = useNavHiddenFeatures();
  const email = useUserStore((s) => s.userInfo?.email);
  const api = useApi();
  const [reviewDialogOpen, setReviewDialogOpen] = useState(false);

  const { shown, feature } = useEssentialsFeature(allowedMaturities, hiddenFeatures, hasPermission);
  // Search has no role permission of its own (the roles API refuses it as a hidden id), and
  // its results are filtered per user, so the search box only follows the maturity filter.
  const searchShown = !!shown('search');
  const catalog = feature('data-catalog');
  const assets = feature('assets');
  const assetsWrite = feature('assets', FeatureAccessLevel.READ_WRITE);
  const concepts = feature('concepts');
  const reviews = feature('data-asset-reviews');
  const reviewsWrite = feature('data-asset-reviews', FeatureAccessLevel.READ_WRITE);
  // My Requests has no feature permission of its own; its API needs access-grants read.
  const myRequests = hasPermission('access-grants', FeatureAccessLevel.READ_ONLY)
    ? shown('my-requests')
    : null;

  const assetTotal = useAssetTotal(!!assets);
  const reviewList = useReviewRequests(!!reviews);
  const pageSize = useEssentialsHomePreferencesStore((s) => s.publishPageSize);
  const setPageSize = useEssentialsHomePreferencesStore((s) => s.setPublishPageSize);
  const owned = useOwnedAssets(!!assetsWrite, pageSize);
  const belowFirst = useOwnedBelowFirstLevel(!!assetsWrite);
  const accessRequests = useMyAccessRequests(!!myRequests);

  const counts = useMemo(() => reviewStatusCounts(reviewList.data), [reviewList.data]);
  const latest = useMemo(
    () => latestReviewedAssets(reviewList.data, LIST_LIMIT), [reviewList.data],
  );
  const gaps = useMemo(
    () => assetGaps(owned.data, reviews ? reviewList.data : null),
    [owned.data, reviews, reviewList.data],
  );
  const openReviews = useMemo(
    () => myOpenReviews(reviewList.data, email), [reviewList.data, email],
  );
  const pendingRequests = useMemo(
    () => accessRequests.data.filter((r) => r.status === 'pending'), [accessRequests.data],
  );

  const conceptsTile = concepts ? tileRegistry['semantic-models'] : null;
  const showFind = searchShown || !!catalog;
  const showUnderstand = !!assets || !!conceptsTile;
  const showTrust = !!reviews;
  const statusLabel = (s: string) => t(`data-asset-reviews:status.${s}`);
  const catalogLink = (fqn: string) =>
    catalog ? `${catalog.path}/${encodeURIComponent(fqn)}` : null;

  return (
    <div data-testid="essentials-home">
      <div className="max-w-2xl mx-auto text-center mb-8">
        <div className="flex items-center justify-center mb-4">
          <UnityCatalogLogo className="h-16 w-16" />
          <h1 className="text-4xl font-bold ml-2">{t('home:title', { appName })}</h1>
        </div>
        <p className="text-lg text-muted-foreground">{t('home:essentials.tagline')}</p>
      </div>

      {(showFind || showUnderstand || showTrust) && (
        <section className="mb-8" data-testid="essentials-journey-consumer">
          <h2 className="text-2xl font-semibold mb-1">{t('home:essentials.consumer.title')}</h2>
          <p className="text-muted-foreground mb-4">
            {t('home:essentials.consumer.description')}
          </p>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {showFind && (
              <JourneyCard
                id="find"
                className="lg:col-span-2"
                icon={<Search className="h-5 w-5" />}
                title={t('home:essentials.find.title')}
                description={t('home:essentials.find.description')}
              >
                {searchShown && (
                  <SearchBar variant="large" placeholder={t('home:essentials.find.placeholder')} />
                )}
                {catalog && (
                  <Button asChild variant="outline" size="sm">
                    <Link to={catalog.path}>
                      <BookOpen className="h-4 w-4 mr-2" />
                      {t('home:essentials.find.browseCatalog')}
                    </Link>
                  </Button>
                )}
              </JourneyCard>
            )}

            {showUnderstand && (
              <JourneyCard
                id="understand"
                icon={<BookOpen className="h-5 w-5" />}
                title={t('home:essentials.understand.title')}
                description={t('home:essentials.understand.description')}
              >
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {assets && (
                    <OverviewTile
                      icon={<assets.icon className="h-4 w-4" />}
                      title={t('home:essentials.understand.assets')}
                      value={assetTotal.data ?? '-'}
                      loading={assetTotal.loading}
                      error={null}
                      link={assets.path}
                      description={t('home:essentials.understand.assetsDescription')}
                    />
                  )}
                  {conceptsTile && (
                    <ConnectedOverviewTile tile={{ ...conceptsTile, link: concepts!.path }} />
                  )}
                </div>
              </JourneyCard>
            )}

            {reviews && (
              <JourneyCard
                id="trust"
                icon={<ShieldCheck className="h-5 w-5" />}
                title={t('home:essentials.trust.title')}
                description={t('home:essentials.trust.description')}
              >
                <div className="flex flex-wrap gap-2" data-testid="essentials-trust-counts">
                  {STATUS_ORDER.map((s) => (
                    <Badge key={s} variant={counts[s] > 0 ? STATUS_VARIANT[s] : 'outline'}>
                      {statusLabel(s)}: {counts[s]}
                    </Badge>
                  ))}
                </div>
                {reviewList.loading ? null : latest.length === 0 ? (
                  <Empty>{t('home:essentials.trust.empty')}</Empty>
                ) : (
                  <ul className="space-y-1 text-sm">
                    {latest.map((a) => {
                      const href = catalogLink(a.fqn);
                      return (
                        <li key={a.fqn} className="flex items-center justify-between gap-2">
                          {href ? (
                            <Link to={href} className="truncate font-mono hover:underline">
                              {a.fqn}
                            </Link>
                          ) : (
                            <span className="truncate font-mono">{a.fqn}</span>
                          )}
                          <Badge variant={STATUS_VARIANT[a.status]}>{statusLabel(a.status)}</Badge>
                        </li>
                      );
                    })}
                  </ul>
                )}
                <Link to={reviews.path} className="text-sm text-primary hover:underline">
                  {t('home:essentials.trust.openReviews')}
                </Link>
              </JourneyCard>
            )}
          </div>
        </section>
      )}

      <section className="mb-8" data-testid="essentials-journey-producer">
        <h2 className="text-2xl font-semibold mb-1">{t('home:essentials.producer.title')}</h2>
        <p className="text-muted-foreground mb-4">{t('home:essentials.producer.description')}</p>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {assetsWrite && (
            <JourneyCard
              id="publish"
              icon={<UploadCloud className="h-5 w-5" />}
              title={t('home:essentials.publish.title')}
              description={t('home:essentials.publish.description')}
            >
              {owned.loading ? null : owned.data.length === 0 ? (
                <Empty>{t('home:essentials.publish.noAssets')}</Empty>
              ) : gaps.length === 0 ? (
                <Empty>
                  {owned.hasMore
                    ? t('home:essentials.publish.noGapsLoaded')
                    : t('home:essentials.publish.allDone')}
                </Empty>
              ) : (
                <ul className="space-y-2 text-sm" data-testid="essentials-publish-gaps">
                  {gaps.map((g) => (
                    <li key={g.asset.id} className="flex flex-wrap items-center gap-2">
                      <Link
                        to={`${assetsWrite.path}/${g.asset.id}`}
                        className="font-medium hover:underline"
                      >
                        {g.asset.name}
                      </Link>
                      {renderAssetBadge?.(g.asset)}
                      {g.missingDescription && (
                        <Badge variant="outline">
                          {t('home:essentials.publish.noDescription')}
                        </Badge>
                      )}
                      {g.missingReview && (
                        <Badge variant="outline">{t('home:essentials.publish.noReview')}</Badge>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {owned.total > 0 && (
                <div className="flex flex-wrap items-center gap-3 text-sm"
                  data-testid="essentials-publish-paging">
                  <span className="text-muted-foreground">
                    {t('home:essentials.publish.more', {
                      shown: owned.data.length, total: owned.total,
                    })}
                  </span>
                  {owned.hasMore && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={owned.loadingMore}
                      onClick={owned.loadMore}
                    >
                      {t('home:essentials.publish.loadMore')}
                    </Button>
                  )}
                  <label className="ml-auto flex items-center gap-2 text-muted-foreground">
                    {t('home:essentials.publish.pageSize')}
                    <Select
                      value={String(pageSize)}
                      onValueChange={(v) => setPageSize(Number(v))}
                    >
                      <SelectTrigger
                        className="h-8 w-[72px]"
                        aria-label={t('home:essentials.publish.pageSize')}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {PUBLISH_PAGE_SIZES.map((n) => (
                          <SelectItem key={n} value={String(n)}>{n}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                </div>
              )}
              {reviewsWrite && (
                <Button size="sm" onClick={() => setReviewDialogOpen(true)}>
                  <ClipboardCheck className="h-4 w-4 mr-2" />
                  {t('home:essentials.publish.requestReview')}
                </Button>
              )}
            </JourneyCard>
          )}

          {assetsWrite && (
            <JourneyCard
              id="maturity"
              icon={<TrendingUp className="h-5 w-5" />}
              title={t('home:essentials.maturity.title')}
              description={t('home:essentials.maturity.description')}
            >
              {belowFirst.loading ? null : (
                <>
                  <p className="text-3xl font-bold" data-testid="essentials-maturity-count">
                    {belowFirst.data?.total ?? 0}
                  </p>
                  {!belowFirst.data?.items.length ? (
                    <Empty>{t('home:essentials.maturity.empty')}</Empty>
                  ) : (
                    <ul className="space-y-1 text-sm" data-testid="essentials-maturity-list">
                      {belowFirst.data.items.map((a) => (
                        <li key={a.id} className="truncate">
                          <Link
                            to={`${assetsWrite.path}/${a.id}`}
                            className="font-medium hover:underline"
                          >
                            {a.name}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                  {(belowFirst.data?.total ?? 0) > (belowFirst.data?.items.length ?? 0) && (
                    <Empty>
                      {t('home:essentials.maturity.more', {
                        shown: belowFirst.data!.items.length, total: belowFirst.data!.total,
                      })}
                    </Empty>
                  )}
                </>
              )}
            </JourneyCard>
          )}

          <JourneyCard
            id="maintain"
            icon={<Inbox className="h-5 w-5" />}
            title={t('home:essentials.maintain.title')}
            description={t('home:essentials.maintain.description')}
          >
            {myRequests && (
              <div data-testid="essentials-maintain-requests">
                <h3 className="text-sm font-semibold mb-1">
                  {t('home:essentials.maintain.myRequests', { count: pendingRequests.length })}
                </h3>
                {!accessRequests.loading && pendingRequests.length === 0 ? (
                  <Empty>{t('home:essentials.maintain.noRequests')}</Empty>
                ) : (
                  <ul className="space-y-1 text-sm">
                    {pendingRequests.slice(0, LIST_LIMIT).map((r) => (
                      <li key={r.id} className="truncate">{r.entity_name || r.entity_id}</li>
                    ))}
                  </ul>
                )}
                <Link to={myRequests.path} className="text-sm text-primary hover:underline">
                  {t('home:essentials.maintain.openMyRequests')}
                </Link>
              </div>
            )}
            {reviews && (
              <div data-testid="essentials-maintain-reviews">
                <h3 className="text-sm font-semibold mb-1">
                  {t('home:essentials.maintain.myReviews', { count: openReviews.length })}
                </h3>
                {!reviewList.loading && openReviews.length === 0 ? (
                  <Empty>{t('home:essentials.maintain.noReviews')}</Empty>
                ) : (
                  <ul className="space-y-1 text-sm">
                    {openReviews.slice(0, LIST_LIMIT).map((r) => (
                      <li key={r.id} className="flex items-center justify-between gap-2">
                        <Link
                          to={`${reviews.path}/${r.id}`}
                          className="truncate hover:underline"
                        >
                          {r.title || r.id}
                        </Link>
                        <Badge variant="secondary">{statusLabel(r.status)}</Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {!myRequests && !reviews && <Empty>{t('home:essentials.maintain.nothing')}</Empty>}
          </JourneyCard>
        </div>

        <Card className="mt-4" data-testid="essentials-approvals">
          <div className="px-6 py-4 border-b bg-muted/30">
            <h3 className="font-semibold text-sm">{t('home:myActions.approvals')}</h3>
          </div>
          <CardContent className="p-0 max-h-[400px] overflow-auto">
            <RequiredActionsSection />
          </CardContent>
        </Card>
      </section>

      {reviewDialogOpen && (
        <CreateReviewRequestDialog
          isOpen={reviewDialogOpen}
          onOpenChange={setReviewDialogOpen}
          api={api}
          onSubmitSuccess={() => setReviewDialogOpen(false)}
        />
      )}
    </div>
  );
}

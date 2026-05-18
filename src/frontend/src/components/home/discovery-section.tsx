import { useEffect, useMemo, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Loader2, Database, BoxSelect, Star, AlertCircle, Info, Bell } from 'lucide-react';
import { Link } from 'react-router-dom';
import EntityInfoDialog from '@/components/metadata/entity-info-dialog';
import SubscribeDialog from '@/components/data-products/subscribe-dialog';
import ApprovalWizardDialog from '@/components/workflows/approval-wizard-dialog';
import { useDomains } from '@/hooks/use-domains';
import { type DataProduct } from '@/types/data-product';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { DataDomain } from '@/types/data-domain';
import { DataDomainMiniGraph } from '@/components/data-domains/data-domain-mini-graph';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { useApprovalWizardTrigger } from '@/hooks/use-approval-wizard-trigger';
import { Badge } from '@/components/ui/badge';

interface DiscoverySectionProps {
  maxItems?: number;
}

export default function DiscoverySection({ maxItems = 12 }: DiscoverySectionProps) {
  const { t } = useTranslation('home');
  const { domains, loading: domainsLoading, getDomainName } = useDomains();
  const [selectedDomainId, setSelectedDomainId] = useState<string | null>(null);
  const [selectedDomainDetails, setSelectedDomainDetails] = useState<DataDomain | null>(null);
  const [domainLoading, setDomainLoading] = useState<boolean>(false);
  const [domainError, setDomainError] = useState<string | null>(null);
  const [exactMatchesOnly, setExactMatchesOnly] = useState<boolean>(false);
  const [matchSets, setMatchSets] = useState<{ ids: Set<string>; namesLower: Set<string> } | null>(null);
  const [graphFadeIn, setGraphFadeIn] = useState<boolean>(false);
  const [allProducts, setAllProducts] = useState<DataProduct[]>([]);
  const [productsLoading, setProductsLoading] = useState<boolean>(false);
  const [productsError, setProductsError] = useState<string | null>(null);
  const [infoProductId, setInfoProductId] = useState<string | null>(null);
  const [infoProductTitle, setInfoProductTitle] = useState<string | undefined>(undefined);
  
  // Subscribed products state
  const [subscribedProducts, setSubscribedProducts] = useState<DataProduct[]>([]);
  const [subscribedProductIds, setSubscribedProductIds] = useState<Set<string>>(new Set());
  const [subscribedLoading, setSubscribedLoading] = useState<boolean>(false);
  const [_subscribedError, setSubscribedError] = useState<string | null>(null);

  // Subscription dialog state
  const [selectedProduct, setSelectedProduct] = useState<DataProduct | null>(null);
  const [subscribeDialogOpen, setSubscribeDialogOpen] = useState(false);
  const [subscriptionWizardOpen, setSubscriptionWizardOpen] = useState(false);
  const [subscriptionWorkflowId, setSubscriptionWorkflowId] = useState<string | null>(null);

  const { lookupWorkflowId } = useApprovalWizardTrigger();

  useEffect(() => {
    const loadProducts = async () => {
      try {
        setProductsLoading(true);
        // Fetch only published (ACTIVE) products for marketplace discovery
        const resp = await fetch('/api/data-products/published');
        if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
        const data = await resp.json();
        setAllProducts(Array.isArray(data) ? data : []);
        setProductsError(null);
      } catch (e: any) {
        setProductsError(e.message || t('discoverySection.error'));
        setAllProducts([]);
      } finally {
        setProductsLoading(false);
      }
    };
    loadProducts();
  }, []);

  // Fetch user's subscribed products
  const loadSubscribedProducts = useCallback(async () => {
    try {
      setSubscribedLoading(true);
      const resp = await fetch('/api/data-products/my-subscriptions');
      if (!resp.ok) {
        if (resp.status === 401) {
          // Not authenticated, silently skip
          setSubscribedProducts([]);
          setSubscribedProductIds(new Set());
          return;
        }
        throw new Error(`HTTP error! status: ${resp.status}`);
      }
      const data = await resp.json();
      const products = Array.isArray(data) ? data : [];
      setSubscribedProducts(products);
      setSubscribedProductIds(new Set(products.map((p: DataProduct) => p.id).filter(Boolean)));
      setSubscribedError(null);
    } catch (e: any) {
      console.warn('Failed to fetch subscribed products:', e);
      setSubscribedError(null); // Don't show error, just hide section
      setSubscribedProducts([]);
      setSubscribedProductIds(new Set());
    } finally {
      setSubscribedLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSubscribedProducts();
  }, [loadSubscribedProducts]);

  // Choose a sensible default domain (prefer a domain named "Core")
  useEffect(() => {
    if (!domainsLoading && domains && domains.length > 0 && !selectedDomainId) {
      const core = domains.find(d => d.name.toLowerCase() === 'core');
      if (core) {
        setSelectedDomainId(core.id);
      }
    }
  }, [domainsLoading, domains, selectedDomainId]);

  // Fetch full domain details via API (includes children_info needed for graph)
  const loadDomainDetails = useCallback(async (domainId: string) => {
    try {
      setDomainLoading(true);
      setDomainError(null);
      const resp = await fetch(`/api/data-domains/${domainId}`);
      if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
      const data: DataDomain = await resp.json();
      setSelectedDomainDetails(data);
    } catch (e: any) {
      setDomainError(e.message || t('discoverySection.error'));
      setSelectedDomainDetails(null);
    } finally {
      setDomainLoading(false);
    }
  }, [t]);

  // Load selected domain details whenever selection changes
  useEffect(() => {
    if (selectedDomainId) {
      loadDomainDetails(selectedDomainId);
    } else {
      setSelectedDomainDetails(null);
    }
  }, [selectedDomainId, loadDomainDetails]);

  // Subtle fade-in of the graph when switching domains
  useEffect(() => {
    // Trigger fade on domain change
    setGraphFadeIn(false);
    const raf = requestAnimationFrame(() => setGraphFadeIn(true));
    return () => cancelAnimationFrame(raf);
  }, [selectedDomainDetails?.id]);

  // Build match sets depending on exact/children selection (using cached domains)
  useEffect(() => {
    const buildSets = () => {
      if (!selectedDomainId) { setMatchSets(null); return; }
      const selected = domains.find(d => d.id === selectedDomainId);
      if (exactMatchesOnly) {
        const ids = new Set<string>([String(selectedDomainId)]);
        const namesLower = new Set<string>();
        if (selected?.name) namesLower.add(selected.name.toLowerCase());
        setMatchSets({ ids, namesLower });
        return;
      }
      // Build descendant tree using already-fetched domains (no API calls needed)
      const ids = new Set<string>();
      const namesLower = new Set<string>();
      const enqueue = (id?: string | null, name?: string | null) => {
        if (id) ids.add(String(id));
        if (name) namesLower.add(String(name).toLowerCase());
      };

      // Build a parent->children map from the cached domains
      const childrenMap = new Map<string, DataDomain[]>();
      const domainById = new Map<string, DataDomain>();
      domains.forEach(d => {
        domainById.set(d.id, d);
        if (d.parent_id) {
          const siblings = childrenMap.get(d.parent_id) || [];
          siblings.push(d);
          childrenMap.set(d.parent_id, siblings);
        }
      });

      // BFS to collect all descendants
      const root = domainById.get(selectedDomainId);
      if (root) {
        enqueue(root.id, root.name);
        const queue = [...(childrenMap.get(root.id) || [])];
        while (queue.length > 0) {
          const child = queue.shift()!;
          enqueue(child.id, child.name);
          const grandchildren = childrenMap.get(child.id) || [];
          queue.push(...grandchildren);
        }
      } else {
        // Fallback if domain not found in cache
        enqueue(String(selectedDomainId), selected?.name || null);
      }

      setMatchSets({ ids, namesLower });
    };
    buildSets();
  }, [selectedDomainId, exactMatchesOnly, domains]);

  const filteredProducts = useMemo(() => {
    if (!selectedDomainId) return allProducts;
    if (!matchSets) return [];
    return allProducts.filter(p => {
      // ODPS v1.0.0: domain is at root level, not in info
      const productDomainRaw = p?.domain;
      const productDomainIdLike = productDomainRaw != null ? String(productDomainRaw) : '';
      const productDomainLower = productDomainIdLike.toLowerCase();
      if (!productDomainLower) return false;
      if (matchSets.ids.has(productDomainIdLike)) return true; // match by id
      if (matchSets.namesLower.has(productDomainLower)) return true;
      return false;
    });
  }, [allProducts, selectedDomainId, matchSets]);

  // Handle subscribe button click
  const handleSubscribeClick = async (product: DataProduct) => {
    setSelectedProduct(product);
    const workflowId = await lookupWorkflowId('for_subscribe');
    if (workflowId) {
      setSubscriptionWorkflowId(workflowId);
      setSubscriptionWizardOpen(true);
    } else {
      setSubscribeDialogOpen(true);
    }
  };

  // Handle successful subscription
  const handleSubscriptionSuccess = () => {
    loadSubscribedProducts();
    setSubscribeDialogOpen(false);
    setSubscriptionWizardOpen(false);
    setSubscriptionWorkflowId(null);
    setSelectedProduct(null);
  };

  return (
    <section className="mb-16">
      <h2 className="text-2xl font-semibold mb-4">{t('discoverySection.title')}</h2>

      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2"><BoxSelect className="h-5 w-5" /><span className="font-medium">{t('discoverySection.dataDomains')}</span></div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">{t('discoverySection.exactMatchOnly')}</span>
              <Switch checked={exactMatchesOnly} onCheckedChange={(v) => setExactMatchesOnly(!!v)} />
            </div>
            {selectedDomainId && (
              <Button variant="outline" size="sm" onClick={() => setSelectedDomainId(null)} title={t('discoverySection.clearFilter')}>
                {t('discoverySection.allDomains')}
              </Button>
            )}
          </div>
        </div>

        {domainsLoading || domainLoading ? (
          <div style={{ height: 220, margin: 'auto' }} className="border rounded-lg overflow-hidden bg-muted/20 w-full flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : domainError ? (
          <div style={{ height: 220, margin: 'auto' }} className="border rounded-lg overflow-hidden bg-muted/20 w-full flex items-center justify-center">
            <Alert variant="destructive" className="m-0 border-0 bg-transparent">
              <AlertDescription>{domainError}</AlertDescription>
            </Alert>
          </div>
        ) : selectedDomainDetails ? (
          <div className={`transition-opacity duration-300 ${graphFadeIn ? 'opacity-100' : 'opacity-0'}`}>
            <DataDomainMiniGraph
              currentDomain={selectedDomainDetails}
              onNodeClick={(id) => setSelectedDomainId(id)}
            />
          </div>
        ) : (
          <div style={{ height: 220, margin: 'auto' }} className="border rounded-lg overflow-hidden bg-muted/20 w-full flex items-center justify-center text-muted-foreground">
            {t('discoverySection.selectDomain')}
          </div>
        )}
      </div>

      {/* My Subscriptions Section */}
      {!subscribedLoading && subscribedProducts.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <Bell className="h-5 w-5 text-primary" />
            <span className="font-medium">My Subscriptions ({subscribedProducts.length})</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {subscribedProducts.slice(0, 4).map(p => {
              const rawDomain = (p?.domain as any);
              const domainStr = rawDomain != null ? String(rawDomain) : '';
              const resolvedById = getDomainName(domainStr);
              const resolvedByName = !resolvedById && domainStr
                ? (domains.find(d => d.name.toLowerCase() === domainStr.toLowerCase())?.name || null)
                : null;
              const domainLabel = resolvedById || resolvedByName || (domainStr || null);
              const description = p.description?.purpose || p.description?.usage || '';
              const owner = p.team?.members?.[0]?.username || p.team?.name || t('discoverySection.unknown');

              return (
                <div key={p.id || p.name} className="group">
                  <Card className="transition-shadow group-hover:shadow-md h-full border-primary/20 bg-primary/5">
                    <CardHeader>
                      <div className="flex items-center gap-2">
                        <Bell className="h-4 w-4 text-primary" />
                        <CardTitle className="truncate flex-1 text-base">
                          <Link to={p.id ? `/data-products/${p.id}` : '/data-products'} className="hover:underline">
                            {p.name || t('discoverySection.untitled')}
                          </Link>
                        </CardTitle>
                      </div>
                      {description ? (
                        <CardDescription className="line-clamp-2">{description}</CardDescription>
                      ) : null}
                    </CardHeader>
                    <CardContent className="pt-0">
                      <div className="flex items-center gap-2 flex-wrap mb-2">
                        <Badge variant="secondary" className="text-xs">
                          {domainLabel || t('discoverySection.unknown')}
                        </Badge>
                        {p.status && (
                          <Badge variant="outline" className="text-xs">
                            {p.status}
                          </Badge>
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground mb-2 truncate">
                        Owner: {owner}
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        asChild
                      >
                        <Link to={p.id ? `/data-products/${p.id}` : '/data-products'}>
                          Manage
                        </Link>
                      </Button>
                    </CardContent>
                  </Card>
                </div>
              );
            })}
          </div>
          {subscribedProducts.length > 4 && (
            <div className="text-center mt-3">
              <Link to="/data-products" className="text-sm text-primary hover:underline">
                View all {subscribedProducts.length} subscribed products →
              </Link>
            </div>
          )}
        </div>
      )}

      <div>
        <div className="flex items-center gap-2 mb-3"><Star className="h-5 w-5 text-primary" /><span className="font-medium">{t('discoverySection.popularProducts')}</span></div>
        {productsLoading ? (
          <div className="flex items-center justify-center h-32"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>
        ) : productsError ? (
          <Alert variant="destructive" className="mb-4"><AlertCircle className="h-4 w-4" /><AlertDescription>{productsError}</AlertDescription></Alert>
        ) : filteredProducts.length === 0 ? (
          <p className="text-center text-muted-foreground">{t('discoverySection.noProducts')}</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredProducts
              .slice()
              .sort((a, b) => new Date(b.updated_at || '').getTime() - new Date(a.updated_at || '').getTime())
              .slice(0, maxItems)
              .map(p => {
                // ODPS v1.0.0: domain is at root level, not in info
                const rawDomain = (p?.domain as any);
                const domainStr = rawDomain != null ? String(rawDomain) : '';
                const resolvedById = getDomainName(domainStr);
                const resolvedByName = !resolvedById && domainStr
                  ? (domains.find(d => d.name.toLowerCase() === domainStr.toLowerCase())?.name || null)
                  : null;
                const domainLabel = resolvedById || resolvedByName || (domainStr || null);

                // ODPS v1.0.0: Get description from structured description
                const description = p.description?.purpose || p.description?.usage || '';

                // ODPS v1.0.0: Get owner from team
                const owner = p.team?.members?.[0]?.username || p.team?.name || t('discoverySection.unknown');

                return (
                  <div key={p.id || p.name} className="group">
                    <Card className="transition-shadow group-hover:shadow-md h-full">
                      <CardHeader>
                        <div className="flex items-center gap-2">
                          <Database className="h-5 w-5 text-primary" />
                          <CardTitle className="truncate flex-1">
                            <Link to={p.id ? `/data-products/${p.id}` : '/data-products'} className="hover:underline">
                              {p.name || t('discoverySection.untitled')}
                            </Link>
                          </CardTitle>
                          <button
                            className="inline-flex items-center justify-center text-foreground/80 hover:text-foreground transition-colors"
                            title={t('discoverySection.info')}
                            aria-label={t('discoverySection.info')}
                            onClick={() => { if (p.id) { setInfoProductId(p.id); setInfoProductTitle(p.name); } }}
                          >
                            <Info className="h-4 w-4" />
                          </button>
                        </div>
                        {description ? (
                          <CardDescription className="line-clamp-2">{description}</CardDescription>
                        ) : null}
                      </CardHeader>
                      <CardContent className="pt-0">
                        <div className="flex items-center gap-2 flex-wrap mb-2">
                          <Badge variant="secondary" className="text-xs">
                            {domainLabel || t('discoverySection.unknown')}
                          </Badge>
                          {p.status && (
                            <Badge variant="outline" className="text-xs">
                              {p.status}
                            </Badge>
                          )}
                        </div>
                        <div className="text-xs text-muted-foreground mb-2 truncate">
                          Owner: {owner}
                        </div>
                        {subscribedProductIds.has(p.id || '') ? (
                          <Button
                            variant="outline"
                            size="sm"
                            className="w-full"
                            disabled
                          >
                            <Bell className="h-3.5 w-3.5 mr-1" />
                            Subscribed
                          </Button>
                        ) : (
                          <Button
                            variant="outline"
                            size="sm"
                            className="w-full"
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              handleSubscribeClick(p);
                            }}
                          >
                            Subscribe
                          </Button>
                        )}
                      </CardContent>
                    </Card>
                  </div>
                );
              })}
          </div>
        )}
      </div>
      <EntityInfoDialog
        entityType={'data_product'}
        entityId={infoProductId}
        title={infoProductTitle}
        open={!!infoProductId}
        onOpenChange={(open) => { if (!open) { setInfoProductId(null); setInfoProductTitle(undefined); } }}
      />

      {/* Subscription wizard (approval workflow with completion_action=subscribe) */}
      {selectedProduct && subscriptionWizardOpen && subscriptionWorkflowId && (
        <ApprovalWizardDialog
          isOpen={subscriptionWizardOpen}
          onOpenChange={(open) => {
            setSubscriptionWizardOpen(open);
            if (!open) {
              setSubscriptionWorkflowId(null);
              setSelectedProduct(null);
            }
          }}
          entityType="data_product"
          entityId={selectedProduct.id || ''}
          preselectedWorkflowId={subscriptionWorkflowId}
          completionAction="subscribe"
          autoStartWithPreselected
          onComplete={handleSubscriptionSuccess}
        />
      )}

      {/* Subscribe Dialog (fallback when no subscription workflow) */}
      {selectedProduct && (
        <SubscribeDialog
          open={subscribeDialogOpen}
          onOpenChange={(open) => {
            setSubscribeDialogOpen(open);
            if (!open) setSelectedProduct(null);
          }}
          productId={selectedProduct.id || ''}
          productName={selectedProduct.name || 'Unknown Product'}
          onSuccess={handleSubscriptionSuccess}
        />
      )}
    </section>
  );
}



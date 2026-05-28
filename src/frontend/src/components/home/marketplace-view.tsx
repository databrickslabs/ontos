import { useEffect, useMemo, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Loader2, Database, Search, Bell, X, LayoutList, Network, Package, Grid2X2, ExternalLink } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useDomains } from '@/hooks/use-domains';
import { type DataProduct } from '@/types/data-product';
import { type DataDomain } from '@/types/data-domain';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { useUserStore } from '@/stores/user-store';
import { useViewModeStore } from '@/stores/view-mode-store';
import { cn } from '@/lib/utils';
import EntityInfoDialog from '@/components/metadata/entity-info-dialog';
import SubscribeDialog from '@/components/data-products/subscribe-dialog';
import ApprovalWizardDialog from '@/components/workflows/approval-wizard-dialog';
import { useApprovalWizardTrigger } from '@/hooks/use-approval-wizard-trigger';
import { DataDomainMiniGraph } from '@/components/data-domains/data-domain-mini-graph';
import { RatingBadge } from '@/components/ratings';
import { QualityBadge } from '@/components/quality/quality-badge';
import CertificationBadge from '@/components/common/certification-badge';
import PublicationBadge from '@/components/common/publication-badge';
import { PUBLICATION_SCOPE_LABELS, type CertificationLevel } from '@/types/lifecycle';

interface MarketplaceViewProps {
  className?: string;
}

export default function MarketplaceView({ className }: MarketplaceViewProps) {
  const { t } = useTranslation('home');
  const navigate = useNavigate();
  const { domains, loading: domainsLoading, getDomainName } = useDomains();
  const { userInfo } = useUserStore();
  const { domainBrowserStyle, setDomainBrowserStyle, tilesPerRow, setTilesPerRow } = useViewModeStore();
  
  // Compute grid class based on tiles per row setting
  const gridClass = useMemo(() => {
    switch (tilesPerRow) {
      case 1: return 'grid grid-cols-1 gap-4';
      case 2: return 'grid grid-cols-1 sm:grid-cols-2 gap-4';
      case 3: return 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4';
      case 4: 
      default: return 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4';
    }
  }, [tilesPerRow]);
  
  // Search and filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDomainId, setSelectedDomainId] = useState<string | null>(null);
  const [scopeFilter, setScopeFilter] = useState<string>('all');
  const [certificationLevels, setCertificationLevels] = useState<CertificationLevel[]>([]);
  
  // Graph view state
  const [selectedDomainDetails, setSelectedDomainDetails] = useState<DataDomain | null>(null);
  const [domainDetailsLoading, setDomainDetailsLoading] = useState(false);
  const [graphFadeIn, setGraphFadeIn] = useState(false);
  
  // Exact match filter (false = include children, true = exact domain only)
  const [exactMatchesOnly, setExactMatchesOnly] = useState(false);
  const [matchSets, setMatchSets] = useState<{ ids: Set<string>; namesLower: Set<string> } | null>(null);
  const [matchesLoading, _setMatchesLoading] = useState(false);
  
  // Products state
  const [allProducts, setAllProducts] = useState<DataProduct[]>([]);
  const [productsLoading, setProductsLoading] = useState(true);
  const [productsError, setProductsError] = useState<string | null>(null);
  
  // Subscribed products state
  const [, setSubscribedProducts] = useState<DataProduct[]>([]);
  const [subscribedProductIds, setSubscribedProductIds] = useState<Set<string>>(new Set());
  const [, setSubscribedLoading] = useState(true);
  
  // Dialog state
  const [selectedProduct, setSelectedProduct] = useState<DataProduct | null>(null);
  const [infoDialogOpen, setInfoDialogOpen] = useState(false);
  const [subscribeDialogOpen, setSubscribeDialogOpen] = useState(false);
  const [subscriptionWizardOpen, setSubscriptionWizardOpen] = useState(false);
  const [subscriptionWorkflowId, setSubscriptionWorkflowId] = useState<string | null>(null);
  const [checkingSubscription, setCheckingSubscription] = useState(false);
  const [productIsSubscribed, setProductIsSubscribed] = useState(false);
  const { lookupWorkflowId } = useApprovalWizardTrigger();

  useEffect(() => {
    let cancelled = false;
    fetch('/api/certification-levels')
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => {
        if (!cancelled) setCertificationLevels(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        if (!cancelled) setCertificationLevels([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Fetch published products (optional server-side scope filter)
  useEffect(() => {
    const loadProducts = async () => {
      try {
        setProductsLoading(true);
        const params =
          scopeFilter !== 'all' ? `?scope=${encodeURIComponent(scopeFilter)}` : '';
        const resp = await fetch(`/api/data-products/published${params}`);
        if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
        const data = await resp.json();
        setAllProducts(Array.isArray(data) ? data : []);
        setProductsError(null);
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : 'Failed to load products';
        setProductsError(message);
        setAllProducts([]);
      } finally {
        setProductsLoading(false);
      }
    };
    loadProducts();
  }, [scopeFilter]);

  // Fetch subscribed products
  const loadSubscribedProducts = useCallback(async () => {
    try {
      setSubscribedLoading(true);
      const resp = await fetch('/api/data-products/my-subscriptions');
      if (!resp.ok) {
        if (resp.status === 401) {
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
    } catch (e) {
      console.warn('Failed to fetch subscribed products:', e);
      setSubscribedProducts([]);
      setSubscribedProductIds(new Set());
    } finally {
      setSubscribedLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSubscribedProducts();
  }, [loadSubscribedProducts]);

  // Load domain details when in graph mode and domain is selected
  const loadDomainDetails = useCallback(async (domainId: string) => {
    try {
      setDomainDetailsLoading(true);
      const resp = await fetch(`/api/data-domains/${domainId}`);
      if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
      const data: DataDomain = await resp.json();
      setSelectedDomainDetails(data);
    } catch (e) {
      console.error('Failed to load domain details:', e);
      setSelectedDomainDetails(null);
    } finally {
      setDomainDetailsLoading(false);
    }
  }, []);

  // Load domain details when switching to graph mode or changing selection
  useEffect(() => {
    if (domainBrowserStyle === 'graph' && selectedDomainId) {
      loadDomainDetails(selectedDomainId);
    } else if (domainBrowserStyle === 'graph' && !selectedDomainId && domains.length > 0) {
      // Auto-select first root domain for graph view
      const rootDomain = domains.find(d => !d.parent_id) || domains[0];
      if (rootDomain) {
        setSelectedDomainId(rootDomain.id);
      }
    }
  }, [domainBrowserStyle, selectedDomainId, domains, loadDomainDetails]);

  // Fade-in effect for graph when domain changes
  useEffect(() => {
    setGraphFadeIn(false);
    const raf = requestAnimationFrame(() => setGraphFadeIn(true));
    return () => cancelAnimationFrame(raf);
  }, [selectedDomainDetails?.id]);

  // Sort domains by hierarchy (roots first, then children under their parents)
  const sortedDomains = useMemo(() => {
    if (!domains || domains.length === 0) return [];
    
    // Build a map of parent_id to children
    const childrenMap = new Map<string | null, DataDomain[]>();
    domains.forEach(d => {
      const parentId = d.parent_id || null;
      if (!childrenMap.has(parentId)) {
        childrenMap.set(parentId, []);
      }
      childrenMap.get(parentId)!.push(d);
    });
    
    // Sort each group alphabetically
    childrenMap.forEach((children) => {
      children.sort((a, b) => a.name.localeCompare(b.name));
    });
    
    // Build sorted list: roots first, then recursively add children
    const result: DataDomain[] = [];
    const addWithChildren = (domain: DataDomain, depth: number = 0) => {
      result.push({ ...domain, _depth: depth } as DataDomain & { _depth: number });
      const children = childrenMap.get(domain.id) || [];
      children.forEach(child => addWithChildren(child, depth + 1));
    };
    
    // Start with root domains (those without parent)
    const roots = childrenMap.get(null) || [];
    roots.forEach(root => addWithChildren(root));
    
    return result;
  }, [domains]);

  // Build match sets based on exact/children selection
  // Uses the already-loaded domains array to walk the tree client-side (no API calls needed)
  useEffect(() => {
    if (!selectedDomainId) { 
      setMatchSets(null); 
      return; 
    }
    
    const selected = domains.find(d => d.id === selectedDomainId);
    if (!selected) {
      // Domain not found in our list - try matching by name in case selectedDomainId is a name
      const byName = domains.find(d => d.name.toLowerCase() === selectedDomainId.toLowerCase());
      if (byName) {
        // Use the found domain
        const ids = new Set<string>([byName.id]);
        const namesLower = new Set<string>([byName.name.toLowerCase()]);
        setMatchSets({ ids, namesLower });
      } else {
        setMatchSets({ ids: new Set([selectedDomainId]), namesLower: new Set([selectedDomainId.toLowerCase()]) });
      }
      return;
    }
    
    // Exact match: only the selected domain
    if (exactMatchesOnly) {
      const ids = new Set<string>([String(selectedDomainId)]);
      const namesLower = new Set<string>([selected.name.toLowerCase()]);
      setMatchSets({ ids, namesLower });
      return;
    }
    
    // Include children: walk all descendants using the domains array (client-side)
    const ids = new Set<string>();
    const namesLower = new Set<string>();
    
    // Build a map of parent_id -> children for efficient lookup
    const childrenByParentId = new Map<string, DataDomain[]>();
    domains.forEach(d => {
      if (d.parent_id) {
        if (!childrenByParentId.has(d.parent_id)) {
          childrenByParentId.set(d.parent_id, []);
        }
        childrenByParentId.get(d.parent_id)!.push(d);
      }
    });
    
    // Walk the tree from the selected domain
    const queue: DataDomain[] = [selected];
    while (queue.length > 0) {
      const domain = queue.shift()!;
      ids.add(domain.id);
      namesLower.add(domain.name.toLowerCase());
      
      // Add children to queue
      const children = childrenByParentId.get(domain.id) || [];
      queue.push(...children);
    }
    
    setMatchSets({ ids, namesLower });
  }, [selectedDomainId, exactMatchesOnly, domains]);

  // Filter products based on search and domain
  const filteredProducts = useMemo(() => {
    let filtered = allProducts;
    
    // Filter by domain using matchSets
    if (selectedDomainId) {
      if (!matchSets) return []; // Still loading match sets
      filtered = filtered.filter(p => {
        const productDomainRaw = p?.domain;
        const productDomainIdLike = productDomainRaw != null ? String(productDomainRaw) : '';
        const productDomainLower = productDomainIdLike.toLowerCase();
        if (!productDomainLower) return false;
        if (matchSets.ids.has(productDomainIdLike)) return true; // Match by id
        if (matchSets.namesLower.has(productDomainLower)) return true; // Match by name
        return false;
      });
    }
    
    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(p => 
        p.name?.toLowerCase().includes(query) ||
        p.description?.purpose?.toLowerCase().includes(query) ||
        p.description?.usage?.toLowerCase().includes(query)
      );
    }

    return filtered;
  }, [allProducts, selectedDomainId, searchQuery, matchSets]);

  // Handle product card click
  const handleProductClick = async (product: DataProduct) => {
    setSelectedProduct(product);
    setCheckingSubscription(true);
    setProductIsSubscribed(subscribedProductIds.has(product.id || ''));
    setInfoDialogOpen(true);
    setCheckingSubscription(false);
  };

  // Handle subscribe button in info dialog: try approval wizard (subscription workflow), fallback to old dialog
  const handleSubscribeClick = async () => {
    setInfoDialogOpen(false);
    const workflowId = await lookupWorkflowId('for_subscribe');
    if (workflowId) {
      setSubscriptionWorkflowId(workflowId);
      setSubscriptionWizardOpen(true);
    } else {
      setSubscribeDialogOpen(true);
    }
  };

  // Handle successful product subscription (from wizard or old dialog)
  const handleProductSubscriptionSuccess = () => {
    loadSubscribedProducts();
    setSubscribeDialogOpen(false);
    setSubscriptionWizardOpen(false);
    setSubscriptionWorkflowId(null);
    setSelectedProduct(null);
  };

  // Get user's first name for greeting
  // Try display name (user field), then fall back to username/email
  const firstName = useMemo(() => {
    // First try the 'user' field which often contains the display name
    if (userInfo?.user) {
      const name = userInfo.user.trim();
      // Check for "Last, First" format
      if (name.includes(',')) {
        const afterComma = name.split(',')[1]?.trim();
        if (afterComma) {
          // Take first word after comma (handles "Last, First Middle")
          return afterComma.split(' ')[0];
        }
      }
      // Standard "First Last" format
      return name.split(' ')[0] || '';
    }
    // Fall back to username (might be email format like first.last@domain.com)
    if (userInfo?.username) {
      // If it looks like an email, extract the first part before @
      const emailPart = userInfo.username.split('@')[0];
      // If it has dots (like first.last), take the first part
      const namePart = emailPart.split('.')[0];
      // Capitalize first letter
      return namePart.charAt(0).toUpperCase() + namePart.slice(1).toLowerCase();
    }
    return '';
  }, [userInfo]);

  // Handle opening product in details view
  const handleOpenProductDetails = (e: React.MouseEvent, productId: string) => {
    e.stopPropagation();
    navigate(`/my-products/${productId}`);
  };

  // Render product card
  const renderProductCard = (product: DataProduct, isSubscribed: boolean = false) => {
    const domainRaw = product?.domain;
    const domainStr = domainRaw != null ? String(domainRaw) : '';
    const domainLabel = getDomainName(domainStr) || domainStr || t('marketplace.products.unknown');
    const description = product.description?.purpose || product.description?.usage || '';
    const owner = product.team?.members?.[0]?.username || product.team?.name || t('marketplace.products.unknown');

    return (
      <Card 
        key={product.id || product.name} 
        className={cn(
          "cursor-pointer transition-all hover:shadow-md hover:border-primary/30",
          isSubscribed && "border-primary/20 bg-primary/5"
        )}
        onClick={() => handleProductClick(product)}
      >
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <Package className="h-4 w-4 text-primary flex-shrink-0" />
              <CardTitle className="text-base truncate">{product.name || 'Untitled'}</CardTitle>
            </div>
            <div className="flex items-center gap-1 flex-shrink-0">
              {isSubscribed && (
                <Bell className="h-4 w-4 text-primary" />
              )}
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0 hover:bg-primary/10"
                onClick={(e) => handleOpenProductDetails(e, product.id || '')}
                title={t('marketplace.openInDetails')}
              >
                <ExternalLink className="h-3.5 w-3.5 text-muted-foreground hover:text-primary" />
              </Button>
            </div>
          </div>
          {description && (
            <CardDescription className="line-clamp-2 text-sm">{description}</CardDescription>
          )}
        </CardHeader>
        <CardContent className="pt-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant="secondary" className="text-xs">
              {domainLabel}
            </Badge>
            {product.status && (
              <Badge variant="outline" className="text-xs">
                {product.status}
              </Badge>
            )}
            <PublicationBadge
              publicationScope={product.publication_scope}
              publishedAt={product.published_at ?? undefined}
              publishedBy={product.published_by ?? undefined}
            />
            <CertificationBadge
              certificationLevel={product.certification_level}
              inheritedCertificationLevel={product.inherited_certification_level}
              certifiedAt={product.certified_at ?? undefined}
              certifiedBy={product.certified_by ?? undefined}
              levels={certificationLevels}
              size="sm"
            />
            {product.id && (
              <RatingBadge
                entityType="data_product"
                entityId={product.id}
                size="sm"
              />
            )}
            {product.id && (
              <QualityBadge
                entityType="data_product"
                entityId={product.id}
                productAggregation
                size="sm"
              />
            )}
          </div>
          <div className="text-xs text-muted-foreground mt-2 truncate">
            {t('marketplace.products.owner')}: {owner}
          </div>
        </CardContent>
      </Card>
    );
  };

  return (
    <div className={cn("space-y-6", className)}>
      {/* Welcome Header */}
      <div className="bg-gradient-to-r from-primary/10 via-primary/5 to-transparent rounded-lg p-6">
        <h1 className="text-3xl font-bold tracking-tight">
          {firstName 
            ? t('marketplace.welcomeWithName', { name: firstName }) 
            : t('marketplace.welcome')}
        </h1>
        <p className="text-muted-foreground mt-1">
          {t('marketplace.tagline')}
        </p>
      </div>

      {/* Search Bar */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          type="search"
          placeholder={t('marketplace.searchPlaceholder')}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-10 h-12 text-base"
        />
        {searchQuery && (
          <Button
            variant="ghost"
            size="sm"
            className="absolute right-2 top-1/2 -translate-y-1/2 h-7 w-7 p-0"
            onClick={() => setSearchQuery('')}
          >
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>

      {/* Domain Browser */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-medium">{t('marketplace.browseDataDomains')}</div>
          <div className="flex items-center gap-4">
            {/* Exact match toggle - only show when a domain is selected */}
            {selectedDomainId && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">{t('marketplace.exactMatchOnly')}</span>
                <Switch 
                  checked={exactMatchesOnly} 
                  onCheckedChange={(v) => setExactMatchesOnly(!!v)} 
                />
              </div>
            )}
            {/* View style toggle */}
            <div className="inline-flex items-center gap-1 p-0.5 bg-muted rounded-md">
              <Button
                variant={domainBrowserStyle === 'pills' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setDomainBrowserStyle('pills')}
                className="h-7 px-2 gap-1"
                title={t('marketplace.domainView.pills')}
              >
                <LayoutList className="h-3.5 w-3.5" />
                <span className="sr-only sm:not-sr-only sm:inline text-xs">{t('marketplace.domainView.pills')}</span>
              </Button>
              <Button
                variant={domainBrowserStyle === 'graph' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setDomainBrowserStyle('graph')}
                className="h-7 px-2 gap-1"
                title={t('marketplace.domainView.graph')}
              >
                <Network className="h-3.5 w-3.5" />
                <span className="sr-only sm:not-sr-only sm:inline text-xs">{t('marketplace.domainView.graph')}</span>
              </Button>
            </div>
          </div>
        </div>

        {domainsLoading || domainDetailsLoading ? (
          <div className="flex items-center gap-2 text-muted-foreground h-[220px] justify-center border rounded-lg bg-muted/20">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">{t('marketplace.loadingDomains')}</span>
          </div>
        ) : domainBrowserStyle === 'pills' ? (
          /* Pills View */
          <div className="flex flex-wrap gap-2">
            <Button
              variant={selectedDomainId === null ? "default" : "outline"}
              size="sm"
              onClick={() => setSelectedDomainId(null)}
              className="rounded-full"
            >
              {t('marketplace.allDomains')}
            </Button>
            {sortedDomains.map(domain => {
              const parentDomain = domain.parent_id 
                ? domains.find(d => d.id === domain.parent_id) 
                : null;
              return (
                <HoverCard key={domain.id} openDelay={300} closeDelay={100}>
                  <HoverCardTrigger asChild>
                    <Button
                      variant={selectedDomainId === domain.id ? "default" : "outline"}
                      size="sm"
                      onClick={() => setSelectedDomainId(domain.id)}
                      className="rounded-full"
                    >
                      {domain.name}
                    </Button>
                  </HoverCardTrigger>
                  <HoverCardContent side="bottom" align="start" className="w-72">
                    <div className="space-y-2">
                      <div className="flex items-start gap-2">
                        <Database className="h-4 w-4 mt-0.5 text-primary flex-shrink-0" />
                        <div>
                          <h4 className="text-sm font-semibold">{domain.name}</h4>
                          {parentDomain && (
                            <p className="text-xs text-muted-foreground">
                              {t('marketplace.domainInfo.parentDomain')}: {parentDomain.name}
                            </p>
                          )}
                        </div>
                      </div>
                      {domain.description && (
                        <p className="text-xs text-muted-foreground line-clamp-3">
                          {domain.description}
                        </p>
                      )}
                      {domain.children_count !== undefined && domain.children_count > 0 && (
                        <p className="text-xs text-muted-foreground">
                          {t('marketplace.domainInfo.childDomains', { count: domain.children_count })}
                        </p>
                      )}
                    </div>
                  </HoverCardContent>
                </HoverCard>
              );
            })}
          </div>
        ) : (
          /* Graph View */
          selectedDomainDetails ? (
            <div className={`transition-opacity duration-300 ${graphFadeIn ? 'opacity-100' : 'opacity-0'}`}>
              <DataDomainMiniGraph
                currentDomain={selectedDomainDetails}
                onNodeClick={(id) => setSelectedDomainId(id)}
              />
            </div>
          ) : (
            <div className="h-[220px] border rounded-lg overflow-hidden bg-muted/20 w-full flex items-center justify-center text-muted-foreground">
              {t('marketplace.selectDomainForGraph')}
            </div>
          )
        )}
      </div>

      {/* Scope filter & tiles per row */}
      <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Select value={scopeFilter} onValueChange={setScopeFilter}>
              <SelectTrigger className="w-[180px] h-7 text-xs">
                <SelectValue placeholder={t('marketplace.scopeFilter.placeholder')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('marketplace.scopeFilter.all')}</SelectItem>
                <SelectItem value="domain">{PUBLICATION_SCOPE_LABELS.domain}</SelectItem>
                <SelectItem value="organization">{PUBLICATION_SCOPE_LABELS.organization}</SelectItem>
                <SelectItem value="external">{PUBLICATION_SCOPE_LABELS.external}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-4 flex-wrap">
            {/* Tiles Per Row Selector */}
            <div className="flex items-center gap-2">
              <Grid2X2 className="h-4 w-4 text-muted-foreground" />
              <Select
                value={String(tilesPerRow)}
                onValueChange={(v) => setTilesPerRow(Number(v) as 1 | 2 | 3 | 4)}
              >
                <SelectTrigger className="w-[100px] h-7 text-xs">
                  <SelectValue placeholder={t('marketplace.tilesPerRow.placeholder')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">{t('marketplace.tilesPerRow.one')}</SelectItem>
                  <SelectItem value="2">{t('marketplace.tilesPerRow.two')}</SelectItem>
                  <SelectItem value="3">{t('marketplace.tilesPerRow.three')}</SelectItem>
                  <SelectItem value="4">{t('marketplace.tilesPerRow.four')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        {/* Products */}
        <div className="mt-4">
          {productsLoading || matchesLoading ? (
            <div className="flex items-center justify-center h-48">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : productsError ? (
            <Alert variant="destructive">
              <AlertDescription>{productsError}</AlertDescription>
            </Alert>
          ) : filteredProducts.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <Package className="h-12 w-12 mx-auto mb-4 opacity-30" />
              <p>{t('marketplace.products.noProducts')}</p>
              {(searchQuery || selectedDomainId || scopeFilter !== 'all') && (
                <p className="text-sm mt-1">{t('marketplace.products.adjustFilters')}</p>
              )}
            </div>
          ) : (
            <>
              <div className="text-sm text-muted-foreground mb-4">
                {filteredProducts.length} {filteredProducts.length === 1 ? 'product' : 'products'} available
              </div>
              <div className={gridClass}>
                {filteredProducts.map(p => renderProductCard(p, subscribedProductIds.has(p.id || '')))}
              </div>
            </>
          )}
        </div>

      {/* Info Dialog - Products */}
      {selectedProduct && (
        <EntityInfoDialog
          entityType="data_product"
          entityId={selectedProduct.id || null}
          title={selectedProduct.name}
          open={infoDialogOpen}
          onOpenChange={(open) => {
            setInfoDialogOpen(open);
            if (!open) setSelectedProduct(null);
          }}
          onSubscribe={handleSubscribeClick}
          isSubscribed={productIsSubscribed}
          subscriptionLoading={checkingSubscription}
          showBackButton
        />
      )}

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
          onComplete={handleProductSubscriptionSuccess}
        />
      )}

      {/* Subscribe Dialog - Products (fallback when no subscription workflow) */}
      {selectedProduct && (
        <SubscribeDialog
          open={subscribeDialogOpen}
          onOpenChange={(open) => {
            setSubscribeDialogOpen(open);
            if (!open) setSelectedProduct(null);
          }}
          productId={selectedProduct.id || ''}
          productName={selectedProduct.name || 'Unknown Product'}
          onSuccess={handleProductSubscriptionSuccess}
        />
      )}
    </div>
  );
}


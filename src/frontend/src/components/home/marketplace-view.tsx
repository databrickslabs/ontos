import { useEffect, useMemo, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Loader2, Database, Search, Bell, Bookmark, X, LayoutList, Network, Package, Table2, Grid2X2, ExternalLink } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useDomains } from '@/hooks/use-domains';
import { type DataProduct } from '@/types/data-product';
import { type DataDomain } from '@/types/data-domain';
import { type DatasetListItem, DATASET_STATUS_LABELS, DATASET_STATUS_COLORS } from '@/types/dataset';
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
import { DataDomainMiniGraph } from '@/components/data-domains/data-domain-mini-graph';
import { RatingBadge } from '@/components/ratings';

// Asset type for marketplace browsing
type MarketplaceAssetType = 'products' | 'datasets';

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
  const [activeTab, setActiveTab] = useState<'explore' | 'subscriptions'>('explore');
  const [assetType, setAssetType] = useState<MarketplaceAssetType>('products');
  
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
  const [subscribedProducts, setSubscribedProducts] = useState<DataProduct[]>([]);
  const [subscribedProductIds, setSubscribedProductIds] = useState<Set<string>>(new Set());
  const [subscribedLoading, setSubscribedLoading] = useState(true);
  
  // Datasets state
  const [allDatasets, setAllDatasets] = useState<DatasetListItem[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(false);
  const [datasetsError, setDatasetsError] = useState<string | null>(null);
  
  // Subscribed datasets state
  const [subscribedDatasets, setSubscribedDatasets] = useState<DatasetListItem[]>([]);
  const [subscribedDatasetIds, setSubscribedDatasetIds] = useState<Set<string>>(new Set());
  const [subscribedDatasetsLoading, setSubscribedDatasetsLoading] = useState(false);
  
  // Selected dataset for dialogs
  const [selectedDataset, setSelectedDataset] = useState<DatasetListItem | null>(null);
  const [datasetIsSubscribed, setDatasetIsSubscribed] = useState(false);
  
  // Dialog state
  const [selectedProduct, setSelectedProduct] = useState<DataProduct | null>(null);
  const [infoDialogOpen, setInfoDialogOpen] = useState(false);
  const [subscribeDialogOpen, setSubscribeDialogOpen] = useState(false);
  const [checkingSubscription, setCheckingSubscription] = useState(false);
  const [productIsSubscribed, setProductIsSubscribed] = useState(false);

  // Fetch published products
  useEffect(() => {
    const loadProducts = async () => {
      try {
        setProductsLoading(true);
        const resp = await fetch('/api/data-products/published');
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
  }, []);

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

  // Fetch published datasets (load on mount to know if toggle should be shown)
  useEffect(() => {
    const loadDatasets = async () => {
      try {
        setDatasetsLoading(true);
        const resp = await fetch('/api/datasets/published');
        if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
        const data = await resp.json();
        setAllDatasets(Array.isArray(data) ? data : []);
        setDatasetsError(null);
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : 'Failed to load datasets';
        setDatasetsError(message);
        setAllDatasets([]);
      } finally {
        setDatasetsLoading(false);
      }
    };
    loadDatasets();
  }, []);

  // Fetch subscribed datasets
  const loadSubscribedDatasets = useCallback(async () => {
    try {
      setSubscribedDatasetsLoading(true);
      const resp = await fetch('/api/datasets/my-subscriptions');
      if (!resp.ok) {
        if (resp.status === 401) {
          setSubscribedDatasets([]);
          setSubscribedDatasetIds(new Set());
          return;
        }
        throw new Error(`HTTP error! status: ${resp.status}`);
      }
      const data = await resp.json();
      const datasets = Array.isArray(data) ? data : [];
      setSubscribedDatasets(datasets);
      setSubscribedDatasetIds(new Set(datasets.map((d: DatasetListItem) => d.id).filter(Boolean)));
    } catch (e) {
      console.warn('Failed to fetch subscribed datasets:', e);
      setSubscribedDatasets([]);
      setSubscribedDatasetIds(new Set());
    } finally {
      setSubscribedDatasetsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (assetType === 'datasets') {
      loadSubscribedDatasets();
    }
  }, [assetType, loadSubscribedDatasets]);

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

  // Filter datasets based on search query (datasets don't have domain association)
  const filteredDatasets = useMemo(() => {
    let filtered = allDatasets;
    
    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(d => 
        d.name?.toLowerCase().includes(query) ||
        d.full_path?.toLowerCase().includes(query) ||
        d.contract_name?.toLowerCase().includes(query)
      );
    }
    
    return filtered;
  }, [allDatasets, searchQuery]);

  // Determine if we have products and/or datasets available
  const hasProducts = allProducts.length > 0;
  const hasDatasets = allDatasets.length > 0;
  const showAssetToggle = hasProducts && hasDatasets;

  // Auto-switch to available asset type when only one exists
  useEffect(() => {
    if (productsLoading || datasetsLoading) return;
    
    if (!hasProducts && hasDatasets && assetType === 'products') {
      setAssetType('datasets');
    } else if (hasProducts && !hasDatasets && assetType === 'datasets') {
      setAssetType('products');
    }
  }, [hasProducts, hasDatasets, assetType, productsLoading, datasetsLoading]);

  // Handle product card click
  const handleProductClick = async (product: DataProduct) => {
    setSelectedProduct(product);
    setSelectedDataset(null);
    setCheckingSubscription(true);
    setProductIsSubscribed(subscribedProductIds.has(product.id || ''));
    setInfoDialogOpen(true);
    setCheckingSubscription(false);
  };

  // Handle dataset card click
  const handleDatasetClick = async (dataset: DatasetListItem) => {
    setSelectedDataset(dataset);
    setSelectedProduct(null);
    setCheckingSubscription(true);
    setDatasetIsSubscribed(subscribedDatasetIds.has(dataset.id || ''));
    setInfoDialogOpen(true);
    setCheckingSubscription(false);
  };

  // Handle subscribe button in info dialog
  const handleSubscribeClick = () => {
    setInfoDialogOpen(false);
    setSubscribeDialogOpen(true);
  };

  // Handle successful product subscription
  const handleProductSubscriptionSuccess = () => {
    loadSubscribedProducts();
    setSubscribeDialogOpen(false);
    setSelectedProduct(null);
  };

  // Handle successful dataset subscription
  const handleDatasetSubscriptionSuccess = async () => {
    // Call the dataset subscribe API
    if (selectedDataset) {
      try {
        const resp = await fetch(`/api/datasets/${selectedDataset.id}/subscribe`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: '' }),
        });
        if (resp.ok) {
          loadSubscribedDatasets();
          setDatasetIsSubscribed(true);
        }
      } catch (e) {
        console.error('Failed to subscribe to dataset:', e);
      }
    }
    setSubscribeDialogOpen(false);
    setSelectedDataset(null);
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
    navigate(`/data-products/${productId}`);
  };

  // Handle opening dataset in details view
  const handleOpenDatasetDetails = (e: React.MouseEvent, datasetId: string) => {
    e.stopPropagation();
    navigate(`/datasets/${datasetId}`);
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
            {product.id && (
              <RatingBadge
                entityType="data_product"
                entityId={product.id}
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

  // Render dataset card
  const renderDatasetCard = (dataset: DatasetListItem, isSubscribed: boolean = false) => {
    const statusLabel = DATASET_STATUS_LABELS[dataset.status] || dataset.status;
    const statusColorClass = DATASET_STATUS_COLORS[dataset.status] || '';

    return (
      <Card 
        key={dataset.id} 
        className={cn(
          "cursor-pointer transition-all hover:shadow-md hover:border-primary/30",
          isSubscribed && "border-primary/20 bg-primary/5"
        )}
        onClick={() => handleDatasetClick(dataset)}
      >
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <Table2 className="h-4 w-4 text-primary flex-shrink-0" />
              <CardTitle className="text-base truncate">{dataset.name || 'Untitled'}</CardTitle>
            </div>
            <div className="flex items-center gap-1 flex-shrink-0">
              {isSubscribed && (
                <Bell className="h-4 w-4 text-primary" />
              )}
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0 hover:bg-primary/10"
                onClick={(e) => handleOpenDatasetDetails(e, dataset.id || '')}
                title={t('marketplace.openInDetails')}
              >
                <ExternalLink className="h-3.5 w-3.5 text-muted-foreground hover:text-primary" />
              </Button>
            </div>
          </div>
          {dataset.description && (
            <CardDescription className="line-clamp-2 text-sm">
              {dataset.description}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="pt-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge className={cn("text-xs", statusColorClass)}>
              {statusLabel}
            </Badge>
            {dataset.instance_count !== undefined && dataset.instance_count > 0 && (
              <Badge variant="outline" className="text-xs">
                {dataset.instance_count} instance{dataset.instance_count !== 1 ? 's' : ''}
              </Badge>
            )}
            {dataset.contract_name && (
              <Badge variant="secondary" className="text-xs">
                {dataset.contract_name}
              </Badge>
            )}
            {dataset.id && (
              <RatingBadge
                entityType="dataset"
                entityId={dataset.id}
                size="sm"
              />
            )}
          </div>
          {dataset.owner_team_name && (
            <div className="text-xs text-muted-foreground mt-2 truncate">
              {t('marketplace.datasets.owner')}: {dataset.owner_team_name}
            </div>
          )}
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
          placeholder={assetType === 'products' ? t('marketplace.searchPlaceholder') : t('marketplace.searchDatasetsPlaceholder')}
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

      {/* Domain Browser - only show for products */}
      {assetType === 'products' && (
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
      )}

      {/* Tabs with Asset Type Toggle */}
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as 'explore' | 'subscriptions')}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <TabsList>
            <TabsTrigger value="explore" className="gap-2">
              <Search className="h-4 w-4" />
              {t('marketplace.tabs.explore')}
            </TabsTrigger>
            <TabsTrigger value="subscriptions" className="gap-2">
              <Bookmark className="h-4 w-4" />
              {t('marketplace.tabs.subscriptions')}
              {assetType === 'products' && subscribedProducts.length > 0 && (
                <Badge variant="secondary" className="ml-1 h-5 px-1.5 text-xs">
                  {subscribedProducts.length}
                </Badge>
              )}
              {assetType === 'datasets' && subscribedDatasets.length > 0 && (
                <Badge variant="secondary" className="ml-1 h-5 px-1.5 text-xs">
                  {subscribedDatasets.length}
                </Badge>
              )}
            </TabsTrigger>
          </TabsList>

          {/* Asset Type Toggle & Tiles Per Row */}
          <div className="flex items-center gap-4 flex-wrap">
            {/* Asset Type Toggle - only show when both types have data */}
            {showAssetToggle && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">{t('marketplace.browseAssetType')}</span>
                <div className="inline-flex items-center gap-1 p-0.5 bg-muted rounded-md">
                  <Button
                    variant={assetType === 'products' ? 'default' : 'ghost'}
                    size="sm"
                    onClick={() => setAssetType('products')}
                    className="h-7 px-3 gap-1.5"
                  >
                    <Package className="h-3.5 w-3.5" />
                    {t('marketplace.assetTypes.products')}
                  </Button>
                  <Button
                    variant={assetType === 'datasets' ? 'default' : 'ghost'}
                    size="sm"
                    onClick={() => setAssetType('datasets')}
                    className="h-7 px-3 gap-1.5"
                  >
                    <Table2 className="h-3.5 w-3.5" />
                    {t('marketplace.assetTypes.datasets')}
                  </Button>
                </div>
              </div>
            )}

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

        {/* Explore Tab Content - Products */}
        {assetType === 'products' && (
          <TabsContent value="explore" className="mt-4">
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
                {(searchQuery || selectedDomainId) && (
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
          </TabsContent>
        )}

        {/* Explore Tab Content - Datasets */}
        {assetType === 'datasets' && (
          <TabsContent value="explore" className="mt-4">
            {datasetsLoading ? (
              <div className="flex items-center justify-center h-48">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              </div>
            ) : datasetsError ? (
              <Alert variant="destructive">
                <AlertDescription>{datasetsError}</AlertDescription>
              </Alert>
            ) : filteredDatasets.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                <Table2 className="h-12 w-12 mx-auto mb-4 opacity-30" />
                <p>{t('marketplace.datasets.noDatasets')}</p>
                {searchQuery && (
                  <p className="text-sm mt-1">{t('marketplace.datasets.adjustFilters')}</p>
                )}
              </div>
            ) : (
              <>
                <div className="text-sm text-muted-foreground mb-4">
                  {filteredDatasets.length} {filteredDatasets.length === 1 ? 'dataset' : 'datasets'} available
                </div>
                <div className={gridClass}>
                  {filteredDatasets.map(d => renderDatasetCard(d, subscribedDatasetIds.has(d.id || '')))}
                </div>
              </>
            )}
          </TabsContent>
        )}

        {/* My Data (Subscriptions) Tab Content - Products */}
        {assetType === 'products' && (
          <TabsContent value="subscriptions" className="mt-4">
            {subscribedLoading ? (
              <div className="flex items-center justify-center h-48">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              </div>
            ) : subscribedProducts.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                <Bell className="h-12 w-12 mx-auto mb-4 opacity-30" />
                <p>{t('marketplace.products.noSubscriptions')}</p>
                <p className="text-sm mt-1">{t('marketplace.products.browseToSubscribe')}</p>
                <Button 
                  variant="outline" 
                  className="mt-4"
                  onClick={() => setActiveTab('explore')}
                >
                  <Search className="mr-2 h-4 w-4" />
                  {t('marketplace.products.exploreProducts')}
                </Button>
              </div>
            ) : (
              <>
                <div className="text-sm text-muted-foreground mb-4">
                  {subscribedProducts.length} subscribed {subscribedProducts.length === 1 ? 'product' : 'products'}
                </div>
                <div className={gridClass}>
                  {subscribedProducts.map(p => renderProductCard(p, true))}
                </div>
              </>
            )}
          </TabsContent>
        )}

        {/* My Data (Subscriptions) Tab Content - Datasets */}
        {assetType === 'datasets' && (
          <TabsContent value="subscriptions" className="mt-4">
            {subscribedDatasetsLoading ? (
              <div className="flex items-center justify-center h-48">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              </div>
            ) : subscribedDatasets.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                <Bell className="h-12 w-12 mx-auto mb-4 opacity-30" />
                <p>{t('marketplace.datasets.noSubscriptions')}</p>
                <p className="text-sm mt-1">{t('marketplace.datasets.browseToSubscribe')}</p>
                <Button 
                  variant="outline" 
                  className="mt-4"
                  onClick={() => setActiveTab('explore')}
                >
                  <Search className="mr-2 h-4 w-4" />
                  {t('marketplace.datasets.exploreDatasets')}
                </Button>
              </div>
            ) : (
              <>
                <div className="text-sm text-muted-foreground mb-4">
                  {subscribedDatasets.length} subscribed {subscribedDatasets.length === 1 ? 'dataset' : 'datasets'}
                </div>
                <div className={gridClass}>
                  {subscribedDatasets.map(d => renderDatasetCard(d, true))}
                </div>
              </>
            )}
          </TabsContent>
        )}
      </Tabs>

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

      {/* Info Dialog - Datasets */}
      {selectedDataset && (
        <EntityInfoDialog
          entityType="dataset"
          entityId={selectedDataset.id || null}
          title={selectedDataset.name}
          open={infoDialogOpen}
          onOpenChange={(open) => {
            setInfoDialogOpen(open);
            if (!open) setSelectedDataset(null);
          }}
          onSubscribe={handleSubscribeClick}
          isSubscribed={datasetIsSubscribed}
          subscriptionLoading={checkingSubscription}
          showBackButton
        />
      )}

      {/* Subscribe Dialog - Products */}
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

      {/* Subscribe Dialog - Datasets */}
      {selectedDataset && subscribeDialogOpen && (
        <SubscribeDialog
          open={subscribeDialogOpen}
          onOpenChange={(open) => {
            setSubscribeDialogOpen(open);
            if (!open) setSelectedDataset(null);
          }}
          productId={selectedDataset.id || ''}
          productName={selectedDataset.name || 'Unknown Dataset'}
          onSuccess={handleDatasetSubscriptionSuccess}
          isDataset
        />
      )}
    </div>
  );
}


import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { Package, Users, Search, User, Calendar, MessageSquare } from 'lucide-react';
import { useApi } from '@/hooks/use-api';
import { cn } from '@/lib/utils';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { RelativeDate } from '@/components/common/relative-date';
import type { DataProduct, SubscriberInfo } from '@/types/data-product';

interface ProductWithSubscribers {
  product: DataProduct;
  subscribers: SubscriberInfo[];
  loading: boolean;
}

export default function OwnerConsumersView() {
  const { t: _t } = useTranslation(['data-products', 'common']);
  const api = useApi();
  const setStaticSegments = useBreadcrumbStore((s) => s.setStaticSegments);

  const [products, setProducts] = useState<DataProduct[]>([]);
  const [productsLoading, setProductsLoading] = useState(true);
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);
  const [productSubscribers, setProductSubscribers] = useState<Record<string, ProductWithSubscribers>>({});
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    setStaticSegments([{ label: 'Consumers' }]);
  }, [setStaticSegments]);

  const fetchProducts = useCallback(async () => {
    setProductsLoading(true);
    try {
      const resp = await api.get<DataProduct[]>('/api/data-products');
      setProducts(resp.data ?? []);
    } catch (err) {
      console.error('Failed to fetch products:', err);
    } finally {
      setProductsLoading(false);
    }
  }, [api]);

  useEffect(() => { fetchProducts(); }, [fetchProducts]);

  const fetchSubscribers = useCallback(async (productId: string) => {
    setProductSubscribers((prev) => ({
      ...prev,
      [productId]: { ...prev[productId], loading: true },
    }));
    try {
      const resp = await api.get<{ subscribers: SubscriberInfo[] }>(`/api/data-products/${productId}/subscribers`);
      setProductSubscribers((prev) => ({
        ...prev,
        [productId]: {
          product: products.find((p) => p.id === productId)!,
          subscribers: resp.data?.subscribers ?? [],
          loading: false,
        },
      }));
    } catch (err) {
      console.error('Failed to fetch subscribers:', err);
      setProductSubscribers((prev) => ({
        ...prev,
        [productId]: { ...prev[productId], subscribers: [], loading: false },
      }));
    }
  }, [api, products]);

  useEffect(() => {
    if (selectedProductId && !productSubscribers[selectedProductId]) {
      fetchSubscribers(selectedProductId);
    }
  }, [selectedProductId, fetchSubscribers, productSubscribers]);

  // Auto-select first product
  useEffect(() => {
    if (!selectedProductId && products.length > 0) {
      setSelectedProductId(products[0].id);
    }
  }, [products, selectedProductId]);

  const totalSubscribers = useMemo(() => {
    return Object.values(productSubscribers).reduce(
      (sum, ps) => sum + (ps.subscribers?.length ?? 0),
      0
    );
  }, [productSubscribers]);

  // Fetch subscriber counts for all products on initial load
  useEffect(() => {
    if (products.length > 0) {
      products.forEach((p) => {
        if (!productSubscribers[p.id]) {
          fetchSubscribers(p.id);
        }
      });
    }
  }, [products]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedData = selectedProductId ? productSubscribers[selectedProductId] : null;

  const filteredSubscribers = useMemo(() => {
    if (!selectedData?.subscribers) return [];
    if (!searchQuery.trim()) return selectedData.subscribers;
    const q = searchQuery.toLowerCase();
    return selectedData.subscribers.filter(
      (s) =>
        s.email.toLowerCase().includes(q) ||
        (s.reason && s.reason.toLowerCase().includes(q))
    );
  }, [selectedData, searchQuery]);

  const activeProducts = products.filter((p) => p.status === 'active' || p.status === 'approved' || p.status === 'certified');

  return (
    <div className="space-y-6">
      {/* Summary stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-primary/10 p-2.5">
                <Package className="h-5 w-5 text-primary" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Total Products</p>
                <p className="text-2xl font-bold">
                  {productsLoading ? <Skeleton className="h-8 w-12" /> : products.length}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-green-500/10 p-2.5">
                <Package className="h-5 w-5 text-green-600 dark:text-green-400" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Active Products</p>
                <p className="text-2xl font-bold">
                  {productsLoading ? <Skeleton className="h-8 w-12" /> : activeProducts.length}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-blue-500/10 p-2.5">
                <Users className="h-5 w-5 text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Total Subscribers</p>
                <p className="text-2xl font-bold">
                  {productsLoading ? <Skeleton className="h-8 w-12" /> : totalSubscribers}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Two-column layout: product list + subscriber detail */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Product list */}
        <Card className="lg:col-span-1">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Products</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 max-h-[600px] overflow-y-auto">
            {productsLoading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full rounded-md" />
              ))
            ) : products.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">No products found</p>
            ) : (
              products.map((p) => {
                const subCount = productSubscribers[p.id]?.subscribers?.length ?? 0;
                const isSelected = selectedProductId === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => setSelectedProductId(p.id)}
                    className={cn(
                      'w-full flex items-center justify-between rounded-md px-3 py-2.5 text-left transition-colors',
                      isSelected
                        ? 'bg-primary/10 text-primary'
                        : 'hover:bg-muted/50'
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">{p.name ?? p.id}</p>
                      <p className="text-xs text-muted-foreground">{p.domain ?? 'No domain'}</p>
                    </div>
                    <Badge variant="secondary" className="ml-2 shrink-0">
                      <Users className="h-3 w-3 mr-1" />
                      {subCount}
                    </Badge>
                  </button>
                );
              })
            )}
          </CardContent>
        </Card>

        {/* Subscriber detail */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">
                {selectedData?.product
                  ? `Subscribers — ${selectedData.product.name ?? selectedData.product.id}`
                  : 'Select a product'}
              </CardTitle>
              {selectedProductId && (
                <div className="relative w-64">
                  <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Filter subscribers..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9 h-9"
                  />
                </div>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {!selectedProductId ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <Users className="h-10 w-10 mb-3 opacity-40" />
                <p className="text-sm">Select a product to view its subscribers</p>
              </div>
            ) : selectedData?.loading ? (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : filteredSubscribers.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <Users className="h-10 w-10 mb-3 opacity-40" />
                <p className="text-sm">
                  {searchQuery ? 'No subscribers match your filter' : 'No subscribers yet'}
                </p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Subscriber</TableHead>
                    <TableHead>Subscribed</TableHead>
                    <TableHead>Reason</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredSubscribers.map((sub) => (
                    <TableRow key={sub.email}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <div className="rounded-full bg-muted p-1.5">
                            <User className="h-3.5 w-3.5 text-muted-foreground" />
                          </div>
                          <span className="text-sm font-medium">{sub.email}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                          <Calendar className="h-3.5 w-3.5" />
                          <RelativeDate date={sub.subscribed_at} />
                        </div>
                      </TableCell>
                      <TableCell>
                        {sub.reason ? (
                          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                            <MessageSquare className="h-3.5 w-3.5" />
                            <span className="truncate max-w-[300px]">{sub.reason}</span>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground italic">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

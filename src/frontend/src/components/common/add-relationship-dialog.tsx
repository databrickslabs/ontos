import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import {
  Search, Loader2, Check, Database, Table2, Eye, Radio,
  LayoutDashboard, BookOpen, BrainCircuit, Globe, Zap,
  Box, Server, Shapes, FolderTree, Columns2, FileCode, Brain,
  Activity, Shield, FolderOpen,
} from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { useFormatLabel } from '@/lib/format-label';
import { AssetTypeRead } from '@/types/asset';
import type { RelationshipDefinition } from '@/types/ontology-schema';

interface AddRelationshipDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  entityType: string;
  entityId: string;
  onRelationshipCreated: () => void;
}

interface TargetEntity {
  id: string;
  name: string;
  type: string;
  location?: string;
}

const ASSET_TYPE_ICONS: Record<string, React.ElementType> = {
  Dataset: Database,
  Table: Table2,
  View: Eye,
  'Delivery Channel': Radio,
  Dashboard: LayoutDashboard,
  Notebook: BookOpen,
  'ML Model': BrainCircuit,
  'API Endpoint': Globe,
  Stream: Zap,
};

const ICON_MAP: Record<string, React.ElementType> = {
  Table2, Eye, Columns2, LayoutDashboard, Globe, FileCode, Brain, Activity,
  Server, Shield, BookOpen, Database, FolderOpen, Shapes, Box,
};

const CATEGORY_META: Record<string, { labelKey: string; icon: React.ElementType; order: number }> = {
  data: { labelKey: 'assetSelector.categories.data', icon: Database, order: 1 },
  analytics: { labelKey: 'assetSelector.categories.analytics', icon: LayoutDashboard, order: 2 },
  integration: { labelKey: 'assetSelector.categories.integration', icon: Globe, order: 3 },
  system: { labelKey: 'assetSelector.categories.system', icon: Server, order: 4 },
  custom: { labelKey: 'assetSelector.categories.custom', icon: Shapes, order: 5 },
};

function getAssetIcon(typeName?: string) {
  if (!typeName) return Database;
  return ASSET_TYPE_ICONS[typeName] || Database;
}

function getIconComponent(iconName?: string | null): React.ElementType {
  if (!iconName) return Box;
  return ICON_MAP[iconName] || Box;
}

function formatTypeName(raw: string): string {
  return raw.replace(/([A-Z])/g, ' $1').trim();
}

function TargetResultRow({ entity, isSelected, onSelect }: {
  entity: TargetEntity;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const { t } = useTranslation('common');
  const Icon = getAssetIcon(entity.type);
  return (
    <button
      onClick={onSelect}
      className={cn(
        'w-full flex items-center gap-3 px-3 py-2 rounded-md text-left transition-colors overflow-hidden',
        isSelected ? 'bg-primary/10 border border-primary/20' : 'hover:bg-muted'
      )}
    >
      <Icon className="h-4 w-4 text-muted-foreground flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{entity.name}</div>
        {entity.location && (
          <div className="text-xs text-muted-foreground truncate">{entity.location}</div>
        )}
      </div>
      <Badge variant="outline" className="text-xs flex-shrink-0">
        {entity.type || t('common:addRelationship.assetFallback')}
      </Badge>
      {isSelected && <Check className="h-4 w-4 text-primary flex-shrink-0" />}
    </button>
  );
}

function TargetResultsList({ results, loading, selectedId, onSelect, emptyMessage }: {
  results: TargetEntity[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (entity: TargetEntity) => void;
  emptyMessage?: string;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (results.length === 0 && emptyMessage) {
    return <p className="text-sm text-muted-foreground text-center py-6">{emptyMessage}</p>;
  }
  return (
    <div className="space-y-0.5">
      {results.map(entity => (
        <TargetResultRow
          key={entity.id}
          entity={entity}
          isSelected={selectedId === entity.id}
          onSelect={() => onSelect(entity)}
        />
      ))}
    </div>
  );
}

export function AddRelationshipDialog({
  isOpen,
  onOpenChange,
  entityType,
  entityId,
  onRelationshipCreated,
}: AddRelationshipDialogProps) {
  const { get: apiGet, post: apiPost } = useApi();
  const { toast } = useToast();
  const { t, i18n } = useTranslation('common');
  const formatLabel = useFormatLabel();

  // Relationship type state
  const [validRelationships, setValidRelationships] = useState<RelationshipDefinition[]>([]);
  const [selectedRelType, setSelectedRelType] = useState('');
  const [relTypesLoading, setRelTypesLoading] = useState(false);

  // Target selection
  const [selectedTarget, setSelectedTarget] = useState<TargetEntity | null>(null);
  const [createLoading, setCreateLoading] = useState(false);

  // Browse/search mode
  const [mode, setMode] = useState<'search' | 'browse'>('browse');

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<TargetEntity[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Browse state
  const [assetTypes, setAssetTypes] = useState<AssetTypeRead[]>([]);
  const [typesLoading, setTypesLoading] = useState(false);
  const [selectedTypeId, setSelectedTypeId] = useState<string | null>(null);
  const [browseResults, setBrowseResults] = useState<TargetEntity[]>([]);
  const [browseTotal, setBrowseTotal] = useState(0);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseFilter, setBrowseFilter] = useState('');
  const browseDebounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Unique key for each relationship definition (property_name alone can repeat across target types)
  const relKey = useCallback((r: RelationshipDefinition) =>
    `${r.property_name}::${r.target_type_iri || r.target_type_label || ''}`,
    []
  );

  const selectedRelDef = useMemo(() =>
    validRelationships.find(r => relKey(r) === selectedRelType),
    [validRelationships, selectedRelType, relKey]
  );
  const targetTypeLabel = selectedRelDef?.target_type_label
    || selectedRelDef?.target_type_iri?.split('#')[1]
    || '';
  const targetAssetTypes = targetTypeLabel ? [targetTypeLabel] : [];

  // Group asset types by category, filtered by target type
  const groupedTypes = useMemo(() => {
    const filtered = targetAssetTypes.length > 0
      ? assetTypes.filter(t => targetAssetTypes.includes(t.name))
      : assetTypes;
    const groups: Record<string, AssetTypeRead[]> = {};
    for (const t of filtered) {
      const cat = t.category || 'custom';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(t);
    }
    return Object.entries(groups)
      .map(([cat, types]) => ({
        category: cat,
        label: CATEGORY_META[cat]?.labelKey ? t(`common:${CATEGORY_META[cat].labelKey}`) : cat,
        icon: CATEGORY_META[cat]?.icon || Shapes,
        order: CATEGORY_META[cat]?.order || 99,
        types: types.sort((a, b) => a.name.localeCompare(b.name)),
      }))
      .sort((a, b) => a.order - b.order);
  }, [assetTypes, targetAssetTypes, t]);

  // Auto-select the only matching type in browse mode
  useEffect(() => {
    if (selectedRelType && groupedTypes.length > 0 && !selectedTypeId) {
      const allTypes = groupedTypes.flatMap(g => g.types);
      if (allTypes.length === 1) {
        handleTypeSelect(allTypes[0].id);
      }
    }
  }, [groupedTypes, selectedRelType]);

  // --- Fetching ---

  const fetchValidRelationships = useCallback(async () => {
    setRelTypesLoading(true);
    try {
      const iri = `http://ontos.app/ontology#${entityType}`;
      const response = await apiGet<{ type_iri: string; outgoing: RelationshipDefinition[]; incoming: RelationshipDefinition[] }>(
        `/api/ontology/entity-types/relationships?type_iri=${encodeURIComponent(iri)}&lang=${encodeURIComponent(i18n.language)}`
      );
      if (!response.error && response.data) {
        setValidRelationships(response.data.outgoing);
      }
    } catch { /* non-critical */ }
    finally { setRelTypesLoading(false); }
  }, [apiGet, entityType, i18n.language]);

  const fetchAssetTypes = useCallback(async () => {
    setTypesLoading(true);
    try {
      const response = await apiGet<AssetTypeRead[]>('/api/asset-types?limit=100');
      if (!response.error && Array.isArray(response.data)) {
        setAssetTypes(response.data.filter(t => t.status === 'active'));
      }
    } catch { /* silent */ }
    finally { setTypesLoading(false); }
  }, [apiGet]);

  const doSearch = useCallback(async (query: string) => {
    if (query.length < 2) {
      setSearchResults([]);
      return;
    }
    setSearchLoading(true);
    try {
      let url = `/api/assets?name=${encodeURIComponent(query)}&limit=20`;
      if (targetAssetTypes.length > 0) {
        url += `&asset_type_names=${encodeURIComponent(targetAssetTypes.join(','))}`;
      }
      const response = await apiGet<{ items: any[]; total: number }>(url);
      const items = response.data?.items;
      if (!response.error && Array.isArray(items)) {
        setSearchResults(items.map(a => ({
          id: a.id,
          name: a.name,
          type: a.asset_type_name || 'Asset',
          location: a.location,
        })));
      } else {
        setSearchResults([]);
      }
    } catch {
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  }, [apiGet, targetAssetTypes]);

  const fetchBrowseAssets = useCallback(async (typeId: string, nameFilter?: string) => {
    setBrowseLoading(true);
    try {
      let url = `/api/assets?asset_type_id=${typeId}&limit=50`;
      if (nameFilter && nameFilter.length >= 2) {
        url += `&name=${encodeURIComponent(nameFilter)}`;
      }
      const response = await apiGet<{ items: any[]; total: number }>(url);
      const items = response.data?.items;
      if (!response.error && Array.isArray(items)) {
        setBrowseResults(items.map(a => ({
          id: a.id,
          name: a.name,
          type: a.asset_type_name || 'Asset',
          location: a.location,
        })));
        setBrowseTotal(response.data?.total ?? 0);
      } else {
        setBrowseResults([]);
        setBrowseTotal(0);
      }
    } catch {
      setBrowseResults([]);
      setBrowseTotal(0);
    } finally {
      setBrowseLoading(false);
    }
  }, [apiGet]);

  // --- Handlers ---

  const handleSearchQueryChange = (value: string) => {
    setSearchQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(value), 300);
  };

  const handleTypeSelect = (typeId: string) => {
    setSelectedTypeId(typeId);
    setBrowseFilter('');
    fetchBrowseAssets(typeId);
  };

  const handleBrowseFilterChange = (value: string) => {
    setBrowseFilter(value);
    if (browseDebounceRef.current) clearTimeout(browseDebounceRef.current);
    if (selectedTypeId) {
      if (value.length === 0) {
        fetchBrowseAssets(selectedTypeId);
      } else {
        browseDebounceRef.current = setTimeout(() => {
          fetchBrowseAssets(selectedTypeId, value);
        }, 300);
      }
    }
  };

  const handleRelTypeChange = (val: string) => {
    setSelectedRelType(val);
    setSelectedTarget(null);
    setSearchQuery('');
    setSearchResults([]);
    setSelectedTypeId(null);
    setBrowseResults([]);
    setBrowseFilter('');
  };

  const handleSelectTarget = (entity: TargetEntity) => {
    setSelectedTarget(prev => prev?.id === entity.id ? null : entity);
  };

  const handleCreate = async () => {
    if (!selectedTarget || !selectedRelType || !selectedRelDef) return;
    setCreateLoading(true);
    try {
      const tType = selectedRelDef.target_type_label
        || selectedRelDef.target_type_iri?.split('#')[1]
        || selectedTarget.type;
      const payload = {
        source_type: entityType,
        source_id: entityId,
        target_type: tType,
        target_id: selectedTarget.id,
        relationship_type: selectedRelDef.property_name,
      };
      const response = await apiPost('/api/entity-relationships', payload);
      if (response.error) throw new Error(response.error);
      toast({ title: t('common:addRelationship.relationshipCreated') });
      onOpenChange(false);
      resetState();
      onRelationshipCreated();
    } catch (err: any) {
      toast({ variant: 'destructive', title: t('common:toast.error'), description: err.message });
    } finally {
      setCreateLoading(false);
    }
  };

  const resetState = () => {
    setSelectedRelType('');
    setSelectedTarget(null);
    setMode('browse');
    setSearchQuery('');
    setSearchResults([]);
    setSelectedTypeId(null);
    setBrowseResults([]);
    setBrowseTotal(0);
    setBrowseFilter('');
  };

  useEffect(() => {
    if (isOpen) {
      resetState();
      fetchValidRelationships();
      fetchAssetTypes();
    }
  }, [isOpen]);

  useEffect(() => {
    if (mode === 'search' && selectedRelType) {
      setTimeout(() => searchInputRef.current?.focus(), 50);
    }
  }, [mode, selectedRelType]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (browseDebounceRef.current) clearTimeout(browseDebounceRef.current);
    };
  }, []);

  const selectedTypeName = assetTypes.find(t => t.id === selectedTypeId)?.name;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { onOpenChange(open); if (!open) resetState(); }}>
      <DialogContent className="max-w-2xl p-0 overflow-hidden">
        <div className="flex flex-col max-h-[80vh] overflow-hidden">
          {/* Header */}
          <div className="px-6 pt-6 pb-2">
            <DialogHeader>
              <DialogTitle>{t('common:addRelationship.title')}</DialogTitle>
              <DialogDescription>
                {t('common:addRelationship.description', { type: formatTypeName(entityType) })}
              </DialogDescription>
            </DialogHeader>
          </div>

          {/* Relationship type selector */}
          <div className="px-6 pb-3">
            <Label>{t('common:addRelationship.relationshipType')}</Label>
            <Select value={selectedRelType} onValueChange={handleRelTypeChange}>
              <SelectTrigger className="mt-1">
                <SelectValue placeholder={relTypesLoading ? t('common:states.loading') : t('common:addRelationship.selectRelationshipType')} />
              </SelectTrigger>
              <SelectContent>
                {validRelationships.map((r) => (
                  <SelectItem key={relKey(r)} value={relKey(r)}>
                    {formatLabel(r.label)} → {r.target_type_label || r.target_type_iri?.split('#')[1] || '?'}
                  </SelectItem>
                ))}
                {validRelationships.length === 0 && !relTypesLoading && (
                  <SelectItem value="_none" disabled>{t('common:addRelationship.noValidRelationships')}</SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>

          {/* Target selection area -- only shown when a relationship type is selected */}
          {selectedRelType ? (
            <>
              <Separator />

              {/* Mode toggle */}
              <div className="px-6 py-3 flex items-center justify-between">
                <Label className="text-sm">
                  {targetTypeLabel
                    ? t('common:addRelationship.selectTargetTyped', { type: targetTypeLabel })
                    : t('common:addRelationship.selectTarget')}
                </Label>
                <Tabs value={mode} onValueChange={(v) => setMode(v as 'search' | 'browse')}>
                  <TabsList className="h-8">
                    <TabsTrigger value="search" className="gap-1.5 text-xs px-2.5 h-6">
                      <Search className="h-3 w-3" />
                      {t('common:actions.search')}
                    </TabsTrigger>
                    <TabsTrigger value="browse" className="gap-1.5 text-xs px-2.5 h-6">
                      <FolderTree className="h-3 w-3" />
                      {t('common:actions.browse')}
                    </TabsTrigger>
                  </TabsList>
                </Tabs>
              </div>

              {/* Content area */}
              <div className="flex-1 min-h-0 px-6 overflow-hidden">
                {mode === 'search' ? (
                  <div className="flex flex-col h-full min-h-[200px] overflow-hidden">
                    <div className="relative mb-3">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                      <Input
                        ref={searchInputRef}
                        placeholder={t('common:addRelationship.searchByNamePlaceholder', { type: targetTypeLabel || t('common:addRelationship.entitiesFallback') })}
                        value={searchQuery}
                        onChange={(e) => handleSearchQueryChange(e.target.value)}
                        className="pl-9"
                      />
                      {searchLoading && (
                        <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground" />
                      )}
                    </div>
                    <ScrollArea className="flex-1 min-h-0">
                      <TargetResultsList
                        results={searchResults}
                        loading={false}
                        selectedId={selectedTarget?.id ?? null}
                        onSelect={handleSelectTarget}
                        emptyMessage={
                          searchQuery.length >= 2
                            ? (searchLoading ? undefined : t('common:addRelationship.noEntitiesFound'))
                            : t('common:addRelationship.typeToSearchHint')
                        }
                      />
                    </ScrollArea>
                  </div>
                ) : (
                  <div className="flex gap-3 h-full min-h-[250px] overflow-hidden">
                    {/* Type sidebar */}
                    <ScrollArea className="w-44 flex-shrink-0 border rounded-md">
                      <div className="p-1">
                        {typesLoading ? (
                          <div className="flex items-center justify-center py-8">
                            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                          </div>
                        ) : groupedTypes.length === 0 ? (
                          <p className="text-xs text-muted-foreground text-center py-4">{t('common:addRelationship.noMatchingTypes')}</p>
                        ) : (
                          groupedTypes.map(group => (
                            <div key={group.category} className="mb-2">
                              <div className="flex items-center gap-1.5 px-2 py-1">
                                <group.icon className="h-3.5 w-3.5 text-muted-foreground" />
                                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                                  {group.label}
                                </span>
                              </div>
                              {group.types.map(t => {
                                const TypeIcon = getIconComponent(t.icon);
                                return (
                                  <button
                                    key={t.id}
                                    onClick={() => handleTypeSelect(t.id)}
                                    className={cn(
                                      'w-full flex items-center gap-2 px-2 py-1.5 rounded-sm text-left text-sm transition-colors',
                                      selectedTypeId === t.id
                                        ? 'bg-primary/10 text-primary font-medium'
                                        : 'hover:bg-muted text-foreground'
                                    )}
                                  >
                                    <TypeIcon className="h-3.5 w-3.5 flex-shrink-0" />
                                    <span className="truncate flex-1">{t.name}</span>
                                    <span className="text-xs text-muted-foreground flex-shrink-0">
                                      {t.asset_count}
                                    </span>
                                  </button>
                                );
                              })}
                            </div>
                          ))
                        )}
                      </div>
                    </ScrollArea>

                    {/* Results panel */}
                    <div className="flex-1 min-w-0 flex flex-col border rounded-md overflow-hidden">
                      {selectedTypeId ? (
                        <>
                          <div className="relative px-3 py-2 border-b">
                            <Search className="absolute left-5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                            <Input
                              placeholder={t('common:addRelationship.filterPlaceholder', { type: selectedTypeName || t('common:addRelationship.entitiesFallback') })}
                              value={browseFilter}
                              onChange={(e) => handleBrowseFilterChange(e.target.value)}
                              className="pl-8 h-8 text-sm"
                            />
                          </div>
                          <ScrollArea className="flex-1">
                            <div className="p-1">
                              <TargetResultsList
                                results={browseResults}
                                loading={browseLoading}
                                selectedId={selectedTarget?.id ?? null}
                                onSelect={handleSelectTarget}
                                emptyMessage={
                                  browseFilter.length >= 2
                                    ? t('common:addRelationship.noMatchingEntities')
                                    : t('common:addRelationship.noEntitiesOfType')
                                }
                              />
                            </div>
                            {browseTotal > 50 && !browseLoading && (
                              <p className="text-xs text-muted-foreground text-center py-2">
                                {t('common:addRelationship.showingLimit', { total: browseTotal })}
                              </p>
                            )}
                          </ScrollArea>
                        </>
                      ) : (
                        <div className="flex-1 flex items-center justify-center">
                          <div className="text-center text-muted-foreground">
                            <FolderTree className="h-8 w-8 mx-auto mb-2 opacity-40" />
                            <p className="text-sm">{t('common:addRelationship.selectTypeToBrowse')}</p>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* Selected target indicator */}
              {selectedTarget && (
                <div className="px-6 pt-2">
                  <Separator className="mb-2" />
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-muted-foreground">{t('common:addRelationship.selected')}</span>
                    <Badge variant="secondary" className="gap-1">
                      {(() => { const Icon = getAssetIcon(selectedTarget.type); return <Icon className="h-3 w-3" />; })()}
                      <span className="max-w-48 truncate">{selectedTarget.name}</span>
                    </Badge>
                    <Badge variant="outline" className="text-xs">{selectedTarget.type}</Badge>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="px-6 py-8 text-center text-muted-foreground">
              <p className="text-sm">{t('common:addRelationship.selectRelTypePrompt')}</p>
            </div>
          )}

          {/* Footer */}
          <div className="px-6 pb-6 pt-3">
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>{t('common:actions.cancel')}</Button>
              <Button onClick={handleCreate} disabled={!selectedTarget || !selectedRelType || createLoading}>
                {createLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {t('common:addRelationship.createRelationship')}
              </Button>
            </DialogFooter>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

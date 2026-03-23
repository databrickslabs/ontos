import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { Columns2, FileText, Shapes, X, Link2 } from 'lucide-react';
import UCAssetLookupDialog from '@/components/data-contracts/uc-asset-lookup-dialog';
import { UCAssetInfo, UCAssetType } from '@/types/uc-asset';

type PropertyItem = { value: string; label: string; type: 'property' };
type Neighbor = {
  direction: 'outgoing' | 'incoming' | 'predicate';
  predicate: string;
  display: string;
  displayType: 'resource' | 'property' | 'literal';
  stepIri?: string | null;
  stepIsResource?: boolean;
};

type SemanticLink = {
  id: string;
  entity_id: string;
  entity_type: string;
  iri: string;
};

type EnrichedSemanticLink = SemanticLink & {
  entity_name?: string;
};

interface PropertiesSearchProps {
  initialQuery?: string;
  initialSelectedProperty?: PropertyItem | null;
}

export default function PropertiesSearch({
  initialQuery = '',
  initialSelectedProperty = null
}: PropertiesSearchProps) {
  const { get, post } = useApi();
  const { toast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation(['search', 'common']);

  const [propertySearchQuery, setPropertySearchQuery] = useState(initialQuery);
  const [propertySearchResults, setPropertySearchResults] = useState<PropertyItem[]>([]);
  const [isPropertyDropdownOpen, setIsPropertyDropdownOpen] = useState(false);
  const [selectedProperty, setSelectedProperty] = useState<PropertyItem | null>(initialSelectedProperty);
  const [propertyIri, setPropertyIri] = useState('');
  const [_propertyLabel, setPropertyLabel] = useState('');
  const [propertyNeighbors, setPropertyNeighbors] = useState<Neighbor[]>([]);
  const [semanticLinks, setSemanticLinks] = useState<EnrichedSemanticLink[]>([]);

  // Assign dialog: target type and selection
  const [assignDialogOpen, setAssignDialogOpen] = useState(false);
  const [assignTargetType, setAssignTargetType] = useState<'data_contract_property' | 'uc_column' | ''>('');
  const [contracts, setContracts] = useState<any[]>([]);
  const [selectedContractId, setSelectedContractId] = useState('');
  const [selectedSchemaName, setSelectedSchemaName] = useState('');
  const [selectedPropertyEntityId, setSelectedPropertyEntityId] = useState('');
  const [ucAssetDialogOpen, setUCAssetDialogOpen] = useState(false);

  const updateUrl = (updates: Partial<{ query: string; iri: string }>) => {
    const params = new URLSearchParams();
    const currentParams = new URLSearchParams(location.search);
    const currentQuery = updates.query !== undefined ? updates.query : currentParams.get('query') || '';
    const currentIri = updates.iri !== undefined ? updates.iri : currentParams.get('iri') || '';

    if (currentQuery) params.set('query', currentQuery);
    if (currentIri) params.set('iri', currentIri);

    params.set('tab', 'properties');
    const queryString = params.toString();
    navigate(`${location.pathname}?${queryString}`, { replace: true });
  };

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const urlQuery = params.get('query');
    const urlIri = params.get('iri');

    if (urlQuery && urlQuery !== initialQuery) {
      setPropertySearchQuery(urlQuery);
    }

    if (urlIri) {
      const loadPropertyFromIri = async () => {
        try {
          const res = await get<PropertyItem[]>(`/api/semantic-models/properties?q=${encodeURIComponent(urlIri)}&limit=10`);
          const match = (res.data || []).find((p: PropertyItem) => p.value === urlIri);
          if (match) {
            await selectProperty(match);
          } else {
            const item: PropertyItem = {
              value: urlIri,
              label: urlIri.split(/[/#]/).pop() || urlIri,
              type: 'property'
            };
            await selectProperty(item);
          }
        } catch (error) {
          console.error('Error loading property from URL:', error);
        }
      };
      loadPropertyFromIri();
    }
  }, [location.search]);

  useEffect(() => {
    const searchProperties = async () => {
      if (!propertySearchQuery.trim()) {
        setPropertySearchResults([]);
        setIsPropertyDropdownOpen(false);
        updateUrl({ query: '' });
        return;
      }

      try {
        const res = await get<PropertyItem[]>(`/api/semantic-models/properties?q=${encodeURIComponent(propertySearchQuery)}&limit=50`);
        setPropertySearchResults(res.data || []);
        setIsPropertyDropdownOpen((res.data || []).length > 0);
        updateUrl({ query: propertySearchQuery });
      } catch (error) {
        console.error('Error searching properties:', error);
        setPropertySearchResults([]);
        setIsPropertyDropdownOpen(false);
      }
    };

    const timer = setTimeout(searchProperties, 250);
    return () => clearTimeout(timer);
  }, [propertySearchQuery]);

  const clearSearch = () => {
    setPropertySearchQuery('');
    setSelectedProperty(null);
    setPropertyIri('');
    setPropertyLabel('');
    setPropertyNeighbors([]);
    setSemanticLinks([]);
    setIsPropertyDropdownOpen(false);
    updateUrl({ query: '', iri: '' });
  };

  const selectProperty = async (property: PropertyItem) => {
    setSelectedProperty(property);
    setPropertyIri(property.value);

    let displayLabel = property.label;
    if (!displayLabel || displayLabel.trim() === property.value) {
      displayLabel = property.value.includes('#') ? property.value.split('#').pop()! : property.value.split('/').pop() || property.value;
    }

    setPropertyLabel(displayLabel);
    setPropertySearchQuery(`${displayLabel} - ${property.value}`);
    setIsPropertyDropdownOpen(false);
    updateUrl({ iri: property.value });

    try {
      const res = await get<Neighbor[]>(`/api/semantic-models/neighbors?iri=${encodeURIComponent(property.value)}&limit=200`);
      setPropertyNeighbors(res.data || []);
    } catch (error) {
      console.error('Error loading neighbors:', error);
      setPropertyNeighbors([]);
    }

    try {
      const res = await get<SemanticLink[]>(`/api/semantic-links/iri/${encodeURIComponent(property.value)}`);
      const links = res.data || [];
      const enriched = await enrichSemanticLinksWithNames(links);
      setSemanticLinks(enriched);
    } catch (error) {
      console.error('Error loading semantic links:', error);
      setSemanticLinks([]);
    }
  };

  const enrichSemanticLinksWithNames = async (links: SemanticLink[]): Promise<EnrichedSemanticLink[]> => {
    const result: EnrichedSemanticLink[] = [];

    for (const link of links) {
      let entityName = link.entity_id;
      try {
        if (link.entity_type === 'data_contract_property') {
          const [contractId, schemaName, propName] = String(link.entity_id).split('#');
          if (contractId) {
            const contractRes = await get<any>(`/api/data-contracts/${contractId}`);
            const contractTitle = contractRes.data?.name || contractRes.data?.info?.title || contractId;
            entityName = `${contractTitle}#${schemaName || ''}.${propName || ''}`.trim();
          }
        } else if (link.entity_type === 'uc_column') {
          entityName = link.entity_id;
        } else if (link.entity_type === 'data_contract') {
          const contractRes = await get<any>(`/api/data-contracts/${link.entity_id}`);
          entityName = contractRes.data?.name || contractRes.data?.info?.title || link.entity_id;
        }
        result.push({ ...link, entity_name: entityName });
      } catch (error) {
        console.error('Error fetching details for', link.entity_type, link.entity_id, error);
        result.push({ ...link, entity_name: link.entity_id });
      }
    }
    return result;
  };

  const getLiteralAttributes = () => {
    return propertyNeighbors.filter(
      (n) => n.direction === 'outgoing' && n.displayType === 'literal' && !n.predicate.includes('type')
    );
  };

  const getDomainRange = () => {
    return propertyNeighbors.filter(
      (n) =>
        n.displayType === 'resource' &&
        (n.predicate.includes('domain') || n.predicate.includes('range'))
    );
  };

  // Load contracts for assign dialog
  useEffect(() => {
    if (assignTargetType === 'data_contract_property') {
      get<any[]>('/api/data-contracts')
        .then((res) => setContracts(res.data || []))
        .catch(() => setContracts([]));
    }
  }, [assignTargetType]);

  const [selectedContractDetail, setSelectedContractDetail] = useState<any>(null);

  useEffect(() => {
    if (!selectedContractId) {
      setSelectedContractDetail(null);
      return;
    }
    get<any>(`/api/data-contracts/${selectedContractId}`)
      .then((res) => setSelectedContractDetail(res.data))
      .catch(() => setSelectedContractDetail(null));
  }, [selectedContractId]);

  const schemaObjects = selectedContractDetail?.schema_objects || [];
  const schemas = schemaObjects.map((s: any) => ({ name: s.name || s.physical_name }));
  const selectedSchema = schemaObjects.find((s: any) => (s.name || s.physical_name) === selectedSchemaName);
  const properties = selectedSchema?.properties || [];

  const handleAssignTargetTypeChange = (v: string) => {
    setAssignTargetType(v as 'data_contract_property' | 'uc_column');
    setSelectedContractId('');
    setSelectedSchemaName('');
    setSelectedPropertyEntityId('');
  };

  const handleAssign = async () => {
    if (!selectedProperty || !assignTargetType) return;

    let entityId = '';
    let entityType = assignTargetType;

    if (assignTargetType === 'data_contract_property') {
      entityId = selectedPropertyEntityId;
      if (!entityId) {
        toast({
          title: t('common:toast.error'),
          description: t('search:properties.messages.selectPropertyTarget'),
          variant: 'destructive'
        });
        return;
      }
    } else if (assignTargetType === 'uc_column') {
      return;
    }

    try {
      const res = await post('/api/semantic-links/', {
        entity_id: entityId,
        entity_type: entityType,
        iri: selectedProperty.value
      });

      if (res.error) throw new Error(res.error);

      toast({
        title: t('common:toast.success'),
        description: t('search:properties.messages.linkedSuccess')
      });

      setAssignDialogOpen(false);
      setAssignTargetType('');
      setSelectedContractId('');
      setSelectedSchemaName('');
      setSelectedPropertyEntityId('');
      await selectProperty(selectedProperty);
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message || t('search:properties.messages.assignFailed'),
        variant: 'destructive'
      });
    }
  };

  const handleUCColumnSelect = (asset: UCAssetInfo) => {
    if (!asset.column_name || !selectedProperty) return;
    const entityId = asset.full_name;

    post('/api/semantic-links/', {
      entity_id: entityId,
      entity_type: 'uc_column',
      iri: selectedProperty.value
    })
      .then((res) => {
        if (res.error) throw new Error(res.error);
        toast({
          title: t('common:toast.success'),
          description: t('search:properties.messages.linkedSuccess')
        });
        setAssignDialogOpen(false);
        setUCAssetDialogOpen(false);
        selectProperty(selectedProperty);
      })
      .catch((err: any) => {
        toast({
          title: t('common:toast.error'),
          description: err.message || t('search:properties.messages.assignFailed'),
          variant: 'destructive'
        });
      });
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">{t('search:properties.searchAndSelect')}</p>
        <div className="relative">
          <Input
            value={propertySearchQuery}
            onChange={(e) => setPropertySearchQuery(e.target.value)}
            onFocus={() => setIsPropertyDropdownOpen(propertySearchResults.length > 0)}
            placeholder={t('search:properties.searchPlaceholder')}
            className="w-full"
          />
          {(propertySearchQuery || selectedProperty) && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute right-1 top-1 h-7 w-7"
              onClick={clearSearch}
              aria-label={t('search:properties.clear')}
            >
              <X className="h-4 w-4" />
            </Button>
          )}

          {isPropertyDropdownOpen && propertySearchResults.length > 0 && (
            <div className="absolute z-50 w-full mt-1 bg-popover border rounded-md shadow-md max-h-80 overflow-y-auto">
              {propertySearchResults.map((result) => (
                <div
                  key={result.value}
                  className="px-3 py-2 text-popover-foreground hover:bg-accent hover:text-accent-foreground cursor-pointer border-b border-border last:border-b-0 transition-colors"
                  onClick={() => selectProperty(result)}
                  title={result.value}
                >
                  <div className="text-sm flex items-center gap-2">
                    <Columns2 className="h-4 w-4 text-muted-foreground" />
                    <span className="truncate">{result.label} - {result.value}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {selectedProperty && (
        <div className="space-y-4">
          <Card>
            <CardContent className="pt-4">
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Columns2 className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-mono text-foreground break-all">{propertyIri}</span>
                </div>
                {getLiteralAttributes().map((prop, idx) => (
                  <div key={idx}>
                    <span className="text-sm font-medium text-muted-foreground">
                      {prop.predicate.split('/').pop()?.split('#').pop() || prop.predicate}:
                    </span>
                    <span className="text-sm text-foreground ml-1">{prop.display}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {getDomainRange().length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">{t('search:properties.domainRange')}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-2">
                    {getDomainRange().map((n, idx) => (
                      <Badge key={idx} variant="secondary" className="text-xs">
                        {n.predicate.split('#').pop() || n.predicate}: {n.display.split('#').pop() || n.display}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader>
                <CardTitle className="text-lg">{t('search:properties.linkedCatalogObjects')}</CardTitle>
              </CardHeader>
              <CardContent>
                {semanticLinks.length === 0 ? (
                  <p className="text-sm text-center text-muted-foreground">{t('search:properties.noCatalogObjects')}</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {semanticLinks.map((link) => {
                      const typeLabel = link.entity_type === 'uc_column'
                        ? t('search:properties.assignDialog.ucColumn')
                        : link.entity_type === 'uc_table'
                        ? t('search:properties.assignDialog.ucTable')
                        : link.entity_type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
                      const Icon = link.entity_type === 'data_contract_property' ? FileText : link.entity_type === 'uc_column' ? Columns2 : Shapes;
                      return (
                        <Badge
                          key={link.id}
                          variant="outline"
                          className="text-xs inline-flex items-center gap-1"
                          title={`${typeLabel}: ${link.entity_name || link.entity_id}`}
                        >
                          <Icon className="h-3 w-3" /> {link.entity_name || link.entity_id}
                        </Badge>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="pt-4">
            <Button variant="outline" onClick={() => setAssignDialogOpen(true)} disabled={!selectedProperty}>
              <Link2 className="h-4 w-4 mr-2" />
              {t('search:properties.assignToProperty')}
            </Button>
          </div>
        </div>
      )}

      <Dialog open={assignDialogOpen} onOpenChange={setAssignDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('search:properties.assignDialog.title')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {selectedProperty && (
              <div className="text-sm">
                <p className="font-medium">{selectedProperty.label}</p>
                <p className="text-muted-foreground font-mono text-xs">{selectedProperty.value}</p>
              </div>
            )}

            <div className="space-y-2">
              <label className="text-sm font-medium">{t('search:properties.assignDialog.targetType')}</label>
              <Select value={assignTargetType} onValueChange={handleAssignTargetTypeChange}>
                <SelectTrigger>
                  <SelectValue placeholder={t('search:properties.assignDialog.selectTargetType')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="data_contract_property">{t('search:properties.assignDialog.dataContractProperty')}</SelectItem>
                  <SelectItem value="uc_column">{t('search:properties.assignDialog.ucColumn')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {assignTargetType === 'data_contract_property' && (
              <>
                <div className="space-y-2">
                  <label className="text-sm font-medium">{t('search:properties.assignDialog.contract')}</label>
                  <Select value={selectedContractId} onValueChange={(v) => { setSelectedContractId(v); setSelectedSchemaName(''); setSelectedPropertyEntityId(''); }}>
                    <SelectTrigger>
                      <SelectValue placeholder={t('search:properties.assignDialog.selectContract')} />
                    </SelectTrigger>
                    <SelectContent>
                      {contracts.map((c) => (
                        <SelectItem key={c.id} value={c.id}>
                          {c.name || c.info?.title || c.id}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {selectedContractId && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t('search:properties.assignDialog.schema')}</label>
                    <Select value={selectedSchemaName} onValueChange={(v) => { setSelectedSchemaName(v); setSelectedPropertyEntityId(''); }}>
                      <SelectTrigger>
                        <SelectValue placeholder={t('search:properties.assignDialog.selectSchema')} />
                      </SelectTrigger>
                      <SelectContent>
                        {schemas.map((s: { name: string }) => (
                          <SelectItem key={s.name} value={s.name}>{s.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                {selectedSchemaName && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t('search:properties.assignDialog.property')}</label>
                    <Select value={selectedPropertyEntityId} onValueChange={setSelectedPropertyEntityId}>
                      <SelectTrigger>
                        <SelectValue placeholder={t('search:properties.assignDialog.selectProperty')} />
                      </SelectTrigger>
                      <SelectContent>
                        {properties.map((p: any) => {
                          const entityId = `${selectedContractId}#${selectedSchemaName}#${p.name}`;
                          return (
                            <SelectItem key={entityId} value={entityId}>
                              {p.name}
                            </SelectItem>
                          );
                        })}
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </>
            )}

            {assignTargetType === 'uc_column' && (
              <div className="space-y-2">
                <Button variant="outline" className="w-full" onClick={() => setUCAssetDialogOpen(true)}>
                  {t('search:properties.assignDialog.browseUCColumn')}
                </Button>
              </div>
            )}

            <div className="flex justify-end space-x-2 pt-4">
              <Button variant="outline" onClick={() => setAssignDialogOpen(false)}>{t('common:actions.cancel')}</Button>
              {assignTargetType === 'data_contract_property' ? (
                <Button onClick={handleAssign} disabled={!selectedPropertyEntityId}>{t('common:actions.assign')}</Button>
              ) : null}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <UCAssetLookupDialog
        isOpen={ucAssetDialogOpen}
        onOpenChange={setUCAssetDialogOpen}
        onSelect={handleUCColumnSelect}
        title={t('search:properties.assignDialog.ucColumnTitle')}
        allowedTypes={[UCAssetType.TABLE, UCAssetType.VIEW, UCAssetType.MATERIALIZED_VIEW]}
        includeColumns={true}
      />
    </div>
  );
}

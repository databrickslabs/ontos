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
import { Shapes, Columns2, FileText, Package, Globe, X, Link2 } from 'lucide-react';

type ConceptItem = { value: string; label: string; type: 'class' };
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

interface ConceptsSearchProps {
  initialQuery?: string;
  initialSelectedConcept?: ConceptItem | null;
}

export default function ConceptsSearch({
  initialQuery = '',
  initialSelectedConcept = null
}: ConceptsSearchProps) {
  const { get, post } = useApi();
  const { toast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation(['search', 'common']);

  const [conceptSearchQuery, setConceptSearchQuery] = useState(initialQuery);
  const [conceptSearchResults, setConceptSearchResults] = useState<ConceptItem[]>([]);
  const [isConceptDropdownOpen, setIsConceptDropdownOpen] = useState(false);
  const [selectedConcept, setSelectedConcept] = useState<ConceptItem | null>(initialSelectedConcept);
  const [conceptIri, setConceptIri] = useState('');
  const [_conceptLabel, setConceptLabel] = useState('');
  const [conceptNeighbors, setConceptNeighbors] = useState<Neighbor[]>([]);
  const [semanticLinks, setSemanticLinks] = useState<EnrichedSemanticLink[]>([]);

  // Assign to Object dialog
  const [assignDialogOpen, setAssignDialogOpen] = useState(false);
  const [selectedEntityType, setSelectedEntityType] = useState<string>('');
  const [selectedEntityId, setSelectedEntityId] = useState<string>('');
  const [availableEntities, setAvailableEntities] = useState<any[]>([]);

  // Update URL when state changes - only manages concepts-specific params
  const updateUrl = (updates: Partial<{
    query: string;
    conceptIri: string;
  }>) => {
    const params = new URLSearchParams();

    // Get current values from URL for params we're not updating
    const currentParams = new URLSearchParams(location.search);
    const currentQuery = updates.query !== undefined ? updates.query : currentParams.get('query') || '';
    const currentIri = updates.conceptIri !== undefined ? updates.conceptIri : currentParams.get('iri') || '';

    if (currentQuery) {
      params.set('query', currentQuery);
    }
    if (currentIri) {
      params.set('iri', currentIri);
    }

    const queryString = params.toString();
    const newUrl = queryString ? `/search/concepts?${queryString}` : '/search/concepts';
    navigate(newUrl, { replace: true });
  };

  // Load initial state from URL
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const urlQuery = params.get('query');
    const urlIri = params.get('iri');

    if (urlQuery && urlQuery !== initialQuery) {
      setConceptSearchQuery(urlQuery);
    }

    if (urlIri) {
      // Load concept from IRI using the exact IRI endpoint
      const loadConceptFromIri = async () => {
        try {
          const res = await get<{ concept: any }>(`/api/semantic-models/concepts/${encodeURIComponent(urlIri)}`);
          if (res.data && res.data.concept) {
            const concept = res.data.concept;
            const conceptItem: ConceptItem = {
              value: concept.iri,
              label: concept.label || concept.iri.split(/[/#]/).pop() || concept.iri,
              type: 'class'
            };
            await selectConcept(conceptItem);
          }
        } catch (error) {
          console.error('Error loading concept from URL:', error);
        }
      };
      loadConceptFromIri();
    }
  }, [location.search]);

  // Search concepts as user types
  useEffect(() => {
    const searchConcepts = async () => {
      if (!conceptSearchQuery.trim()) {
        setConceptSearchResults([]);
        setIsConceptDropdownOpen(false);
        updateUrl({ query: '' });
        return;
      }

      try {
        const res = await get<ConceptItem[]>(`/api/semantic-models/concepts?q=${encodeURIComponent(conceptSearchQuery)}&limit=50`);
        setConceptSearchResults(res.data || []);
        setIsConceptDropdownOpen((res.data || []).length > 0);
        updateUrl({ query: conceptSearchQuery });
      } catch (error) {
        console.error('Error searching concepts:', error);
        setConceptSearchResults([]);
        setIsConceptDropdownOpen(false);
      }
    };

    const timer = setTimeout(searchConcepts, 250);
    return () => clearTimeout(timer);
  }, [conceptSearchQuery]);

  const clearSearch = () => {
    setConceptSearchQuery('');
    setSelectedConcept(null);
    setConceptIri('');
    setConceptLabel('');
    setConceptNeighbors([]);
    setSemanticLinks([]);
    setIsConceptDropdownOpen(false);
    updateUrl({ query: '', conceptIri: '' });
  };

  // Select a concept and load its details
  const selectConcept = async (concept: ConceptItem) => {
    setSelectedConcept(concept);
    setConceptIri(concept.value);

    // Use label if available, otherwise extract last part of IRI
    let displayLabel = concept.label;
    if (!displayLabel || displayLabel.trim() === concept.value) {
      if (concept.value.includes('#')) {
        displayLabel = concept.value.split('#').pop() || concept.value;
      } else if (concept.value.includes('/')) {
        displayLabel = concept.value.split('/').pop() || concept.value;
      } else {
        displayLabel = concept.value;
      }
    }

    setConceptLabel(displayLabel);
    setConceptSearchQuery(`${displayLabel} - ${concept.value}`);
    setIsConceptDropdownOpen(false);
    updateUrl({ conceptIri: concept.value });

    // Load neighbors for this concept
    try {
      const res = await get<Neighbor[]>(`/api/semantic-models/neighbors?iri=${encodeURIComponent(concept.value)}&limit=200`);
      setConceptNeighbors(res.data || []);
    } catch (error) {
      console.error('Error loading neighbors:', error);
      setConceptNeighbors([]);
    }

    // Load semantic links (catalog objects linked to this concept)
    try {
      const res = await get<SemanticLink[]>(`/api/semantic-links/iri/${encodeURIComponent(concept.value)}`);
      const links = res.data || [];

      // Enrich semantic links with entity names
      const enrichedLinks = await enrichSemanticLinksWithNames(links);
      setSemanticLinks(enrichedLinks);
    } catch (error) {
      console.error('Error loading semantic links:', error);
      setSemanticLinks([]);
    }
  };

  // Navigate to a related concept (parent/subclass)
  const navigateToConcept = async (iri: string) => {
    const label = conceptNeighbors.find(n => n.stepIri === iri)?.display || iri.split('/').pop() || iri.split('#').pop() || iri;
    const conceptItem: ConceptItem = {
      value: iri,
      label: label,
      type: 'class'
    };
    await selectConcept(conceptItem);
  };

  // Get parent classes from neighbors
  const getParentClasses = () => {
    return conceptNeighbors.filter(n =>
      n.direction === 'outgoing' &&
      (n.predicate.includes('subClassOf') || n.predicate.includes('rdfs:subClassOf')) &&
      n.stepIsResource
    );
  };

  // Get subclasses from neighbors
  const getSubclasses = () => {
    return conceptNeighbors.filter(n =>
      n.direction === 'incoming' &&
      (n.predicate.includes('subClassOf') || n.predicate.includes('rdfs:subClassOf')) &&
      n.stepIsResource
    );
  };

  // Get related properties
  const getRelatedProperties = () => {
    return conceptNeighbors.filter(n =>
      n.displayType === 'property' ||
      n.predicate.includes('domain') ||
      n.predicate.includes('range')
    );
  };

  // Get linked catalog objects from semantic links
  const getCatalogObjects = () => {
    return semanticLinks;
  };

  // Enrich semantic links with readable entity names
  const enrichSemanticLinksWithNames = async (links: SemanticLink[]): Promise<EnrichedSemanticLink[]> => {
    const enrichedLinks: EnrichedSemanticLink[] = [];

    for (const link of links) {
      try {
        let entityName = link.entity_id;
        let endpoint = '';

        switch (link.entity_type) {
          case 'data_product':
            endpoint = `/api/data-products/${link.entity_id}`;
            break;
          case 'data_contract':
            endpoint = `/api/data-contracts/${link.entity_id}`;
            break;
          case 'data_domain':
            endpoint = `/api/data-domains/${link.entity_id}`;
            break;
          case 'data_contract_schema': {
            const [contractId, schemaName] = String(link.entity_id).split('#');
            if (contractId) {
              const contractRes = await get<any>(`/api/data-contracts/${contractId}`);
              const contractTitle = contractRes.data?.name || contractRes.data?.info?.title || contractId;
              entityName = `${contractTitle}#${schemaName || ''}`.trim();
            }
            enrichedLinks.push({ ...link, entity_name: entityName });
            continue;
          }
          case 'data_contract_property': {
            const [contractId, schemaName, propertyName] = String(link.entity_id).split('#');
            if (contractId) {
              const contractRes = await get<any>(`/api/data-contracts/${contractId}`);
              const contractTitle = contractRes.data?.name || contractRes.data?.info?.title || contractId;
              entityName = `${contractTitle}#${schemaName || ''}.${propertyName || ''}`.trim();
            }
            enrichedLinks.push({ ...link, entity_name: entityName });
            continue;
          }
          default:
            enrichedLinks.push({ ...link, entity_name: link.entity_id });
            continue;
        }

        const entityRes = await get<any>(endpoint);
        if (entityRes.data && !entityRes.error) {
          entityName = entityRes.data.name || entityRes.data.info?.title || entityRes.data.title || link.entity_id;
        }

        enrichedLinks.push({ ...link, entity_name: entityName });
      } catch (error) {
        console.error("Error fetching details for", link.entity_type, ":", link.entity_id, error);
        enrichedLinks.push({ ...link, entity_name: link.entity_id });
      }
    }

    return enrichedLinks;
  };

  // Load entities for assignment
  const loadEntitiesForType = async (entityType: string) => {
    try {
      let endpoint = '';
      switch (entityType) {
        case 'data_product':
          endpoint = '/api/data-products';
          break;
        case 'data_contract':
          endpoint = '/api/data-contracts';
          break;
        case 'data_domain':
          endpoint = '/api/data-domains';
          break;
        default:
          return;
      }

      const res = await get<any[]>(endpoint);
      setAvailableEntities(res.data || []);
    } catch (error) {
      console.error('Error loading entities:', error);
      setAvailableEntities([]);
    }
  };

  // Handle entity type selection
  const handleEntityTypeChange = (entityType: string) => {
    setSelectedEntityType(entityType);
    setSelectedEntityId('');
    loadEntitiesForType(entityType);
  };

  // Navigate to entity detail page
  const navigateToEntity = (link: SemanticLink) => {
    let path = '';
    switch (link.entity_type) {
      case 'data_product':
        path = `/data-products/${link.entity_id}`;
        break;
      case 'data_contract':
        path = `/data-contracts/${link.entity_id}`;
        break;
      case 'data_domain':
        path = `/data-domains/${link.entity_id}`;
        break;
      default:
        toast({
          title: t('common:toast.error'),
          description: t('search:concepts.messages.navigationError', { entityType: link.entity_type }),
          variant: 'destructive'
        });
        return;
    }
    navigate(path);
  };

  // Create semantic link
  const handleAssignToObject = async () => {
    if (!selectedConcept || !selectedEntityType || !selectedEntityId) {
      toast({
        title: t('common:toast.error'),
        description: t('search:concepts.messages.assignError'),
        variant: 'destructive'
      });
      return;
    }

    try {
      const res = await post('/api/semantic-links/', {
        entity_id: selectedEntityId,
        entity_type: selectedEntityType,
        iri: selectedConcept.value,
      });

      if (res.error) {
        throw new Error(res.error);
      }

      const entityTypeLabel = selectedEntityType === 'data_product' ? t('search:concepts.assignDialog.dataProduct') :
                              selectedEntityType === 'data_contract' ? t('search:concepts.assignDialog.dataContract') :
                              t('search:concepts.assignDialog.dataDomain');

      toast({
        title: t('common:toast.success'),
        description: t('search:concepts.messages.linkedSuccess', {
          label: selectedConcept.label,
          entityType: entityTypeLabel,
          entityId: selectedEntityId
        }),
      });

      setAssignDialogOpen(false);
      setSelectedEntityType('');
      setSelectedEntityId('');

      // Reload semantic links
      await selectConcept(selectedConcept);
    } catch (error: any) {
      toast({
        title: t('common:toast.error'),
        description: error.message || t('search:concepts.messages.assignFailed'),
        variant: 'destructive'
      });
    }
  };

  return (
    <div className="space-y-6">
      {/* Search Section */}
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">{t('search:concepts.searchAndSelect')}</p>
        <div className="relative">
          <Input
            value={conceptSearchQuery}
            onChange={(e) => setConceptSearchQuery(e.target.value)}
            onFocus={() => setIsConceptDropdownOpen(conceptSearchResults.length > 0)}
            placeholder={t('search:concepts.searchPlaceholder')}
            className="w-full"
          />
          {(conceptSearchQuery || selectedConcept) && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute right-1 top-1 h-7 w-7"
              onClick={clearSearch}
              aria-label={t('search:concepts.clear')}
            >
              <X className="h-4 w-4" />
            </Button>
          )}

          {/* Search Results Dropdown */}
          {isConceptDropdownOpen && conceptSearchResults.length > 0 && (
            <div className="absolute z-50 w-full mt-1 bg-popover border rounded-md shadow-md max-h-80 overflow-y-auto">
              {conceptSearchResults.map((result) => (
                <div
                  key={result.value}
                  className="px-3 py-2 text-popover-foreground hover:bg-accent hover:text-accent-foreground cursor-pointer border-b border-border last:border-b-0 transition-colors"
                  onClick={() => selectConcept(result)}
                  title={result.value}
                >
                  <div className="text-sm flex items-center gap-2">
                    <Shapes className="h-4 w-4 text-muted-foreground" />
                    <span className="truncate">{result.label} - {result.value}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Selected Concept Details */}
      {selectedConcept && (
        <div className="space-y-4">
          {/* Concept Info - Show ALL assigned properties */}
          <Card>
            <CardContent className="pt-4">
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Shapes className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-mono text-foreground break-all">{conceptIri}</span>
                </div>
                {conceptNeighbors.filter(n =>
                  n.direction === 'outgoing' &&
                  n.displayType === 'literal' &&
                  !n.predicate.includes('subClassOf') &&
                  !n.predicate.includes('type')
                ).map((prop, idx) => (
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

          {/* Three Column Layout */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Concept Hierarchy */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">{t('search:concepts.conceptHierarchy')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <h3 className="text-sm font-medium text-muted-foreground mb-2">{t('search:concepts.parentClasses')}</h3>
                  <div className="space-y-2">
                    {getParentClasses().length === 0 ? (
                      <p className="text-sm text-muted-foreground">{t('search:concepts.noParentClasses')}</p>
                    ) : (
                      getParentClasses().map((parent, idx) => (
                        <Badge
                          key={idx}
                          variant="outline"
                          className="cursor-pointer hover:bg-accent inline-flex items-center gap-1"
                          onClick={() => parent.stepIri && navigateToConcept(parent.stepIri)}
                          title={parent.stepIri || parent.display}
                        >
                          <Shapes className="h-3 w-3" />
                          {parent.display.split('#').pop() || parent.display.split('/').pop() || parent.display}
                        </Badge>
                      ))
                    )}
                  </div>
                </div>

                <div>
                  <h3 className="text-sm font-medium text-muted-foreground mb-2">{t('search:concepts.subclasses')}</h3>
                  <div className="flex flex-wrap gap-2">
                    {getSubclasses().length === 0 ? (
                      <p className="text-sm text-muted-foreground">{t('search:concepts.noSubclasses')}</p>
                    ) : (
                      getSubclasses().map((sub, idx) => (
                        <Badge
                          key={idx}
                          variant="outline"
                          className="cursor-pointer hover:bg-accent inline-flex items-center gap-1"
                          onClick={() => sub.stepIri && navigateToConcept(sub.stepIri)}
                          title={sub.stepIri || sub.display}
                        >
                          <Shapes className="h-3 w-3" />
                          {sub.display.split('#').pop() || sub.display.split('/').pop() || sub.display}
                        </Badge>
                      ))
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Related Properties */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">{t('search:concepts.relatedProperties')}</CardTitle>
              </CardHeader>
              <CardContent>
                {getRelatedProperties().length === 0 ? (
                  <p className="text-sm text-center text-muted-foreground">{t('search:concepts.noRelatedProperties')}</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {getRelatedProperties().map((prop, idx) => (
                      <Badge key={idx} variant="secondary" className="text-xs inline-flex items-center gap-1" title={prop.display}>
                        <Columns2 className="h-3 w-3" />
                        {prop.display.split('#').pop() || prop.display.split('/').pop() || prop.display}
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Linked Catalog Objects */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">{t('search:concepts.linkedCatalogObjects')}</CardTitle>
              </CardHeader>
              <CardContent>
                {getCatalogObjects().length === 0 ? (
                  <p className="text-sm text-center text-muted-foreground">{t('search:concepts.noCatalogObjects')}</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {getCatalogObjects().map((link) => {
                      const typeLabel = link.entity_type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
                      const Icon = link.entity_type === 'data_contract'
                        ? FileText
                        : link.entity_type === 'data_product'
                        ? Package
                        : link.entity_type === 'data_domain'
                        ? Globe
                        : link.entity_type === 'data_contract_schema'
                        ? Shapes
                        : link.entity_type === 'data_contract_property'
                        ? Columns2
                        : FileText;
                      return (
                        <Badge
                          key={link.id}
                          variant="outline"
                          className="text-xs inline-flex items-center gap-1 cursor-pointer hover:bg-accent transition-colors"
                          onClick={() => navigateToEntity(link)}
                          title={`${typeLabel}: ${link.entity_name || link.entity_id} • ${link.iri}`}
                        >
                          <Icon className="h-3 w-3" /> {typeLabel}: {link.entity_name || link.entity_id}
                        </Badge>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Assign to Concept Button */}
          <div className="pt-4">
            <Button
              variant="outline"
              onClick={() => setAssignDialogOpen(true)}
              disabled={!selectedConcept}
            >
              <Link2 className="h-4 w-4 mr-2" />
              {t('search:concepts.assignToConcept')}
            </Button>
          </div>
        </div>
      )}

      {/* Assign to Concept Dialog */}
      <Dialog open={assignDialogOpen} onOpenChange={setAssignDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('search:concepts.assignDialog.title')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {selectedConcept && (
              <div className="text-sm">
                <p className="font-medium">{selectedConcept.label}</p>
                <p className="text-muted-foreground font-mono text-xs">{selectedConcept.value}</p>
              </div>
            )}

            <div className="space-y-2">
              <label className="text-sm font-medium">{t('search:concepts.assignDialog.entityType')}</label>
              <Select value={selectedEntityType} onValueChange={handleEntityTypeChange}>
                <SelectTrigger>
                  <SelectValue placeholder={t('search:concepts.assignDialog.selectEntityType')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="data_product">{t('search:concepts.assignDialog.dataProduct')}</SelectItem>
                  <SelectItem value="data_contract">{t('search:concepts.assignDialog.dataContract')}</SelectItem>
                  <SelectItem value="data_domain">{t('search:concepts.assignDialog.dataDomain')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {selectedEntityType && (
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  {selectedEntityType === 'data_product' ? t('search:concepts.assignDialog.dataProduct') :
                   selectedEntityType === 'data_contract' ? t('search:concepts.assignDialog.dataContract') :
                   t('search:concepts.assignDialog.dataDomain')}
                </label>
                <Select value={selectedEntityId} onValueChange={setSelectedEntityId}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('search:concepts.assignDialog.selectEntity', { 
                      entityType: selectedEntityType === 'data_product' ? t('search:concepts.assignDialog.dataProduct') :
                                  selectedEntityType === 'data_contract' ? t('search:concepts.assignDialog.dataContract') :
                                  t('search:concepts.assignDialog.dataDomain')
                    })} />
                  </SelectTrigger>
                  <SelectContent>
                    {availableEntities.map((entity) => (
                      <SelectItem key={entity.id} value={entity.id}>
                        {entity.name || entity.info?.title || entity.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="flex justify-end space-x-2 pt-4">
              <Button variant="outline" onClick={() => setAssignDialogOpen(false)}>
                {t('common:actions.cancel')}
              </Button>
              <Button
                onClick={handleAssignToObject}
                disabled={!selectedEntityType || !selectedEntityId}
              >
                {t('common:actions.assign')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
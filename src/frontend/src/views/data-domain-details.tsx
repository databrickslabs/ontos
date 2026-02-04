import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/use-api';
import { useToast } from '@/hooks/use-toast';
import { Button } from '@/components/ui/button';
// Label - unused
// import { Label } from '@/components/ui/label';
import EntityMetadataPanel from '@/components/metadata/entity-metadata-panel';
// Preview handled in EntityMetadataPanel
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import TagChip from '@/components/ui/tag-chip';
import { Separator } from '@/components/ui/separator';
import { ArrowLeft, Edit3, Users, Tag, Hash, CalendarDays, UserCircle, ListTree, ChevronsUpDown, Plus } from 'lucide-react';
import ConceptSelectDialog from '@/components/semantic/concept-select-dialog';
import LinkedConceptChips from '@/components/semantic/linked-concept-chips';
import type { EntitySemanticLink } from '@/types/semantic-link';
import { DataDomain } from '@/types/data-domain';
import useBreadcrumbStore from '@/stores/breadcrumb-store';
import { RelativeDate } from '@/components/common/relative-date';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AlertCircle } from 'lucide-react';
// import { Loader2 } from 'lucide-react'; // Unused
import { DetailViewSkeleton } from '@/components/common/list-view-skeleton';
import { DataDomainMiniGraph } from '@/components/data-domains/data-domain-mini-graph';
import { DataDomainFormDialog } from '@/components/data-domains/data-domain-form-dialog';
import { CommentSidebar } from '@/components/comments';
import { DataTable } from '@/components/ui/data-table';
import { ColumnDef } from '@tanstack/react-table';
import { useDomains } from '@/hooks/use-domains';
import { TeamFormDialog } from '@/components/teams/team-form-dialog';
import { Team, TeamSummary } from '@/types/team';

// Helper to check API response (can be moved to a shared util if used in many places)
const checkApiResponse = <T,>(response: { data?: T | { detail?: string }, error?: string | null | undefined }, name: string): T => {
    if (response.error) throw new Error(`${name} fetch failed: ${response.error}`);
    if (response.data && typeof response.data === 'object' && response.data !== null && 'detail' in response.data && typeof (response.data as { detail: string }).detail === 'string') {
        throw new Error(`${name} fetch failed: ${(response.data as { detail: string }).detail}`);
    }
    if (response.data === null || response.data === undefined) throw new Error(`${name} fetch returned null or undefined data.`);
    return response.data as T;
};

interface InfoItemProps {
  label: string;
  icon?: React.ReactNode;
  value?: string | React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}

const InfoItem: React.FC<InfoItemProps> = ({ label, value, icon, children, className }) => (
  <div className={`mb-3 ${className}`}>
    <p className="text-sm font-medium text-muted-foreground flex items-center">
      {icon && React.cloneElement(icon as React.ReactElement, { className: 'mr-2 h-4 w-4' })}
      {label}
    </p>
    {value && <p className="text-md text-foreground mt-0.5">{value}</p>}
    {children && <div className="mt-0.5">{children}</div>}
  </div>
);

// Column definitions for child domains table
const createChildDomainsColumns = (_navigate: (path: string) => void): ColumnDef<any>[] => [
  {
    accessorKey: "name",
    header: "Name",
    cell: ({ row }) => (
      <Link
        to={`/data-domains/${row.original.id}`}
        className="font-medium text-primary hover:underline"
      >
        {row.getValue("name")}
      </Link>
    ),
  },
  {
    accessorKey: "id",
    header: "ID",
    cell: ({ row }) => (
      <code className="text-xs bg-muted px-2 py-1 rounded">
        {row.getValue("id")}
      </code>
    ),
  },
];

// Column definitions for teams table
const createTeamsColumns = (_navigate: (path: string) => void, onEdit: (teamId: string) => void): ColumnDef<TeamSummary>[] => [
  {
    accessorKey: "name",
    header: "Team Name",
    cell: ({ row }) => (
      <Link
        to={`/teams/${row.original.id}`}
        className="font-medium text-primary hover:underline"
      >
        {row.getValue("name")}
      </Link>
    ),
  },
  {
    accessorKey: "title",
    header: "Title",
    cell: ({ row }) => {
      const title = row.getValue("title") as string;
      return title || <span className="text-muted-foreground italic">No title</span>;
    },
  },
  {
    accessorKey: "member_count",
    header: "Members",
    cell: ({ row }) => (
      <Badge variant="secondary" className="text-xs">
        {row.getValue("member_count")} members
      </Badge>
    ),
  },
  {
    id: "actions",
    header: "Actions",
    cell: ({ row }) => (
      <Button
        variant="ghost"
        size="sm"
        onClick={() => onEdit(row.original.id)}
        className="text-xs px-2 py-1"
      >
        <Edit3 className="w-3 h-3 mr-1" />
        Edit
      </Button>
    ),
  },
];

// Define the linked asset type
type LinkedAsset = {
  id: string;
  name: string;
  type?: string;
  path?: string;
  domainId?: string;
  version?: string;
  status?: string;
};

// Component for displaying linked assets
interface LinkedAssetsViewProps {
  assets: LinkedAsset[];
}

const LinkedAssetsView: React.FC<LinkedAssetsViewProps> = ({ assets }) => {
  const { t } = useTranslation(['common']);
  const { getDomainName } = useDomains();
  // Define columns for the linked assets table
  const columns: ColumnDef<LinkedAsset>[] = [
    {
      accessorKey: "name",
      header: "Asset Name",
      cell: ({ row }) => (
        <div className="font-medium">{row.getValue("name")}</div>
      ),
    },
    {
      accessorKey: "type",
      header: "Type",
      cell: ({ row }) => {
        const type = row.getValue("type") as string;
        return (
          <Badge variant="outline" className="text-xs">
            {type?.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase()) || 'Unknown'}
          </Badge>
        );
      },
    },
    {
      accessorKey: "path",
      header: "Path",
      cell: ({ row }) => {
        const path = row.getValue("path") as string;
        return path ? (
          <code className="text-sm text-muted-foreground bg-muted px-2 py-1 rounded">
            {path}
          </code>
        ) : null;
      },
    },
    {
      accessorKey: "domainId",
      header: "Domain",
      cell: ({ row }) => {
        const asset = row.original;
        const domainName = asset.domainId ? getDomainName(asset.domainId) : null;
        return domainName || t('common:states.notAssigned');
      },
    },
  ];

  if (assets.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No linked assets found
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-semibold">Linked Assets</h3>
        <Badge variant="secondary" className="text-xs">
          {assets.length} total
        </Badge>
      </div>
      <DataTable
        columns={columns}
        data={assets}
        searchColumn="name"
      />
    </div>
  );
};

export default function DataDomainDetailsView() {
  const { t } = useTranslation(['data-domains', 'common']);
  const { domainId } = useParams<{ domainId: string }>();
  const navigate = useNavigate();
  const { get, post, delete: del } = useApi();
  const { toast } = useToast();
  
  const setStaticSegments = useBreadcrumbStore((state) => state.setStaticSegments);
  const setDynamicTitle = useBreadcrumbStore((state) => state.setDynamicTitle);

  const [domain, setDomain] = useState<DataDomain | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCommentSidebarOpen, setIsCommentSidebarOpen] = useState(false);
  const [iriDialogOpen, setIriDialogOpen] = useState(false);
  const [semanticLinks, setSemanticLinks] = useState<EntitySemanticLink[]>([]);
  const [_parentSemanticLinks, setParentSemanticLinks] = useState<EntitySemanticLink[]>([]);
  const [hierarchyConceptIris, setHierarchyConceptIris] = useState<string[]>([]);
  const [linkedAssets, setLinkedAssets] = useState<any[]>([]);
  const [domainTeams, setDomainTeams] = useState<TeamSummary[]>([]);
  const [teamDialogOpen, setTeamDialogOpen] = useState(false);
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null);
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);

  // Metadata: Rich Texts, Links, Documents
  interface RichTextItem { id: string; entity_id: string; entity_type: string; title: string; short_description?: string | null; content_markdown: string; created_at?: string; }
  interface LinkItem { id: string; entity_id: string; entity_type: string; title: string; short_description?: string | null; url: string; created_at?: string; }
  interface DocumentItem { id: string; entity_id: string; entity_type: string; title: string; short_description?: string | null; original_filename: string; content_type?: string | null; size_bytes?: number | null; storage_path: string; created_at?: string; }

  const [_richTexts, setRichTexts] = useState<RichTextItem[]>([]);
  const [_links, setLinks] = useState<LinkItem[]>([]);
  const [_documents, setDocuments] = useState<DocumentItem[]>([]);

  const [_addingNote, _setAddingNote] = useState(false);
  const [_noteTitle, _setNoteTitle] = useState('');
  const [_noteDesc, _setNoteDesc] = useState('');
  const [_noteContent, _setNoteContent] = useState('');

  const [_addingLink, _setAddingLink] = useState(false);
  const [_linkTitle, _setLinkTitle] = useState('');
  const [_linkDesc, _setLinkDesc] = useState('');
  const [_linkUrl, _setLinkUrl] = useState('');

  const [_uploadingDoc, _setUploadingDoc] = useState(false);
  const [_addingDoc, _setAddingDoc] = useState(false);
  const [_docTitle, _setDocTitle] = useState('');
  const [_docDesc, _setDocDesc] = useState('');
  const [_docFile, _setDocFile] = useState<File | null>(null);

  const fetchDomainHierarchyConceptIris = useCallback(async (domainId: string): Promise<string[]> => {
    const conceptIris: string[] = [];
    let currentDomainId = domainId;
    const visited = new Set<string>(); // Prevent infinite loops
    
    while (currentDomainId && !visited.has(currentDomainId)) {
      visited.add(currentDomainId);
      
      try {
        // Fetch domain details and semantic links for current domain
        const [domainRes, linksRes] = await Promise.all([
          get<DataDomain>(`/api/data-domains/${currentDomainId}`),
          get<EntitySemanticLink[]>(`/api/semantic-links/entity/data_domain/${currentDomainId}`)
        ]);
        
        const domainData = checkApiResponse(domainRes, 'Domain Details');
        
        // If this domain has semantic links, add the first IRI to our list
        if (linksRes.data && !linksRes.error && Array.isArray(linksRes.data) && linksRes.data.length > 0) {
          const firstConceptIri = linksRes.data[0].iri;
          if (firstConceptIri && !conceptIris.includes(firstConceptIri)) {
            conceptIris.push(firstConceptIri);
          }
        }
        
        // Move to parent domain
        currentDomainId = domainData.parent_id || '';
      } catch (error) {
        // If we can't fetch a domain in the hierarchy, break the chain
        break;
      }
    }
    
    return conceptIris;
  }, [get]);

  const fetchDomainDetails = useCallback(async (id: string) => {
    setIsLoading(true);
    setError(null);
    setDynamicTitle('Loading...');
    try {
      const [domainRes, linksRes] = await Promise.all([
        get<DataDomain>(`/api/data-domains/${id}`),
        get<EntitySemanticLink[]>(`/api/semantic-links/entity/data_domain/${id}`)
      ]);
      
      const data = checkApiResponse(domainRes, 'Data Domain Details');
      setDomain(data);
      setDynamicTitle(data.name);
      
      if (linksRes.data && !linksRes.error) {
        const links = Array.isArray(linksRes.data) ? linksRes.data : [];
        setSemanticLinks(links);

        // Transform semantic links to linked assets for the LinkedAssetsView
        const semanticAssets = links.map(link => ({
          id: link.entity_id,
          name: link.label || link.entity_id,
          type: link.entity_type,
          path: link.entity_id,
        }));

        // Fetch data contracts that reference this domain
        try {
          const contractsRes = await get(`/api/data-contracts?domain_id=${domainId}`);
          if (contractsRes.data && !contractsRes.error) {
            const contracts = Array.isArray(contractsRes.data) ? contractsRes.data : [];
            const contractAssets = contracts.map(contract => ({
              id: contract.id,
              name: contract.name,
              type: 'data_contract',
              path: contract.id,
              domainId: contract.domainId, // For domain name resolution
              version: contract.version,
              status: contract.status,
            }));

            // Combine semantic assets and contract assets
            setLinkedAssets([...semanticAssets, ...contractAssets]);
          } else {
            setLinkedAssets(semanticAssets);
          }
        } catch (error) {
          console.error('Error fetching contracts for domain:', error);
          setLinkedAssets(semanticAssets);
        }
      } else {
        setSemanticLinks([]);
        setLinkedAssets([]);
      }

      // Fetch hierarchy concept IRIs (starts from parent, then walks up)
      if (data.parent_id) {
        try {
          const conceptIris = await fetchDomainHierarchyConceptIris(data.parent_id);
          setHierarchyConceptIris(conceptIris);
          
          // Also set parent semantic links for backward compatibility
          if (conceptIris.length > 0) {
            const parentLinksRes = await get<EntitySemanticLink[]>(`/api/semantic-links/entity/data_domain/${data.parent_id}`);
            if (parentLinksRes.data && !parentLinksRes.error) {
              setParentSemanticLinks(Array.isArray(parentLinksRes.data) ? parentLinksRes.data : []);
            } else {
              setParentSemanticLinks([]);
            }
          } else {
            setParentSemanticLinks([]);
          }
        } catch {
          setHierarchyConceptIris([]);
          setParentSemanticLinks([]);
        }
      } else {
        setHierarchyConceptIris([]);
        setParentSemanticLinks([]);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to fetch domain details.');
      toast({
        title: 'Error Fetching Domain',
        description: err.message || 'Could not load domain details.',
        variant: 'destructive',
      });
      setDomain(null);
      setDynamicTitle('Error');
    }
    setIsLoading(false);
  }, [get, toast, setDynamicTitle, fetchDomainHierarchyConceptIris]);

  const entityType = 'data_domain';

  // Load all domains for parent selection in edit dialog
  const { domains, refetch: refetchDomains } = useDomains();

  // Available for future use
  // const truncate = (text?: string | null, maxLen: number = 80) => {
  //   if (!text) return '';
  //   return text.length > maxLen ? text.slice(0, maxLen - 1) + '…' : text;
  // };

  const addIri = async (iri: string) => {
    if (!domainId) return
    try {
      const res = await post<EntitySemanticLink>(`/api/semantic-links/`, {
        entity_id: domainId,
        entity_type: 'data_domain',
        iri,
      });
      if (res.error) throw new Error(res.error);
      await fetchDomainDetails(domainId);
      setIriDialogOpen(false);
      toast({ title: 'Linked', description: 'Business concept linked to data domain.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e.message || 'Failed to link business concept', variant: 'destructive' });
    }
  };

  const removeLink = async (linkId: string) => {
    try {
      const res = await del(`/api/semantic-links/${linkId}`);
      if (res.error) throw new Error(res.error);
      await fetchDomainDetails(domainId!);
      toast({ title: 'Unlinked', description: 'Business concept unlinked from data domain.' });
    } catch (e: any) {
      toast({ title: 'Error', description: e.message || 'Failed to unlink business concept', variant: 'destructive' });
    }
  };

  // Preview dialogs
  // const [previewNote, setPreviewNote] = useState<RichTextItem | null>(null);
  // const [previewLink, setPreviewLink] = useState<LinkItem | null>(null);
  // const [previewDoc, setPreviewDoc] = useState<DocumentItem | null>(null);
  // const [docPreviewUrl, setDocPreviewUrl] = useState<string | undefined>(undefined);

  const fetchMetadata = useCallback(async (id: string) => {
    try {
      const [rtResp, liResp, docResp] = await Promise.all([
        get<RichTextItem[]>(`/api/entities/${entityType}/${id}/rich-texts`),
        get<LinkItem[]>(`/api/entities/${entityType}/${id}/links`),
        get<DocumentItem[]>(`/api/entities/${entityType}/${id}/documents`),
      ]);
      setRichTexts(checkApiResponse(rtResp, 'Rich Texts'));
      setLinks(checkApiResponse(liResp, 'Links'));
      setDocuments(checkApiResponse(docResp, 'Documents'));
    } catch (err: any) {
      toast({ title: 'Metadata load failed', description: err.message || 'Could not load metadata.', variant: 'destructive' });
    }
  }, [get, toast]);

  const fetchDomainTeams = useCallback(async (domainId: string) => {
    try {
      const response = await get<TeamSummary[]>(`/api/teams?domain_id=${domainId}`);
      if (response.data && !response.error) {
        const teams = Array.isArray(response.data) ? response.data : [];
        setDomainTeams(teams);
      } else {
        setDomainTeams([]);
      }
    } catch (error) {
      console.error('Error fetching domain teams:', error);
      setDomainTeams([]);
    }
  }, [get]);

  const handleTeamDialogSuccess = (_team: Team) => {
    // Refresh domain teams after successful team operation
    if (domainId) {
      fetchDomainTeams(domainId);
    }
    setSelectedTeam(null);
  };

  const handleEditTeam = async (teamId: string) => {
    try {
      const response = await get<Team>(`/api/teams/${teamId}`);
      if (response.data && !response.error) {
        setSelectedTeam(response.data);
        setTeamDialogOpen(true);
      }
    } catch (error) {
      toast({
        variant: 'destructive',
        title: 'Error',
        description: 'Failed to load team details for editing.',
      });
    }
  };

  const handleCreateTeam = () => {
    setSelectedTeam(null);
    setTeamDialogOpen(true);
  };

  const handleEditSuccess = async (updated: DataDomain) => {
    // Refresh current domain data and the cached domains list
    setDomain(updated);
    if (domainId) {
      await fetchDomainDetails(domainId);
    }
    await refetchDomains();
  };

  useEffect(() => {
    setStaticSegments([{ label: 'Data Domains', path: '/data-domains' }]);
    if (domainId) {
      fetchDomainDetails(domainId);
      fetchMetadata(domainId);
      fetchDomainTeams(domainId);
    } else {
      setError("No Domain ID provided.");
      setDynamicTitle("Invalid Domain");
      setIsLoading(false);
    }
    return () => {
        setStaticSegments([]);
        setDynamicTitle(null);
    };
  }, [domainId, fetchDomainDetails, fetchMetadata, fetchDomainTeams, setStaticSegments, setDynamicTitle]);

  useEffect(() => {
    if (domain) {
      setDynamicTitle(domain.name);
    }
  }, [domain, setDynamicTitle]);

  if (isLoading) {
    return <DetailViewSkeleton cards={4} actionButtons={2} />;
  }

  if (error) {
    return (
      <div className="container mx-auto py-10">
        <Alert variant="destructive" className="mb-4">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
        </Alert>
        <Button variant="outline" onClick={() => navigate('/data-domains')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Data Domains
        </Button>
      </div>
    );
  }

  if (!domain) {
    return (
        <div className="container mx-auto py-10 text-center">
            <Alert className="mb-4">
                <AlertDescription>Data domain not found or could not be loaded.</AlertDescription>
            </Alert>
            <Button variant="outline" onClick={() => navigate('/data-domains')}>
                <ArrowLeft className="mr-2 h-4 w-4" /> Back to Data Domains
            </Button>
        </div>
    );
  }

  return (
    <div className="py-6 space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="outline" onClick={() => navigate('/data-domains')} size="sm">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to List
        </Button>
        <div className="flex items-center gap-2">
          <CommentSidebar
            entityType="data_domain"
            entityId={domainId!}
            isOpen={isCommentSidebarOpen}
            onToggle={() => setIsCommentSidebarOpen(!isCommentSidebarOpen)}
            className="h-8"
          />
          <Button variant="outline" size="sm" onClick={() => setIsEditDialogOpen(true)}>
              <Edit3 className="mr-2 h-4 w-4" /> Edit
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
            <CardTitle className="text-2xl font-bold flex items-center">
                <ListTree className="mr-3 h-7 w-7 text-primary" />{domain.name}
            </CardTitle>
            {domain.description && <CardDescription className="pt-1">{domain.description}</CardDescription>}
        </CardHeader>
        <CardContent className="pt-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2">
            <InfoItem label="ID" value={domain.id} icon={<Hash />} className="lg:col-span-1 md:col-span-2" />
            
            {domain.parent_info && (
              <InfoItem label="Parent Domain" icon={<ListTree />}>
                <Link to={`/data-domains/${domain.parent_info.id}`} className="text-primary hover:underline">
                  {domain.parent_info.name}
                </Link>
              </InfoItem>
            )}
             <InfoItem label="Children Count" value={domain.children_count?.toString() ?? '0'} icon={<ListTree />} />

            <InfoItem label="Owners" icon={<Users />}>
              {domain.owner && domain.owner.length > 0 ? (
                <div className="flex flex-wrap gap-1 mt-1">
                  {domain.owner.map((o, i) => <Badge key={i} variant="outline">{o}</Badge>)}
                </div>
              ) : t('common:states.notAssigned')}
            </InfoItem>

            <InfoItem label="Tags" icon={<Tag />}>
              {domain.tags && domain.tags.length > 0 ? (
                <div className="flex flex-wrap gap-1 mt-1">
                  {domain.tags.map((tag, i) => <TagChip key={i} tag={tag} size="sm" />)}
                </div>
              ) : t('common:states.none')}
            </InfoItem>
           
            <InfoItem label="Created By" value={domain.created_by || t('common:states.notAvailable')} icon={<UserCircle />} />
            <InfoItem label="Created At" icon={<CalendarDays />}>
                {domain.created_at ? <RelativeDate date={domain.created_at} /> : t('common:states.notAvailable')}
            </InfoItem>
            <InfoItem label="Last Updated At" icon={<CalendarDays />}>
                {domain.updated_at ? <RelativeDate date={domain.updated_at} /> : t('common:states.notAvailable')}
            </InfoItem>
            
            <InfoItem label="Linked Business Concepts" className="col-span-full">
              <LinkedConceptChips
                links={semanticLinks}
                onRemove={(id) => removeLink(id)}
                trailing={<Button size="sm" variant="outline" onClick={() => setIriDialogOpen(true)}>Add Concept</Button>}
              />
            </InfoItem>
        </CardContent>
      </Card>

      <Separator />

      {/* Domain Hierarchy Context */}
      {(domain.parent_info || (domain.children_info && domain.children_info.length > 0)) && (
        <Card className="mb-6">
          <CardHeader className='pb-2'>
            <CardTitle className="text-lg font-semibold flex items-center">
              <ChevronsUpDown className="h-5 w-5 mr-2 text-primary" />
              Domain Hierarchy Context
            </CardTitle>
          </CardHeader>
          <CardContent>
            <DataDomainMiniGraph currentDomain={domain} />
          </CardContent>
        </Card>
      )}

      {/* Child Data Domains */}
      {domain.children_count !== undefined && domain.children_count > 0 && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="text-xl flex items-center">
              <ListTree className="mr-2 h-5 w-5 text-primary"/>
              Child Data Domains ({domain.children_count})
            </CardTitle>
            <CardDescription>Directly nested data domains.</CardDescription>
          </CardHeader>
          <CardContent>
            {domain.children_info && domain.children_info.length > 0 ? (
              <DataTable
                columns={createChildDomainsColumns(navigate)}
                data={domain.children_info}
                searchColumn="name"
              />
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                No child domains found
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Domain Teams Section */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-xl flex items-center justify-between">
            <div className="flex items-center">
              <Users className="mr-2 h-5 w-5 text-primary"/>
              Domain Teams
              <Badge variant="secondary" className="ml-3 text-xs">
                {domainTeams.length} teams
              </Badge>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleCreateTeam}
              className="flex items-center gap-2"
            >
              <Plus className="w-4 h-4" />
              Create Team
            </Button>
          </CardTitle>
          <CardDescription>
            Teams assigned to this data domain. Teams inherit domain-specific permissions and responsibilities.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {domainTeams.length > 0 ? (
            <DataTable
              columns={createTeamsColumns(navigate, handleEditTeam)}
              data={domainTeams}
              searchColumn="name"
            />
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              <Users className="mx-auto h-12 w-12 mb-4 opacity-30" />
              <p className="text-lg font-medium">No teams assigned</p>
              <p className="text-sm">Create a team to assign it to this data domain.</p>
              <Button
                variant="outline"
                size="sm"
                onClick={handleCreateTeam}
                className="mt-4"
              >
                <Plus className="w-4 h-4 mr-2" />
                Create First Team
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Linked Assets Section */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-xl flex items-center">
            <Tag className="mr-2 h-5 w-5 text-primary"/>
            Linked Assets
          </CardTitle>
          <CardDescription>
            Assets (data products, contracts, etc.) linked to this data domain through semantic relationships.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <LinkedAssetsView assets={linkedAssets} />
        </CardContent>
      </Card>

      {/* Metadata Panel - Last Section */}
      <EntityMetadataPanel entityId={domainId!} entityType={entityType} />

      <ConceptSelectDialog
        isOpen={iriDialogOpen}
        onOpenChange={setIriDialogOpen}
        onSelect={addIri}
        parentConceptIris={hierarchyConceptIris}
      />

      <TeamFormDialog
        isOpen={teamDialogOpen}
        onOpenChange={setTeamDialogOpen}
        team={selectedTeam}
        onSubmitSuccess={handleTeamDialogSuccess}
        initialDomainId={selectedTeam ? undefined : domainId}
      />

      {/* Edit Domain Dialog */}
      <DataDomainFormDialog
        isOpen={isEditDialogOpen}
        onOpenChange={setIsEditDialogOpen}
        domain={domain}
        onSubmitSuccess={handleEditSuccess}
        allDomains={domains}
      />
    </div>
  );
} 
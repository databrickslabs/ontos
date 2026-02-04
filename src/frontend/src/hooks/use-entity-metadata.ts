import { useCallback, useEffect, useMemo, useState } from 'react';

// Note: entity-metadata-panel.tsx and costs.ts also define EntityKind - keep in sync
export type EntityKind = 'data_domain' | 'data_product' | 'data_contract' | 'dataset' | 'concept' | 'collection' | 'compliance_policy';

export interface RichTextItem { 
  id: string; 
  entity_id: string; 
  entity_type: EntityKind; 
  title: string; 
  short_description?: string | null; 
  content_markdown: string; 
  is_shared?: boolean;
  level?: number;
  inheritable?: boolean;
  created_at?: string; 
  updated_at?: string; 
}

export interface LinkItem { 
  id: string; 
  entity_id: string; 
  entity_type: EntityKind; 
  title: string; 
  short_description?: string | null; 
  url: string; 
  is_shared?: boolean;
  level?: number;
  inheritable?: boolean;
  created_at?: string; 
  updated_at?: string; 
}

export interface DocumentItem { 
  id: string; 
  entity_id: string; 
  entity_type: EntityKind; 
  title: string; 
  short_description?: string | null; 
  original_filename: string; 
  content_type?: string | null; 
  size_bytes?: number | null; 
  storage_path: string; 
  is_shared?: boolean;
  level?: number;
  inheritable?: boolean;
  created_at?: string; 
  updated_at?: string; 
}

export interface MetadataAttachment {
  id: string;
  entity_id: string;
  entity_type: string;
  asset_type: 'rich_text' | 'link' | 'document';
  asset_id: string;
  level_override?: number | null;
  created_by?: string | null;
  created_at?: string;
}

export interface SharedAssetListResponse {
  rich_texts: RichTextItem[];
  links: LinkItem[];
  documents: DocumentItem[];
}

export interface MergedMetadataResponse {
  rich_texts: RichTextItem[];
  links: LinkItem[];
  documents: DocumentItem[];
  sources: Record<string, string>;
}

export interface UseEntityMetadataResult {
  richTexts: RichTextItem[];
  links: LinkItem[];
  documents: DocumentItem[];
  attachments: MetadataAttachment[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export interface UseMergedMetadataResult {
  richTexts: RichTextItem[];
  links: LinkItem[];
  documents: DocumentItem[];
  sources: Record<string, string>;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export interface UseSharedAssetsResult {
  richTexts: RichTextItem[];
  links: LinkItem[];
  documents: DocumentItem[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Hook to fetch direct metadata for an entity (not inherited).
 */
export function useEntityMetadata(entityType: EntityKind, entityId: string | null | undefined): UseEntityMetadataResult {
  const [richTexts, setRichTexts] = useState<RichTextItem[]>([]);
  const [links, setLinks] = useState<LinkItem[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [attachments, setAttachments] = useState<MetadataAttachment[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!entityId) return;
    try {
      setLoading(true);
      setError(null);
      const [rt, li, docs, att] = await Promise.all([
        fetch(`/api/entities/${entityType}/${entityId}/rich-texts`).then(r => r.ok ? r.json() : Promise.reject(new Error(`rich-texts ${r.status}`))),
        fetch(`/api/entities/${entityType}/${entityId}/links`).then(r => r.ok ? r.json() : Promise.reject(new Error(`links ${r.status}`))),
        fetch(`/api/entities/${entityType}/${entityId}/documents`).then(r => r.ok ? r.json() : Promise.reject(new Error(`documents ${r.status}`))),
        fetch(`/api/entities/${entityType}/${entityId}/attachments`).then(r => r.ok ? r.json() : []),
      ]);
      setRichTexts(Array.isArray(rt) ? rt : []);
      setLinks(Array.isArray(li) ? li : []);
      setDocuments(Array.isArray(docs) ? docs : []);
      setAttachments(Array.isArray(att) ? att : []);
    } catch (e: any) {
      setError(e?.message || 'Failed to load metadata');
      setRichTexts([]);
      setLinks([]);
      setDocuments([]);
      setAttachments([]);
    } finally {
      setLoading(false);
    }
  }, [entityType, entityId]);

  useEffect(() => { refresh(); }, [refresh]);

  // Sort by level (ascending), then by created_at
  const value = useMemo(() => ({
    richTexts: richTexts.slice().sort((a, b) => (a.level ?? 50) - (b.level ?? 50) || new Date(a.created_at || '').getTime() - new Date(b.created_at || '').getTime()),
    links: links.slice().sort((a, b) => (a.level ?? 50) - (b.level ?? 50) || new Date(a.created_at || '').getTime() - new Date(b.created_at || '').getTime()),
    documents: documents.slice().sort((a, b) => (a.level ?? 50) - (b.level ?? 50) || new Date(a.created_at || '').getTime() - new Date(b.created_at || '').getTime()),
    attachments,
    loading,
    error,
    refresh,
  }), [richTexts, links, documents, attachments, loading, error, refresh]);

  return value;
}

/**
 * Hook to fetch merged metadata with inheritance from contracts.
 */
export function useMergedMetadata(
  entityType: EntityKind, 
  entityId: string | null | undefined,
  contractIds?: string[],
  maxLevel: number = 99
): UseMergedMetadataResult {
  const [richTexts, setRichTexts] = useState<RichTextItem[]>([]);
  const [links, setLinks] = useState<LinkItem[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [sources, setSources] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!entityId) return;
    try {
      setLoading(true);
      setError(null);
      
      const params = new URLSearchParams();
      if (contractIds && contractIds.length > 0) {
        params.set('contract_ids', contractIds.join(','));
      }
      params.set('max_level', String(maxLevel));
      
      const resp = await fetch(`/api/entities/${entityType}/${entityId}/metadata/merged?${params.toString()}`);
      if (!resp.ok) throw new Error(`merged metadata ${resp.status}`);
      
      const data: MergedMetadataResponse = await resp.json();
      setRichTexts(data.rich_texts || []);
      setLinks(data.links || []);
      setDocuments(data.documents || []);
      setSources(data.sources || {});
    } catch (e: any) {
      setError(e?.message || 'Failed to load merged metadata');
      setRichTexts([]);
      setLinks([]);
      setDocuments([]);
      setSources({});
    } finally {
      setLoading(false);
    }
  }, [entityType, entityId, contractIds?.join(','), maxLevel]);

  useEffect(() => { refresh(); }, [refresh]);

  return useMemo(() => ({
    richTexts,
    links,
    documents,
    sources,
    loading,
    error,
    refresh,
  }), [richTexts, links, documents, sources, loading, error, refresh]);
}

/**
 * Hook to fetch all shared metadata assets.
 */
export function useSharedAssets(entityType?: EntityKind): UseSharedAssetsResult {
  const [richTexts, setRichTexts] = useState<RichTextItem[]>([]);
  const [links, setLinks] = useState<LinkItem[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      const params = entityType ? `?entity_type=${entityType}` : '';
      const resp = await fetch(`/api/metadata/shared${params}`);
      if (!resp.ok) throw new Error(`shared assets ${resp.status}`);
      
      const data: SharedAssetListResponse = await resp.json();
      setRichTexts(data.rich_texts || []);
      setLinks(data.links || []);
      setDocuments(data.documents || []);
    } catch (e: any) {
      setError(e?.message || 'Failed to load shared assets');
      setRichTexts([]);
      setLinks([]);
      setDocuments([]);
    } finally {
      setLoading(false);
    }
  }, [entityType]);

  useEffect(() => { refresh(); }, [refresh]);

  return useMemo(() => ({
    richTexts: richTexts.slice().sort((a, b) => (a.level ?? 50) - (b.level ?? 50)),
    links: links.slice().sort((a, b) => (a.level ?? 50) - (b.level ?? 50)),
    documents: documents.slice().sort((a, b) => (a.level ?? 50) - (b.level ?? 50)),
    loading,
    error,
    refresh,
  }), [richTexts, links, documents, loading, error, refresh]);
}

/**
 * Attach a shared asset to an entity.
 */
export async function attachSharedAsset(
  entityType: EntityKind,
  entityId: string,
  assetType: 'rich_text' | 'link' | 'document',
  assetId: string,
  levelOverride?: number
): Promise<MetadataAttachment> {
  const resp = await fetch(`/api/entities/${entityType}/${entityId}/attachments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ 
      asset_type: assetType, 
      asset_id: assetId,
      level_override: levelOverride 
    }),
  });
  if (!resp.ok) throw new Error('Failed to attach shared asset');
  return resp.json();
}

/**
 * Detach a shared asset from an entity.
 */
export async function detachSharedAsset(
  entityType: EntityKind,
  entityId: string,
  assetType: 'rich_text' | 'link' | 'document',
  assetId: string
): Promise<void> {
  const resp = await fetch(`/api/entities/${entityType}/${entityId}/attachments/${assetType}/${assetId}`, {
    method: 'DELETE',
  });
  if (!resp.ok && resp.status !== 404) throw new Error('Failed to detach shared asset');
}



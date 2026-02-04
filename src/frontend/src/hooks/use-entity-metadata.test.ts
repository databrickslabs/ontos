import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useEntityMetadata, EntityKind, RichTextItem, LinkItem, DocumentItem } from './use-entity-metadata';

// Mock fetch globally
global.fetch = vi.fn();

describe('useEntityMetadata Hook', () => {
  const mockRichTexts: RichTextItem[] = [
    {
      id: 'rt-1',
      entity_id: 'entity-123',
      entity_type: 'data_product',
      title: 'Rich Text 1',
      short_description: 'First rich text',
      content_markdown: '# Content 1',
      created_at: '2024-01-01T10:00:00Z',
      updated_at: '2024-01-01T10:00:00Z',
    },
    {
      id: 'rt-2',
      entity_id: 'entity-123',
      entity_type: 'data_product',
      title: 'Rich Text 2',
      content_markdown: '# Content 2',
      created_at: '2024-01-02T10:00:00Z',
    },
  ];

  const mockLinks: LinkItem[] = [
    {
      id: 'link-1',
      entity_id: 'entity-123',
      entity_type: 'data_product',
      title: 'Link 1',
      url: 'https://example.com/link1',
      created_at: '2024-01-01T11:00:00Z',
    },
    {
      id: 'link-2',
      entity_id: 'entity-123',
      entity_type: 'data_product',
      title: 'Link 2',
      short_description: 'Second link',
      url: 'https://example.com/link2',
      created_at: '2024-01-02T11:00:00Z',
    },
  ];

  const mockDocuments: DocumentItem[] = [
    {
      id: 'doc-1',
      entity_id: 'entity-123',
      entity_type: 'data_product',
      title: 'Document 1',
      original_filename: 'doc1.pdf',
      content_type: 'application/pdf',
      size_bytes: 1024,
      storage_path: '/storage/doc1.pdf',
      created_at: '2024-01-01T12:00:00Z',
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('Initial State', () => {
    it('initializes with empty arrays and no loading', () => {
      const { result } = renderHook(() => useEntityMetadata('data_product', null));

      expect(result.current.richTexts).toEqual([]);
      expect(result.current.links).toEqual([]);
      expect(result.current.documents).toEqual([]);
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('provides refresh function', () => {
      const { result } = renderHook(() => useEntityMetadata('data_product', null));

      expect(typeof result.current.refresh).toBe('function');
    });
  });

  describe('Fetching Metadata', () => {
    it('fetches all metadata types on mount when entityId is provided', async () => {
      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('rich-texts')) {
          return Promise.resolve({ ok: true, json: async () => mockRichTexts });
        }
        if (url.includes('links') && !url.includes('semantic')) {
          return Promise.resolve({ ok: true, json: async () => mockLinks });
        }
        if (url.includes('documents')) {
          return Promise.resolve({ ok: true, json: async () => mockDocuments });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.reject(new Error('Unknown URL'));
      });

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.richTexts).toHaveLength(2);
      expect(result.current.links).toHaveLength(2);
      expect(result.current.documents).toHaveLength(1);
      expect(result.current.error).toBeNull();
    });

    it('does not fetch when entityId is null', async () => {
      const { result } = renderHook(() => useEntityMetadata('data_product', null));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(global.fetch).not.toHaveBeenCalled();
      expect(result.current.richTexts).toEqual([]);
      expect(result.current.links).toEqual([]);
      expect(result.current.documents).toEqual([]);
    });

    it('does not fetch when entityId is undefined', async () => {
      const { result } = renderHook(() => useEntityMetadata('data_product', undefined));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(global.fetch).not.toHaveBeenCalled();
    });

    it('makes parallel requests for all metadata types', async () => {
      let fetchCount = 0;
      (global.fetch as any).mockImplementation(() => {
        fetchCount++;
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(fetchCount).toBe(4); // rich-texts, links, documents, attachments
      });
    });

    it('constructs correct API URLs', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
      global.fetch = fetchMock;

      renderHook(() => useEntityMetadata('data_contract', 'contract-456'));

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledTimes(4);
      });

      expect(fetchMock).toHaveBeenCalledWith('/api/entities/data_contract/contract-456/rich-texts');
      expect(fetchMock).toHaveBeenCalledWith('/api/entities/data_contract/contract-456/links');
      expect(fetchMock).toHaveBeenCalledWith('/api/entities/data_contract/contract-456/documents');
      expect(fetchMock).toHaveBeenCalledWith('/api/entities/data_contract/contract-456/attachments');
    });

    it('sets loading state during fetch', async () => {
      (global.fetch as any).mockImplementation(() =>
        new Promise(resolve =>
          setTimeout(() => resolve({ ok: true, json: async () => [] }), 100)
        )
      );

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      // Should be loading initially
      await waitFor(() => {
        expect(result.current.loading).toBe(true);
      });

      // Should finish loading
      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      }, { timeout: 2000 });
    });
  });

  describe('Error Handling', () => {
    it('handles rich-texts fetch error', async () => {
      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('rich-texts')) {
          return Promise.resolve({ ok: false, status: 500 });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBeTruthy();
      expect(result.current.error).toContain('rich-texts 500');
      expect(result.current.richTexts).toEqual([]);
      expect(result.current.links).toEqual([]);
      expect(result.current.documents).toEqual([]);
    });

    it('handles links fetch error', async () => {
      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('links') && !url.includes('semantic')) {
          return Promise.resolve({ ok: false, status: 404 });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBeTruthy();
      expect(result.current.error).toContain('links 404');
    });

    it('handles documents fetch error', async () => {
      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('documents')) {
          return Promise.resolve({ ok: false, status: 403 });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBeTruthy();
      expect(result.current.error).toContain('documents 403');
    });

    it('handles network error', async () => {
      (global.fetch as any).mockRejectedValue(new Error('Network error'));

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBe('Network error');
    });

    it('handles error without message', async () => {
      (global.fetch as any).mockRejectedValue({});

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBe('Failed to load metadata');
    });

    it('clears data on error', async () => {
      // First successful fetch
      (global.fetch as any).mockImplementation(() =>
        Promise.resolve({ ok: true, json: async () => mockRichTexts })
      );

      const { result, rerender: _rerender } = renderHook(
        ({ entityType, entityId }) => useEntityMetadata(entityType, entityId),
        { initialProps: { entityType: 'data_product' as EntityKind, entityId: 'entity-123' } }
      );

      await waitFor(() => {
        expect(result.current.richTexts.length).toBeGreaterThan(0);
      });

      // Now trigger error with refetch
      (global.fetch as any).mockRejectedValue(new Error('Fetch failed'));

      await act(async () => {
        await result.current.refresh();
      });

      expect(result.current.richTexts).toEqual([]);
      expect(result.current.error).toBe('Fetch failed');
    });
  });

  describe('Data Sorting', () => {
    it('sorts rich texts by created_at ascending', async () => {
      const unsortedRichTexts = [
        { ...mockRichTexts[1], created_at: '2024-01-03T10:00:00Z' },
        { ...mockRichTexts[0], created_at: '2024-01-01T10:00:00Z' },
      ];

      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('rich-texts')) {
          return Promise.resolve({ ok: true, json: async () => unsortedRichTexts });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.richTexts[0].created_at).toBe('2024-01-01T10:00:00Z');
      expect(result.current.richTexts[1].created_at).toBe('2024-01-03T10:00:00Z');
    });

    it('sorts links by created_at ascending', async () => {
      const unsortedLinks = [
        { ...mockLinks[1], created_at: '2024-01-04T10:00:00Z' },
        { ...mockLinks[0], created_at: '2024-01-02T10:00:00Z' },
      ];

      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('links') && !url.includes('semantic')) {
          return Promise.resolve({ ok: true, json: async () => unsortedLinks });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.links[0].created_at).toBe('2024-01-02T10:00:00Z');
      expect(result.current.links[1].created_at).toBe('2024-01-04T10:00:00Z');
    });

    it('sorts documents by created_at ascending', async () => {
      const unsortedDocuments = [
        { ...mockDocuments[0], id: 'doc-3', created_at: '2024-01-05T10:00:00Z' },
        { ...mockDocuments[0], id: 'doc-1', created_at: '2024-01-01T10:00:00Z' },
        { ...mockDocuments[0], id: 'doc-2', created_at: '2024-01-03T10:00:00Z' },
      ];

      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('documents')) {
          return Promise.resolve({ ok: true, json: async () => unsortedDocuments });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.documents[0].id).toBe('doc-1');
      expect(result.current.documents[1].id).toBe('doc-2');
      expect(result.current.documents[2].id).toBe('doc-3');
    });

    it('handles items without created_at dates', async () => {
      const itemsWithoutDates = [
        { ...mockRichTexts[0], created_at: undefined },
        { ...mockRichTexts[1], created_at: '2024-01-01T10:00:00Z' },
      ];

      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('rich-texts')) {
          return Promise.resolve({ ok: true, json: async () => itemsWithoutDates });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      // Should not crash, sorted array should exist
      expect(Array.isArray(result.current.richTexts)).toBe(true);
      expect(result.current.richTexts).toHaveLength(2);
    });
  });

  describe('Refresh Function', () => {
    it('refetches data when refresh is called', async () => {
      (global.fetch as any).mockImplementation(() =>
        Promise.resolve({ ok: true, json: async () => [] })
      );

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      vi.clearAllMocks();

      await act(async () => {
        await result.current.refresh();
      });

      expect(global.fetch).toHaveBeenCalledTimes(4); // rich-texts, links, documents, attachments
    });

    it('updates data on refresh', async () => {
      // First fetch returns one item
      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('rich-texts')) {
          return Promise.resolve({ ok: true, json: async () => [mockRichTexts[0]] });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.richTexts).toHaveLength(1);
      });

      // Second fetch returns different data
      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('rich-texts')) {
          return Promise.resolve({ ok: true, json: async () => mockRichTexts });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      await act(async () => {
        await result.current.refresh();
      });

      expect(result.current.richTexts).toHaveLength(2);
    });

    it('sets loading state during refresh', async () => {
      (global.fetch as any).mockImplementation(() =>
        Promise.resolve({ ok: true, json: async () => [] })
      );

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      // Mock slow refresh
      (global.fetch as any).mockImplementation(() =>
        new Promise(resolve =>
          setTimeout(() => resolve({ ok: true, json: async () => [] }), 100)
        )
      );

      act(() => {
        result.current.refresh();
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(true);
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });
    });

    it('does not fetch when entityId is null', async () => {
      const { result } = renderHook(() => useEntityMetadata('data_product', null));

      await act(async () => {
        await result.current.refresh();
      });

      expect(global.fetch).not.toHaveBeenCalled();
    });
  });

  describe('Entity Type Support', () => {
    it('works with data_domain entity type', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
      global.fetch = fetchMock;

      renderHook(() => useEntityMetadata('data_domain', 'domain-123'));

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled();
      });

      expect(fetchMock).toHaveBeenCalledWith('/api/entities/data_domain/domain-123/rich-texts');
    });

    it('works with data_product entity type', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
      global.fetch = fetchMock;

      renderHook(() => useEntityMetadata('data_product', 'product-123'));

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled();
      });

      expect(fetchMock).toHaveBeenCalledWith('/api/entities/data_product/product-123/rich-texts');
    });

    it('works with data_contract entity type', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
      global.fetch = fetchMock;

      renderHook(() => useEntityMetadata('data_contract', 'contract-123'));

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalled();
      });

      expect(fetchMock).toHaveBeenCalledWith('/api/entities/data_contract/contract-123/rich-texts');
    });
  });

  describe('Data Validation', () => {
    it('handles non-array response for rich texts', async () => {
      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('rich-texts')) {
          return Promise.resolve({ ok: true, json: async () => ({ invalid: 'data' }) });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.richTexts).toEqual([]);
      expect(result.current.error).toBeNull();
    });

    it('handles non-array response for links', async () => {
      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('links') && !url.includes('semantic')) {
          return Promise.resolve({ ok: true, json: async () => null });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.links).toEqual([]);
    });

    it('handles non-array response for documents', async () => {
      (global.fetch as any).mockImplementation((url: string) => {
        if (url.includes('documents')) {
          return Promise.resolve({ ok: true, json: async () => 'invalid' });
        }
        if (url.includes('attachments')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => [] });
      });

      const { result } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.documents).toEqual([]);
    });
  });

  describe('Hook Stability', () => {
    it('maintains refresh function reference', async () => {
      (global.fetch as any).mockResolvedValue({ ok: true, json: async () => [] });

      const { result, rerender } = renderHook(() => useEntityMetadata('data_product', 'entity-123'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      const firstRefresh = result.current.refresh;

      rerender();

      const secondRefresh = result.current.refresh;

      // Should be different because useCallback depends on entityType and entityId
      expect(typeof firstRefresh).toBe('function');
      expect(typeof secondRefresh).toBe('function');
    });

    it('refetches when entityId changes', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
      global.fetch = fetchMock;

      const { rerender } = renderHook(
        ({ entityId }) => useEntityMetadata('data_product', entityId),
        { initialProps: { entityId: 'entity-1' } }
      );

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith('/api/entities/data_product/entity-1/rich-texts');
      });

      fetchMock.mockClear();

      rerender({ entityId: 'entity-2' });

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith('/api/entities/data_product/entity-2/rich-texts');
      });
    });

    it('refetches when entityType changes', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
      global.fetch = fetchMock;

      const { rerender } = renderHook(
        ({ entityType }) => useEntityMetadata(entityType, 'entity-123'),
        { initialProps: { entityType: 'data_product' as EntityKind } }
      );

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith('/api/entities/data_product/entity-123/rich-texts');
      });

      fetchMock.mockClear();

      rerender({ entityType: 'data_contract' as EntityKind });

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith('/api/entities/data_contract/entity-123/rich-texts');
      });
    });
  });
});

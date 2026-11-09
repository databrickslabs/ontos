import { describe, it, expect } from 'vitest';
import { buildEntityCommentsUrl } from './comment-sidebar';

describe('buildEntityCommentsUrl', () => {
  const iri = 'http://example.org/onto/x#Foo';

  it('keeps the path form for plain ids', () => {
    expect(buildEntityCommentsUrl('data_product', 'abc-123', 'comments')).toBe(
      '/api/entities/data_product/abc-123/comments',
    );
    expect(
      buildEntityCommentsUrl('data_product', 'abc-123', 'timeline/count', {
        filter_type: 'all',
        project_id: 'p1',
      }),
    ).toBe('/api/entities/data_product/abc-123/timeline/count?filter_type=all&project_id=p1');
  });

  it('drops empty query values', () => {
    expect(
      buildEntityCommentsUrl('data_product', 'abc', 'timeline', {
        filter_type: 'comments',
        project_id: undefined,
      }),
    ).toBe('/api/entities/data_product/abc/timeline?filter_type=comments');
  });

  it('uses the by-iri variant with an encoded entity_id for IRIs', () => {
    expect(buildEntityCommentsUrl('ontology_concept', iri, 'comments')).toBe(
      `/api/entities/ontology_concept/by-iri/comments?entity_id=${encodeURIComponent(iri)}`,
    );
  });

  it('merges entity_id with the other query params for IRIs', () => {
    const url = buildEntityCommentsUrl('ontology_concept', iri, 'timeline/count', {
      filter_type: 'all',
      project_id: 'p1',
    });
    expect(url.startsWith('/api/entities/ontology_concept/by-iri/timeline/count?')).toBe(true);
    const params = new URLSearchParams(url.split('?')[1]);
    expect(params.get('entity_id')).toBe(iri);
    expect(params.get('filter_type')).toBe('all');
    expect(params.get('project_id')).toBe('p1');
    expect(url.split('?').length).toBe(2);
    expect(url).not.toContain('#');
  });
});

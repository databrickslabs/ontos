import { describe, expect, it } from 'vitest';
import { previewDocuments, rewriteImageLinks } from './metadata-image-links';
import type { DocumentItem } from '@/hooks/use-entity-metadata';

const docs = [
  { id: 'd-1', original_filename: 'snapshot.png', title: 'Snapshot', entity_id: 'a', entity_type: 'asset', storage_path: 'x' },
] as unknown as DocumentItem[];

describe('rewriteImageLinks', () => {
  it('rewrites doc: and file: references to the content endpoint', () => {
    expect(rewriteImageLinks('![s](doc:d-1) ![t](file:snapshot.png)', docs)).toBe(
      '![s](/api/documents/d-1/content) ![t](/api/documents/d-1/content)',
    );
  });

  it('leaves unknown references and plain URLs alone', () => {
    expect(rewriteImageLinks('![s](doc:nope) [x](https://example.com)', docs)).toBe(
      '![s](doc:nope) [x](https://example.com)',
    );
  });
});

describe('previewDocuments', () => {
  const own = {
    id: 'own', original_filename: 'snapshot.png', entity_id: 'p', entity_type: 'data_product',
  } as unknown as DocumentItem;
  const inherited = {
    id: 'inh', original_filename: 'snapshot.png', entity_id: 'a', entity_type: 'asset',
  } as unknown as DocumentItem;

  it("lets the entity's own document win a file: name clash with an inherited one", () => {
    const list = previewDocuments([own], [inherited]);
    expect(rewriteImageLinks('![s](file:snapshot.png)', list)).toBe(
      '![s](/api/documents/own/content)',
    );
  });

  it('still resolves inherited-only documents', () => {
    const list = previewDocuments([], [inherited]);
    expect(rewriteImageLinks('![s](file:snapshot.png)', list)).toBe(
      '![s](/api/documents/inh/content)',
    );
  });
});

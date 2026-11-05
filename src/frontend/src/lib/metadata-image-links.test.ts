import { describe, expect, it } from 'vitest';
import { rewriteImageLinks } from './metadata-image-links';
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

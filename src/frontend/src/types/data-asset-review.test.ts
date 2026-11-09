import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { AssetType } from './data-asset-review';

// The backend enum the review API validates `asset_type` against.
// Tests run from src/frontend.
const backendModels = resolve(process.cwd(), '../backend/src/models/data_asset_reviews.py');

function backendAssetTypes(): string[] {
  const source = readFileSync(backendModels, 'utf-8');
  const body = source.split('class AssetType(str, Enum):')[1].split(/\n(?=\S)/)[0];
  return [...body.matchAll(/^\s+[A-Z_]+\s*=\s*"([^"]+)"/gm)].map((m) => m[1]);
}

describe('AssetType', () => {
  it('has the same values as the backend enum', () => {
    const backend = backendAssetTypes();
    expect(backend).toContain('knowledge_concept');
    expect(Object.values(AssetType).sort()).toEqual([...backend].sort());
  });
});

import { AssetType } from '@/types/data-asset-review';

/**
 * The page of a data product or contract under review, whose FQN is
 * `product:<id>` or `contract:<id>`; null for any other asset.
 */
export function appEntityAssetLink(asset: { asset_fqn: string; asset_type: string }): string | null {
  const pages: Record<string, [string, string]> = {
    [AssetType.DATA_PRODUCT]: ['product:', '/data-products/'],
    [AssetType.DATA_CONTRACT]: ['contract:', '/data-contracts/'],
  };
  const page = pages[asset.asset_type];
  if (!page || !asset.asset_fqn.startsWith(page[0])) return null;
  const id = asset.asset_fqn.slice(page[0].length);
  return id ? `${page[1]}${encodeURIComponent(id)}` : null;
}

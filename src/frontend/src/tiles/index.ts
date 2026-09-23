import { TileRegistry } from './types';
import { semanticModelsTile } from './semantic-models/config';
import { dataProductsTile } from './data-products/config';
import { dataContractsTile } from './data-contracts/config';
import { complianceTile } from './compliance/config';
import { authorityResolutionTile } from './authority-resolution/config';

/**
 * Registry of all available overview tiles.
 *
 * To add a new tile:
 * 1. Create a new directory in src/tiles/
 * 2. Create config.tsx, use-*-data.ts, and optional custom content components
 * 3. Import and add to this registry
 * 4. Add to tileOrder array below
 */
export const tileRegistry: TileRegistry = {
  'semantic-models': semanticModelsTile,
  'data-products': dataProductsTile,
  'data-contracts': dataContractsTile,
  'compliance': complianceTile,
  'authority-resolution': authorityResolutionTile,
};

/**
 * Ordered list of tile IDs for display.
 * Tiles will be rendered in this order.
 */
export const tileOrder = [
  'semantic-models',
  'data-products',
  'data-contracts',
  'compliance',
  'authority-resolution',
];

// Re-export types for convenience
export type { TileConfig, TileData, TileRegistry } from './types';

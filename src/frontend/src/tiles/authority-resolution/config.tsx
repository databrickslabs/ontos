import { Shield as ShieldIcon } from 'lucide-react';
import { FeatureAccessLevel } from '@/types/settings';
import { TileConfig } from '../types';
import { useAuthorityResolutionData } from './use-authority-resolution-data';

export const authorityResolutionTile: TileConfig = {
  id: 'authority-resolution',
  icon: <ShieldIcon className="h-4 w-4" />,
  titleKey: 'home:overview.tiles.authorityResolution.title',
  descriptionKey: 'home:overview.tiles.authorityResolution.description',
  link: '/authority-resolution',
  permission: 'authority-resolution',
  requiredLevel: FeatureAccessLevel.READ_ONLY,
  useTileData: useAuthorityResolutionData,
};

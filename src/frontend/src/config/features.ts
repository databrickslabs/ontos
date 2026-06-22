import {
    FileTextIcon,
    Network,
    Users,
    CheckCircle,
    Globe,
    Lock,
    Shield,
    RefreshCw,
    FolderKanban,
    ClipboardCheck,
    Search,
    Package,
    BookOpen,
    Box,
    ShoppingCart,
    ClipboardList,
    type LucideIcon,
  } from 'lucide-react';
  
  export type FeatureMaturity = 'ga' | 'beta' | 'alpha';
  export type FeatureGroup = 'Discover' | 'Build' | 'Govern' | 'Deploy';
  
  export interface FeatureConfig {
    id: string;
    name: string;
    path: string;
    description: string;
    icon: LucideIcon;
    group: FeatureGroup;
    maturity: FeatureMaturity;
    showInLanding?: boolean;
    /** When set, permission checks use this feature ID instead of `id`. */
    permissionId?: string;
  }
  
  export const features: FeatureConfig[] = [
    // Discover - Find and explore data
    {
      id: 'marketplace',
      name: 'Marketplace',
      path: '/marketplace',
      description: 'Browse and subscribe to available data products.',
      icon: ShoppingCart,
      group: 'Discover',
      maturity: 'ga',
      showInLanding: false,
      permissionId: 'data-products',
    },
    {
      id: 'search',
      name: 'Search',
      path: '/search',
      description: 'Search across data products, contracts, and knowledge graph.',
      icon: Search,
      group: 'Discover',
      maturity: 'ga',
      showInLanding: false,
    },
    {
      id: 'data-catalog',
      name: 'Data Catalog',
      path: '/data-catalog',
      description: 'Browse Unity Catalog assets, search columns, and analyze lineage.',
      icon: BookOpen,
      group: 'Discover',
      maturity: 'beta',
      showInLanding: true,
    },
    // Build - Create and manage data assets
    {
      id: 'assets',
      name: 'Assets',
      path: '/assets',
      description: 'Catalog and manage data and analytics assets with identity, metadata, and relationships.',
      icon: Box,
      group: 'Build',
      maturity: 'beta',
      showInLanding: true,
    },
    {
      id: 'concepts',
      name: 'Concepts',
      path: '/concepts',
      description: 'Browse, search, and manage business concepts, collections, and hierarchies.',
      icon: Network,
      group: 'Build',
      maturity: 'ga',
      showInLanding: true,
      permissionId: 'semantic-models',
    },
    {
      id: 'data-contracts',
      name: 'Contracts',
      path: '/data-contracts',
      description: 'Define and enforce technical metadata standards.',
      icon: FileTextIcon,
      group: 'Build',
      maturity: 'ga',
      showInLanding: true,
    },
    {
      id: 'data-products',
      name: 'Products',
      path: '/data-products',
      description: 'Group and manage related Databricks assets with tags.',
      icon: Package,
      group: 'Build',
      maturity: 'ga',
      showInLanding: true,
    },
    {
      id: 'my-products',
      name: 'My Products',
      path: '/my-products',
      description: 'View and manage your subscribed data products.',
      icon: ShoppingCart,
      group: 'Build',
      maturity: 'ga',
      showInLanding: false,
    },
    {
      id: 'my-requests',
      name: 'My Requests',
      path: '/my-requests',
      description: 'Track your pending and completed requests.',
      icon: ClipboardList,
      group: 'Build',
      maturity: 'ga',
      showInLanding: false,
    },
    // Govern - Monitor and comply
    {
      id: 'compliance',
      name: 'Compliance',
      path: '/compliance',
      description: 'Create, verify compliance rules, and calculate scores.',
      icon: CheckCircle,
      group: 'Govern',
      maturity: 'beta',
      showInLanding: true,
    },
    {
      id: 'master-data',
      name: 'Master Data Management',
      path: '/master-data',
      description: 'Build a golden record of your data.',
      icon: Users,
      group: 'Govern',
      maturity: 'beta',
      showInLanding: true,
    },
    {
      id: 'data-asset-reviews',
      name: 'Asset Reviews',
      path: '/data-asset-reviews',
      description: 'Review and approve Databricks assets like tables, views, and functions.',
      icon: ClipboardCheck,
      group: 'Govern',
      maturity: 'beta',
      showInLanding: true,
    },
    {
      id: 'security-features',
      name: 'Security Features',
      path: '/security-features',
      description: 'Enable advanced security like differential privacy.',
      icon: Lock,
      group: 'Govern',
      maturity: 'alpha',
      showInLanding: true,
    },
    {
      id: 'entitlements',
      name: 'Entitlements',
      path: '/entitlements',
      description: 'Manage access privileges through personas and groups.',
      icon: Shield,
      group: 'Govern',
      maturity: 'alpha',
      showInLanding: true,
    },
    {
      id: 'entitlements-sync',
      name: 'Entitlements Sync',
      path: '/entitlements-sync',
      description: 'Synchronize entitlements with external systems.',
      icon: RefreshCw,
      group: 'Govern',
      maturity: 'alpha',
      showInLanding: true,
    },
    // Deploy - Operationalize
    {
      id: 'estate-manager',
      name: 'Estate Manager',
      path: '/estate-manager',
      description: 'Manage multiple Databricks instances across regions and clouds.',
      icon: Globe,
      group: 'Deploy',
      maturity: 'alpha',
      showInLanding: true,
    },
    {
      id: 'catalog-commander',
      name: 'Catalog Commander',
      path: '/catalog-commander',
      description: 'Side-by-side catalog explorer for asset management.',
      icon: FolderKanban,
      group: 'Deploy',
      maturity: 'alpha',
      showInLanding: true,
    },
  ];
  
  // Helper function to get feature by path
  export const getFeatureByPath = (path: string): FeatureConfig | undefined =>
    features.find((feature) => feature.path === path);
  
  // Helper function to get feature name by path (for breadcrumbs)
  export const getFeatureNameByPath = (pathSegment: string): string => {
      const feature = features.find(f => f.path === `/${pathSegment}` || f.path === pathSegment);
      return feature?.name || pathSegment;
  };
  
  // Helper function to group features for navigation
  export const getNavigationGroups = (
      allowedMaturities: FeatureMaturity[] = ['ga']
    ): { name: FeatureGroup; items: FeatureConfig[] }[] => {
      const grouped: { [key in FeatureGroup]?: FeatureConfig[] } = {};
  
      features
        .filter((feature) => allowedMaturities.includes(feature.maturity))
        .forEach((feature) => {
          if (!grouped[feature.group]) {
            grouped[feature.group] = [];
          }
          grouped[feature.group]?.push(feature);
        });
  
      const groupOrder: FeatureGroup[] = ['Discover', 'Build', 'Govern', 'Deploy'];
  
      return groupOrder
          .map(groupName => ({
              name: groupName,
              items: grouped[groupName] || []
          }))
          .filter(group => group.items.length > 0);
    };
  
  // Helper function to get features for landing pages (Home, About)
  export const getLandingPageFeatures = (
      allowedMaturities: FeatureMaturity[] = ['ga']
  ): FeatureConfig[] => {
      return features.filter(
          (feature) =>
          feature.showInLanding && allowedMaturities.includes(feature.maturity)
      );
  };

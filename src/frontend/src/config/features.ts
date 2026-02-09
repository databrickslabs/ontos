import {
    FileTextIcon,
    Network,
    Users, // Using Users icon from About for MDM for now
    CheckCircle, // Using CheckCircle icon from About for Compliance for now
    Globe,
    Lock, // Using Lock icon from About for Security for now
    Shield,
    RefreshCw, // Using RefreshCw icon from About for Entitlements Sync for now
    FolderKanban, // Icon for Catalog Commander
    Settings,
    Info,
    ClipboardCheck, // Added icon for Data Asset Review
    BoxSelect, // Added icon for Data Domain
    Search, // Added icon for Search
    UserCheck, // Added icon for Teams
    FolderOpen, // Added icon for Projects
    ScrollText, // Added icon for Audit Trail
    Table2, // Icon for Datasets (matching marketplace)
    Package, // Icon for Data Products (matching marketplace)
    GitBranch, // Icon for Process Workflows
    BookOpen, // Icon for Data Catalog
    Waypoints, // Icon for Graph Explorer
    type LucideIcon, // Import LucideIcon type
  } from 'lucide-react';
  
  export type FeatureMaturity = 'ga' | 'beta' | 'alpha';
  export type FeatureGroup = 'Data Products' | 'Governance' | 'Operations' | 'Security' | 'System';
  
  export interface FeatureConfig {
    id: string; // Unique identifier, e.g., 'data-products'
    name: string;
    path: string;
    description: string;
    icon: LucideIcon; // Use LucideIcon type
    group: FeatureGroup;
    maturity: FeatureMaturity;
    showInLanding?: boolean; // Show on Home/About pages?
  }
  
  export const features: FeatureConfig[] = [
    // Data Products - Core product development lifecycle
    {
      id: 'data-domains',
      name: 'Domains',
      path: '/data-domains',
      description: 'Organize data products and assets into logical domains.',
      icon: BoxSelect,
      group: 'Data Products',
      maturity: 'ga',
      showInLanding: true,
    },
    {
      id: 'teams',
      name: 'Teams',
      path: '/teams',
      description: 'Manage teams and team members with role overrides.',
      icon: UserCheck,
      group: 'Data Products',
      maturity: 'ga',
      showInLanding: false,
    },
    {
      id: 'projects',
      name: 'Projects',
      path: '/projects',
      description: 'Manage projects and assign teams for workspace isolation.',
      icon: FolderOpen,
      group: 'Data Products',
      maturity: 'ga',
      showInLanding: false,
    },
    {
      id: 'datasets',
      name: 'Datasets',
      path: '/datasets',
      description: 'Physical implementations of data contracts (tables, views).',
      icon: Table2,
      group: 'Data Products',
      maturity: 'ga',
      showInLanding: true,
    },
    {
      id: 'data-contracts',
      name: 'Contracts',
      path: '/data-contracts',
      description: 'Define and enforce technical metadata standards.',
      icon: FileTextIcon,
      group: 'Data Products',
      maturity: 'ga',
      showInLanding: true,
    },
    {
      id: 'data-products',
      name: 'Products',
      path: '/data-products',
      description: 'Group and manage related Databricks assets with tags.',
      icon: Package,
      group: 'Data Products',
      maturity: 'ga',
      showInLanding: true,
    },
    // Governance - Standards definition and approval workflows
  {
    id: 'semantic-models',
    name: 'Business Glossary',
    path: '/semantic-models',
    description: 'Explore business glossary terms, concepts, and their relationships.',
    icon: Network,
    group: 'Governance',
    maturity: 'ga',
    showInLanding: true,
  },
    {
      id: 'data-asset-reviews',
      name: 'Asset Review',
      path: '/data-asset-reviews',
      description: 'Review and approve Databricks assets like tables, views, and functions.',
      icon: ClipboardCheck,
      group: 'Governance',
      maturity: 'beta',
      showInLanding: true,
    },
    {
      id: 'data-catalog',
      name: 'Data Catalog',
      path: '/data-catalog',
      description: 'Browse Unity Catalog assets, search columns, and analyze lineage.',
      icon: BookOpen,
      group: 'Governance',
      maturity: 'beta',
      showInLanding: true,
    },
    // Operations - Ongoing monitoring and technical management
    {
      id: 'compliance',
      name: 'Compliance',
      path: '/compliance',
      description: 'Create, verify compliance rules, and calculate scores.',
      icon: CheckCircle,
      group: 'Operations',
      maturity: 'beta',
      showInLanding: true,
    },
    {
      id: 'process-workflows',
      name: 'Workflows',
      path: '/workflows',
      description: 'Configure automated workflows for validation, approval, and notifications.',
      icon: GitBranch,
      group: 'Operations',
      maturity: 'ga',
      showInLanding: true,
    },
    {
      id: 'estate-manager',
      name: 'Estate Manager',
      path: '/estate-manager',
      description: 'Manage multiple Databricks instances across regions and clouds.',
      icon: Globe,
      group: 'Operations',
      maturity: 'alpha',
      showInLanding: true,
    },
    {
      id: 'master-data',
      name: 'Master Data Management',
      path: '/master-data',
      description: 'Build a golden record of your data.',
      icon: Users,
      group: 'Operations',
      maturity: 'beta',
      showInLanding: true,
    },
    {
      id: 'catalog-commander',
      name: 'Catalog Commander',
      path: '/catalog-commander',
      description: 'Side-by-side catalog explorer for asset management.',
      icon: FolderKanban,
      group: 'Operations',
      maturity: 'ga',
      showInLanding: true,
    },
    // Security
    {
      id: 'security-features',
      name: 'Security Features',
      path: '/security',
      description: 'Enable advanced security like differential privacy.',
      icon: Lock,
      group: 'Security',
      maturity: 'alpha',
      showInLanding: true,
    },
    {
      id: 'entitlements',
      name: 'Entitlements',
      path: '/entitlements',
      description: 'Manage access privileges through personas and groups.',
      icon: Shield,
      group: 'Security',
      maturity: 'alpha',
      showInLanding: true,
    },
    {
      id: 'entitlements-sync',
      name: 'Entitlements Sync',
      path: '/entitlements-sync',
      description: 'Synchronize entitlements with external systems.',
      icon: RefreshCw,
      group: 'Security',
      maturity: 'alpha',
      showInLanding: true,
    },
    // System - Application utilities and configuration
    {
      id: 'search',
      name: 'Search',
      path: '/search',
      description: 'Search across data products, contracts, and knowledge graph.',
      icon: Search,
      group: 'System',
      maturity: 'ga',
      showInLanding: false,
    },
    {
      id: 'audit',
      name: 'Audit Trail',
      path: '/audit',
      description: 'View and filter application audit logs.',
      icon: ScrollText,
      group: 'System',
      maturity: 'ga',
      showInLanding: false,
    },
    {
      id: 'settings',
      name: 'Settings',
      path: '/settings',
      description: 'Configure application settings, jobs, and integrations.',
      icon: Settings,
      group: 'System',
      maturity: 'ga',
      showInLanding: false,
    },
    {
      id: 'graph-explorer',
      name: 'Graph Explorer',
      path: '/graph-explorer',
      description: 'Explore and edit property graphs stored in Databricks tables.',
      icon: Waypoints,
      group: 'Governance',
      maturity: 'alpha',
      showInLanding: true,
    },
    {
      id: 'about',
      name: 'About',
      path: '/about',
      description: 'Information about the application and its features.',
      icon: Info,
      group: 'System',
      maturity: 'ga',
      showInLanding: false,
    },
  ];
  
  // Helper function to get feature by path
  export const getFeatureByPath = (path: string): FeatureConfig | undefined =>
    features.find((feature) => feature.path === path);
  
  // Helper function to get feature name by path (for breadcrumbs)
  export const getFeatureNameByPath = (pathSegment: string): string => {
      // Find feature where the path ends with the segment (handling potential leading '/')
      const feature = features.find(f => f.path === `/${pathSegment}` || f.path === pathSegment);
      return feature?.name || pathSegment; // Return name or segment itself if not found
  };
  
  // Helper function to group features for navigation
  export const getNavigationGroups = (
      allowedMaturities: FeatureMaturity[] = ['ga'] // Default to GA only
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
  
      // Define the desired order of groups
      const groupOrder: FeatureGroup[] = ['Data Products', 'Governance', 'Operations', 'Security', 'System'];
  
      // Sort groups according to the defined order
      return groupOrder
          .map(groupName => ({
              name: groupName,
              items: grouped[groupName] || [] // Get items or empty array if group is missing
          }))
          .filter(group => group.items.length > 0); // Remove empty groups
    };
  
  // Helper function to get features for landing pages (Home, About)
  export const getLandingPageFeatures = (
      allowedMaturities: FeatureMaturity[] = ['ga'] // Default to GA only
  ): FeatureConfig[] => {
      return features.filter(
          (feature) =>
          feature.showInLanding && allowedMaturities.includes(feature.maturity)
      );
  };
  
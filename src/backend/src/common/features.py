from enum import Enum
from typing import List, Dict, Type

class FeatureAccessLevel(str, Enum):
    NONE = "None"           # No access
    READ_ONLY = "Read-only" # Can view data, cannot modify
    READ_WRITE = "Read/Write" # Can view and modify data within the feature
    FILTERED = "Filtered"   # Read/Write access, but only to a subset of data (e.g., based on domain) - Requires specific implementation per feature
    FULL = "Full"           # Full access within the feature scope (potentially includes config)
    ADMIN = "Admin"         # Full access + administrative actions (e.g., delete glossary, manage feature settings)

# Define the order of access levels from lowest to highest
ACCESS_LEVEL_ORDER: Dict[FeatureAccessLevel, int] = {
    FeatureAccessLevel.NONE: 0,
    FeatureAccessLevel.READ_ONLY: 1,
    FeatureAccessLevel.FILTERED: 2, # Filtered is higher than read-only
    FeatureAccessLevel.READ_WRITE: 3,
    FeatureAccessLevel.FULL: 4,
    FeatureAccessLevel.ADMIN: 5,
}

# Define which levels are generally applicable. Specific features might restrict further.
ALL_ACCESS_LEVELS = list(FeatureAccessLevel)
READ_WRITE_ADMIN_LEVELS = [
    FeatureAccessLevel.NONE,
    FeatureAccessLevel.READ_ONLY,
    FeatureAccessLevel.READ_WRITE,
    FeatureAccessLevel.ADMIN,
]
READ_ONLY_FULL_LEVELS = [
    FeatureAccessLevel.NONE,
    FeatureAccessLevel.READ_ONLY,
    FeatureAccessLevel.FULL,
    FeatureAccessLevel.ADMIN,
]
ADMIN_ONLY_LEVELS = [
    FeatureAccessLevel.NONE,
    FeatureAccessLevel.ADMIN,
]


# Permission group buckets — mirror the sidebar groups plus a Settings bucket
# and a catch-all `Other` bucket for cross-cutting permissions.
GROUP_DISCOVER = "Discover"
GROUP_BUILD = "Build"
GROUP_GOVERN = "Govern"
GROUP_DEPLOY = "Deploy"
GROUP_SETTINGS = "Settings"
GROUP_OTHER = "Other"


# Mirroring src/config/features.ts (simplified for now)
# Key: Feature ID, Value: Dict with 'name', 'allowed_levels', and 'group'
APP_FEATURES: Dict[str, Dict[str, str | List[FeatureAccessLevel]]] = {
    # --- Discover ---
    'data-catalog': {
        'name': 'Data Catalog',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,  # Browse catalog, view lineage
        'group': GROUP_DISCOVER,
    },
    'llm-search': {
        'name': 'LLM Search',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_DISCOVER,
    },

    # --- Build ---
    'data-products': {
        'name': 'Data Products',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS + [FeatureAccessLevel.FILTERED],  # Allow filtering
        'group': GROUP_BUILD,
    },
    'data-contracts': {
        'name': 'Data Contracts',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_BUILD,
    },
    'assets': {
        'name': 'Assets',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_BUILD,
    },
    'semantic-models': {
        'name': 'Concept Browser',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_BUILD,
    },
    'schema-importer': {
        'name': 'Schema Importer',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_BUILD,
    },

    # --- Govern ---
    'compliance': {
        'name': 'Compliance',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_GOVERN,
    },
    'master-data': {
        'name': 'Master Data Management',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_GOVERN,
    },
    'data-asset-reviews': {
        'name': 'Asset Reviews',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,  # Stewards review, admins manage
        'group': GROUP_GOVERN,
    },
    'security-features': {
        'name': 'Security Features',
        'allowed_levels': ADMIN_ONLY_LEVELS,  # Likely admin only
        'group': GROUP_GOVERN,
    },
    'entitlements': {
        'name': 'Entitlements',
        'allowed_levels': ADMIN_ONLY_LEVELS,  # Admin manages personas/groups
        'group': GROUP_GOVERN,
    },
    'entitlements-sync': {
        'name': 'Entitlements Sync',
        'allowed_levels': ADMIN_ONLY_LEVELS,  # Admin manages sync jobs
        'group': GROUP_GOVERN,
    },
    'process-workflows': {
        'name': 'Process Workflows',
        'allowed_levels': [
            FeatureAccessLevel.NONE,
            FeatureAccessLevel.READ_ONLY,
            FeatureAccessLevel.ADMIN,  # Only Admin gets full write access
        ],
        'group': GROUP_GOVERN,
    },
    'access-grants': {
        'name': 'Access Grants',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,  # Users request, admins grant
        'group': GROUP_GOVERN,
    },

    # --- Deploy ---
    'estate-manager': {
        'name': 'Estate Manager',
        'allowed_levels': READ_ONLY_FULL_LEVELS,  # Now includes ADMIN
        'group': GROUP_DEPLOY,
    },
    'catalog-commander': {
        'name': 'Catalog Commander',
        'allowed_levels': [FeatureAccessLevel.NONE, FeatureAccessLevel.READ_ONLY, FeatureAccessLevel.FULL, FeatureAccessLevel.ADMIN],
        'group': GROUP_DEPLOY,
    },

    # --- Settings (layout gate) ---
    'settings': {
        'name': 'Settings',
        # Bumped from ADMIN_ONLY to full scale — acts as the layout gate.
        # Each sub-page below has its own settings-<name> permission.
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # --- Settings: Reference Data sub-pages ---
    'settings-data-domains': {
        'name': 'Settings — Data Domains',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-business-roles': {
        'name': 'Settings — Business Roles',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-delivery-methods': {
        'name': 'Settings — Delivery Methods',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-asset-types': {
        'name': 'Settings — Asset Types',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-teams': {
        'name': 'Settings — Teams',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-projects': {
        'name': 'Settings — Projects',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-certification-levels': {
        'name': 'Settings — Certification Levels',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # --- Settings: Configuration sub-pages ---
    'settings-general': {
        'name': 'Settings — General',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-ui': {
        'name': 'Settings — UI Customization',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-tags': {
        'name': 'Settings — Tags',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-connectors': {
        'name': 'Settings — Connectors',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # --- Settings: Integrations sub-pages ---
    'settings-git': {
        'name': 'Settings — Git',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-mcp': {
        'name': 'Settings — MCP',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-directory': {
        'name': 'Settings — Directory',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-semantic-models': {
        'name': 'Settings — RDF Sources',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-search': {
        'name': 'Settings — Search',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # --- Settings: Operations sub-pages ---
    'settings-jobs': {
        'name': 'Settings — Jobs',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-delivery': {
        'name': 'Settings — Delivery',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-workflows': {
        'name': 'Settings — Workflows',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # --- Settings: Access Control sub-pages ---
    'settings-roles': {
        'name': 'Settings — App Roles',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-audit': {
        'name': 'Settings — Audit Trail',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # --- Other (cross-cutting / consumption-side permissions) ---
    # These existing top-level IDs remain in place to govern consumption of
    # the underlying feature elsewhere in the app (pickers, lineage, search
    # results, etc.). Their settings-page counterparts live above.
    'data-domains': {
        'name': 'Data Domains',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_OTHER,
    },
    'teams': {
        'name': 'Teams',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_OTHER,
    },
    'projects': {
        'name': 'Projects',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_OTHER,
    },
    'business-roles': {
        'name': 'Business Roles',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_OTHER,
    },
    'business-owners': {
        'name': 'Business Owners',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_OTHER,
    },
    'delivery-methods': {
        'name': 'Delivery Methods',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_OTHER,
    },
    'tags': {
        'name': 'Tags',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,  # READ_WRITE can create tags, ADMIN can manage taxonomy
        'group': GROUP_OTHER,
    },
    'jobs': {
        'name': 'Jobs',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,  # View/manage background jobs
        'group': GROUP_OTHER,
    },
    'audit': {
        'name': 'Audit & Change Logs',
        # Allow read-only, full (if used), and admin; write requires at least READ_WRITE but routes use explicit checks
        'allowed_levels': [
            FeatureAccessLevel.NONE,
            FeatureAccessLevel.READ_ONLY,
            FeatureAccessLevel.READ_WRITE,
            FeatureAccessLevel.FULL,
            FeatureAccessLevel.ADMIN,
        ],
        'group': GROUP_OTHER,
    },
    'notifications': {
        'name': 'Notifications',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,  # Users can view/manage own notifications
        'group': GROUP_OTHER,
    },
    'self-service': {
        'name': 'Self Service',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,  # Self-service data requests
        'group': GROUP_OTHER,
    },
    'comments': {
        'name': 'Comments & Ratings',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,  # READ_WRITE to add, ADMIN to manage all
        'group': GROUP_OTHER,
    },
    'ontology': {
        'name': 'Ontology Schema',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_OTHER,
    },
    'entity_relationships': {
        'name': 'Entity Relationships',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_OTHER,
    },
    'entity_subscriptions': {
        'name': 'Entity Subscriptions',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_OTHER,
    },
    # 'about': { ... } # About page doesn't need explicit permissions here
}


# IDs that are part of the Settings group — used by the role seeder to
# auto-grant ADMIN on the built-in Admin role.
SETTINGS_SUBPAGE_FEATURE_IDS: List[str] = [
    feature_id
    for feature_id, config in APP_FEATURES.items()
    if feature_id.startswith('settings-')
]


def get_feature_config() -> Dict[str, Dict[str, str | List[FeatureAccessLevel]]]:
    """Returns the application feature configuration."""
    return APP_FEATURES

def get_all_access_levels() -> List[FeatureAccessLevel]:
    """Returns all possible access levels."""
    return ALL_ACCESS_LEVELS

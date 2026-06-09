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
# Levels for "implicit" cross-cutting features that every authenticated user
# should have at least read access to (commenting, requesting access grants,
# viewing one's own process-workflow status, etc.). These features can still
# be tightened to read-only or expanded to admin per role, but `NONE` is not
# offered as a choice because the feature is part of the baseline UX.
IMPLICIT_FEATURE_LEVELS = [
    FeatureAccessLevel.READ_ONLY,
    FeatureAccessLevel.READ_WRITE,
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
    # NOTE: `llm-search` is intentionally NOT registered as a permission.
    # The LLM Search routes deliberately bypass PermissionChecker (access
    # control is performed by the underlying tools that filter results
    # based on the caller's permissions for each surfaced entity). See
    # `src/backend/src/routes/llm_search_routes.py`.

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
    'term-mapping': {
        'name': 'Term Mapping',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_BUILD,  # lives under /concepts/mapping alongside Concepts
    },
    'schema-importer': {
        # Cross-cutting: schema-importer has no top-level sidebar entry; it
        # is launched inline from Data Contracts / Data Products to populate
        # them from existing schemas.
        'name': 'Schema Importer',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_BUILD,
        'cross_cutting': True,
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
        # Cross-cutting: process workflows are surfaced inline (notifications
        # for approvals, status badges on entities) — there is no dedicated
        # "Process Workflows" sidebar entry. Every user can see the workflows
        # that affect them; admins manage workflow definitions.
        'name': 'Process Workflows',
        'allowed_levels': [
            FeatureAccessLevel.READ_ONLY,
            FeatureAccessLevel.ADMIN,
        ],
        'group': GROUP_GOVERN,
        'cross_cutting': True,
    },
    'access-grants': {
        # Cross-cutting: launched from asset detail pages, no sidebar entry.
        # Every user can request grants (READ_WRITE) or at minimum see their
        # own grants (READ_ONLY); admins approve and manage.
        'name': 'Access Grants',
        'allowed_levels': IMPLICIT_FEATURE_LEVELS,
        'group': GROUP_GOVERN,
        'cross_cutting': True,
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
    # NOTE: most Reference Data sub-pages no longer need a dedicated
    # `settings-*` permission. The Settings sidebar gates visibility via the
    # corresponding consumption-side permission (e.g. `data-domains`,
    # `business-roles`, `teams`, …). The sub-pages that remain below either
    # (a) lack a consumption counterpart (asset-types, certification-levels)
    # or (b) need distinct backend semantics from their consumption sibling.
    'settings-asset-types': {
        'name': 'Asset Types',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-certification-levels': {
        'name': 'Certification Levels',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-maturity-levels': {
        'name': 'Maturity Levels',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-maturity-levels': {
        'name': 'Settings — Maturity Levels',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # --- Settings: Configuration sub-pages ---
    'settings-general': {
        'name': 'General',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-ui': {
        'name': 'UI Customization',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-connectors': {
        'name': 'Connectors',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # --- Settings: Integrations sub-pages ---
    'settings-git': {
        'name': 'Git',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-mcp': {
        'name': 'MCP',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-directory': {
        'name': 'Directory',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-semantic-models': {
        'name': 'RDF Sources',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-search': {
        'name': 'Search',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # --- Settings: Operations sub-pages ---
    'settings-delivery': {
        # Configures delivery MODES for data products (Direct / Indirect /
        # Manual). Disambiguated from the `delivery-methods` reference data
        # (which manages the list of selectable delivery method labels).
        'name': 'Delivery Modes',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'settings-workflows': {
        'name': 'Workflows',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # --- Settings: Access Control sub-pages ---
    'settings-roles': {
        'name': 'App Roles',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # --- Cross-cutting / consumption-side permissions ---
    # These top-level IDs govern consumption of the underlying feature
    # elsewhere in the app (pickers, lineage, detail panels, etc.). Reference
    # data permissions live in the Settings group so they appear under the
    # appropriate Settings sub-section (Reference Data, Configuration,
    # Operations, Access Control) — the same buckets the Settings sidebar
    # uses. Cross-cutting platform permissions without a Settings sub-section
    # counterpart live in the appropriate main-menu group.

    # Reference data — gates both the Settings sidebar entry and any
    # cross-app consumption (domain pickers, business role assignment, etc.)
    'data-domains': {
        'name': 'Data Domains',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'business-roles': {
        'name': 'Business Roles',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'business-owners': {
        # Cross-cutting: no dedicated Settings sub-page. Used by the
        # ownership panel and Assign Owner dialog on data product / data
        # contract details. The `/business-owners` route exists as a list
        # view but is not linked from the sidebar.
        'name': 'Business Owners',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
        'cross_cutting': True,
    },
    'delivery-methods': {
        'name': 'Delivery Methods',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'teams': {
        'name': 'Teams',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },
    'projects': {
        'name': 'Projects',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # Configuration — gates both the Tags settings page (tag taxonomy
    # administration at ADMIN level) and tag application throughout the
    # app (READ_WRITE level on detail panels, pickers, etc.).
    'tags': {
        'name': 'Tags',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # Operations — background jobs (gates both the Jobs settings page and
    # any cross-app job APIs).
    'jobs': {
        'name': 'Jobs',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_SETTINGS,
    },

    # Access Control — read access to audit trail
    'audit': {
        'name': 'Audit & Change Logs',
        'allowed_levels': [
            FeatureAccessLevel.NONE,
            FeatureAccessLevel.READ_ONLY,
            FeatureAccessLevel.READ_WRITE,
            FeatureAccessLevel.FULL,
            FeatureAccessLevel.ADMIN,
        ],
        'group': GROUP_SETTINGS,
    },

    # --- Cross-cutting platform permissions (no sidebar entry) ---
    # These features are surfaced inline (panels on detail pages, inline
    # actions, etc.) rather than as their own top-level sidebar item. They
    # are flagged `cross_cutting: True` so the role editor renders them in
    # a separate "Background" sub-section under their primary group.
    'comments': {
        # Comments and star ratings on any entity. Every user can at least
        # read comments; READ_WRITE lets them post their own; ADMIN can
        # moderate / delete others'.
        'name': 'Comments & Ratings',
        'allowed_levels': IMPLICIT_FEATURE_LEVELS,
        'group': GROUP_GOVERN,
        'cross_cutting': True,
    },
    'ontology': {
        # Concepts feature backend (ontology generator + schema endpoints).
        # No sidebar entry of its own; used by the Concepts UI.
        'name': 'Ontology Schema',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_BUILD,
        'cross_cutting': True,
    },
    'entity_relationships': {
        # Cross-entity relationships and business lineage. Surfaced inline
        # on entity detail pages — no dedicated sidebar entry.
        'name': 'Entity Relationships',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_BUILD,
        'cross_cutting': True,
    },

    # --- Backend-only permissions ---
    # These gate backend APIs that are not currently surfaced in the UI for
    # end users. They're flagged `hidden_from_role_dialog: True` so the role
    # editor doesn't expose them — admins implicitly inherit ADMIN on all
    # features via the admin role.
    'notifications': {
        # Admin-only: governs CREATE/DELETE notification endpoints. End
        # users see their own notifications without this permission.
        'name': 'Notifications (Admin)',
        'allowed_levels': ADMIN_ONLY_LEVELS,
        'group': GROUP_GOVERN,
        'hidden_from_role_dialog': True,
    },
    'entity_subscriptions': {
        # Generic subscribe/unsubscribe endpoints at /api/subscriptions.
        # The marketplace subscribe flow uses product-specific endpoints
        # gated by `data-products`, so this perm is currently backend-only.
        'name': 'Entity Subscriptions',
        'allowed_levels': READ_WRITE_ADMIN_LEVELS,
        'group': GROUP_DISCOVER,
        'hidden_from_role_dialog': True,
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

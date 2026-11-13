"""The seeded Lifecycle Stage Groups: one default group per entity type (PRD #1208).

They reproduce the transition maps the app had before stage groups, so an
install that doesn't configure anything behaves as before. Migration
``t1_lifecycle_stage_groups`` writes the same rows (with its own copy, as
migrations don't import app code) and backfills existing entities; the startup
seed (``lifecycle_stage_groups_repo.seed_defaults``) writes them on a fresh
database, which ``create_all()`` initializes without running migrations.

While no group is stored for an entity type (e.g. the in-memory test database),
the lifecycle service uses these definitions directly.
"""
from typing import Dict, List, Tuple

# Stage Categories, in lifecycle order. Code branches on these, never on labels.
DRAFT = 'draft'
REVIEW = 'review'
ACTIVE = 'active'
DEPRECATED = 'deprecated'
RETIRED = 'retired'
STAGE_CATEGORIES: Tuple[str, ...] = (DRAFT, REVIEW, ACTIVE, DEPRECATED, RETIRED)

# The ODCS / ODPS ``status`` an export writes for each category (both standards
# recommend proposed / draft / active / deprecated / retired).
STANDARD_STATUS_BY_CATEGORY: Dict[str, str] = {
    DRAFT: 'draft',
    REVIEW: 'proposed',
    ACTIVE: 'active',
    DEPRECATED: 'deprecated',
    RETIRED: 'retired',
}

DATA_PRODUCT = 'data_product'
DATA_CONTRACT = 'data_contract'
ASSET = 'asset'
LIFECYCLE_ENTITY_TYPES: Tuple[str, ...] = (DATA_PRODUCT, DATA_CONTRACT, ASSET)

# key -> (label, category, colour)
_STAGES: Dict[str, Tuple[str, str, str]] = {
    'draft': ('Draft', DRAFT, 'gray'),
    'sandbox': ('Sandbox', DRAFT, 'purple'),
    'proposed': ('Proposed', REVIEW, 'blue'),
    'under_review': ('Under Review', REVIEW, 'amber'),
    'approved': ('Approved', REVIEW, 'teal'),
    'active': ('Active', ACTIVE, 'green'),
    'deprecated': ('Deprecated', DEPRECATED, 'orange'),
    'retired': ('Retired', RETIRED, 'red'),
}

# The category of every seeded stage key (the same in each default group)
DEFAULT_STAGE_CATEGORIES: Dict[str, str] = {key: s[1] for key, s in _STAGES.items()}

# Per entity type: ordered stage keys (the first is the initial stage) and the
# allowed transitions (stage key -> next stage keys).
_DEFAULT_TRANSITIONS: Dict[str, Dict[str, List[str]]] = {
    DATA_PRODUCT: {
        'draft': ['sandbox', 'proposed', 'deprecated'],
        'sandbox': ['draft', 'proposed', 'deprecated'],
        'proposed': ['draft', 'under_review', 'deprecated'],
        'under_review': ['draft', 'approved', 'deprecated'],
        'approved': ['active', 'draft', 'deprecated'],
        'active': ['deprecated'],
        'deprecated': ['retired', 'active'],
        'retired': [],
    },
    DATA_CONTRACT: {
        'draft': ['proposed', 'deprecated'],
        # A steward can approve directly from "proposed" (the approve endpoint
        # is documented as PROPOSED/UNDER_REVIEW -> APPROVED). "under_review"
        # stays an optional intermediate step rather than a mandatory one.
        'proposed': ['draft', 'under_review', 'approved', 'deprecated'],
        'under_review': ['draft', 'approved', 'deprecated'],
        'approved': ['active', 'draft', 'deprecated'],
        'active': ['deprecated'],
        'deprecated': ['retired', 'active'],
        'retired': [],
    },
    ASSET: {
        'draft': ['active', 'deprecated'],
        'active': ['deprecated'],
        'deprecated': ['retired', 'active'],
        'retired': [],
    },
}

DEFAULT_GROUP_IDS: Dict[str, str] = {
    DATA_PRODUCT: '717c78be-b81b-501f-9851-4f1fc7313f17',
    DATA_CONTRACT: '67dd0305-a4d4-5e3b-92d6-6f1f7955b565',
    ASSET: '587296b9-5b92-5880-be60-5a1b2f299ed5',
}

DEFAULT_GROUP_NAMES: Dict[str, str] = {
    DATA_PRODUCT: 'Default data product lifecycle',
    DATA_CONTRACT: 'Default data contract lifecycle',
    ASSET: 'Default asset lifecycle',
}


def default_transitions(entity_type: str) -> Dict[str, List[str]]:
    """The seeded transition map of ``entity_type`` (a copy), targets in stage order
    (the order ``lifecycle_service`` lists allowed transitions in)."""
    transitions = _DEFAULT_TRANSITIONS[entity_type]
    order = {key: i for i, key in enumerate(transitions)}
    return {k: sorted(v, key=order.__getitem__) for k, v in transitions.items()}


def default_group_definition(entity_type: str) -> dict:
    """The seeded default group of ``entity_type``, in the group write shape.

    ``{id, name, description, entity_type, is_default_for_type, stages,
    transitions}``; a stage is ``{key, label, category, color, order,
    is_initial}``, a transition ``{from_key, to_key}``.
    """
    transitions = _DEFAULT_TRANSITIONS[entity_type]
    stages = []
    for order, key in enumerate(transitions):
        label, category, color = _STAGES[key]
        stages.append({
            'key': key, 'label': label, 'category': category, 'color': color,
            'order': order, 'is_initial': order == 0,
        })
    return {
        'id': DEFAULT_GROUP_IDS[entity_type],
        'name': DEFAULT_GROUP_NAMES[entity_type],
        'description': 'Seeded lifecycle; reproduces the built-in transitions.',
        'entity_type': entity_type,
        'is_default_for_type': True,
        'stages': stages,
        'transitions': [
            {'from_key': src, 'to_key': dst}
            for src, targets in transitions.items() for dst in targets
        ],
    }

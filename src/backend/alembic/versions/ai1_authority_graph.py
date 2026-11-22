"""Authority Resolution — graph-native refs, prerequisites, provenance

Revision ID: ai1_authority_graph
Revises: ah1_authority_versioning
Create Date: 2026-10-16

ARF v2 schema: ARs stop being standalone scalar-field rows and become graph
nodes with pluggable field resolution and declarative prerequisite chains.

* ``authority_resource_refs`` — one row per AR field (``actor_identity``,
  ``object_id``, ``domain_context.<key>``) that is backed by something richer
  than a literal. ``ref_type`` is ``literal``, ``ontos_entity`` (an Ontos
  Business Concept / Domain / Term / Data Product / … resolved via the
  existing semantic-link + entity-domain-association plumbing) or ``mcp_tool``
  (resolved at eval time via a UC Catalog MCP service or an AI Gateway Unity
  Gateway MCP, both discovered through the Databricks SDK). The AR row's
  own scalar columns continue to hold the *cached* resolved value so the
  list view, search, and existing REST shape keep working unchanged.

* ``authority_prerequisites`` — AR → AR edges keyed by family slug (never
  version UUIDs). The resolver walks them depth-first with cycle detection;
  a required prerequisite returning ``denied`` / ``no_authority`` short-
  circuits the outer AR to ``denied`` with the chain carried in provenance.

* ``authority_relations.resolver_auth`` — per-AR flag selecting whether
  MCP calls made while resolving this AR use the calling agent's token
  (OBO, default) or the Ontos app SP's token (``app_sp``, pinned by the
  author for stability).

* ``authority_decisions.provenance`` — JSON column carrying the prerequisite
  chain + the resolved refs + their source for the decision just taken.

No backfill (PoC environment wipes the schema on boot in LOCAL; prod rolls
forward with the defaults).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ai1_authority_graph'
down_revision: Union[str, None] = 'ah1_authority_versioning'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- authority_relations: per-AR MCP-auth selector --------------------
    op.add_column(
        'authority_relations',
        sa.Column('resolver_auth', sa.String(), nullable=False, server_default='obo'),
    )

    # --- authority_decisions: provenance JSON ------------------------------
    op.add_column(
        'authority_decisions',
        sa.Column('provenance', sa.JSON(), nullable=True),
    )

    # --- authority_resource_refs: typed field pointers --------------------
    op.create_table(
        'authority_resource_refs',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column(
            'relation_id', sa.String(),
            sa.ForeignKey('authority_relations.id', ondelete='CASCADE'),
            nullable=False, index=True,
        ),
        # JSON-pointer-ish path on the AR, e.g. ``actor_identity``, ``object_id``,
        # ``domain_context.brand`` — scoped per AR; one ref per field.
        sa.Column('field_path', sa.String(), nullable=False),
        sa.Column('ref_type', sa.String(), nullable=False),  # literal|ontos_entity|mcp_tool

        # literal branch
        sa.Column('literal_value', sa.Text(), nullable=True),

        # ontos_entity branch — polymorphic reference to another Ontos entity
        # (business_concept | business_term | data_domain | data_product | asset | ...).
        sa.Column('entity_type', sa.String(), nullable=True),
        sa.Column('entity_id', sa.String(), nullable=True),

        # mcp_tool branch — the SDK's full service name
        # (``mcp-services/system.ai.github``,
        # ``mcp-services/<cat>.<schema>.ontos_mcp_service``) + the tool name on
        # that server. mcp_params is a Jinja template rendered against the
        # resolve-time request. mcp_result_pointer is a JSONPath into the tool
        # response (default ``$`` — take the whole value).
        sa.Column('mcp_service_name', sa.String(), nullable=True),
        sa.Column('mcp_tool_name', sa.String(), nullable=True),
        sa.Column('mcp_params', sa.JSON(), nullable=True),
        sa.Column('mcp_result_pointer', sa.String(), nullable=False, server_default='$'),

        # Cached resolved value for display / audit; the AR's own scalar
        # column holds the same string so existing views keep working.
        sa.Column('cached_label', sa.Text(), nullable=True),
        sa.Column('cached_at', sa.DateTime(timezone=True), nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        sa.UniqueConstraint('relation_id', 'field_path', name='uq_authority_resource_refs_field'),
    )

    # --- authority_prerequisites: AR → AR edges, per-family slug ----------
    op.create_table(
        'authority_prerequisites',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('relation_family_slug', sa.String(), nullable=False, index=True),
        sa.Column('prerequisite_family_slug', sa.String(), nullable=False, index=True),
        sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        sa.UniqueConstraint(
            'relation_family_slug', 'prerequisite_family_slug',
            name='uq_authority_prerequisites_edge',
        ),
        # A self-loop is always a cycle; reject at write time instead of
        # waiting for the eval-time cycle detector.
        sa.CheckConstraint(
            'relation_family_slug <> prerequisite_family_slug',
            name='ck_authority_prerequisites_no_self_loop',
        ),
    )


def downgrade() -> None:
    op.drop_table('authority_prerequisites')
    op.drop_table('authority_resource_refs')
    op.drop_column('authority_decisions', 'provenance')
    op.drop_column('authority_relations', 'resolver_auth')

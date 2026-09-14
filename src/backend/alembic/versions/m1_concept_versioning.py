"""Concept-versioning schema foundation (P0-1).

Adds the concept-version spine for the ontology-versioning engine, mirroring the
Data Products versioning pattern (indexed ``version`` + ``parent_*_id`` self-ref
lineage, see j0577f481hh3 / j1_add_version_family_id):

- ``concept_version`` [NEW]: ``(iri, version)`` is the versioned unit; ``iri`` is
  the stable identity. Exactly one ``is_current=true`` row per ``iri`` (the hot
  set), enforced at the DB level by a PARTIAL UNIQUE INDEX
  ``UNIQUE(iri) WHERE is_current`` so the two-``is_current`` corruption is
  structurally impossible, not merely transaction-disciplined.
- ``rdf_triples`` [EXISTING]: add ONE column ``concept_version_id`` FK — the only
  change to an existing table. Triple ownership rule (P0-1): a triple's owning
  concept-version is determined by its SUBJECT IRI; blank-node closures follow the
  IRI subject they hang off.
- ``scheme_membership`` [NEW]: unversioned many-to-many ``(concept_iri, scheme_iri)``
  (``skos:inScheme``). No "scheme version" object exists.

Backfill (idempotent + reversible): every existing concept (subject of an
``rdf:type`` triple whose object is ``skos:Concept`` / ``owl:Class`` /
``rdfs:Class``) becomes version 1, ``is_current=true``. Every triple whose subject
equals a concept IRI gets its ``concept_version_id`` set (subject-IRI ownership).
``scheme_membership`` is seeded from existing ``skos:inScheme`` triples.

Release manifests (release_manifest / manifest_pin) are intentionally NOT built
here — deferred to P2, gated on a named version-pinning consumer.

Postgres-targeted (partial unique index, gen_random_uuid); the project deploys on
Postgres/Lakebase.

Revision ID: m1_concept_versioning
Revises: l1_entity_domain_associations
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


# revision identifiers, used by Alembic.
revision: str = 'm1_concept_versioning'
down_revision: Union[str, None] = 'l1_entity_domain_associations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# rdf:type predicate and the object IRIs that mark a subject as a versionable
# concept. skos:ConceptScheme is intentionally excluded: schemes are unversioned
# membership tags, not concepts (see PRD §3.2).
_RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
_SKOS_IN_SCHEME = 'http://www.w3.org/2004/02/skos/core#inScheme'
_CONCEPT_TYPES = (
    'http://www.w3.org/2004/02/skos/core#Concept',
    'http://www.w3.org/2002/07/owl#Class',
    'http://www.w3.org/2000/01/rdf-schema#Class',
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. concept_version — the versioned unit is (iri, version).
    # ------------------------------------------------------------------
    op.create_table(
        'concept_version',
        sa.Column('id', PG_UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        # Stable identity across versions.
        sa.Column('iri', sa.Text(), nullable=False),
        # Monotonic per iri.
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        # Exactly one true per iri (enforced by partial unique index below).
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        # Self-referential lineage / fork.
        sa.Column('parent_version_id', PG_UUID(as_uuid=True), nullable=True),
        # Set on a 2B meaning-split (new IRI replaces an old one).
        sa.Column('replaces_iri', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ['parent_version_id'], ['concept_version.id'],
            name='fk_concept_version_parent_version_id', ondelete='SET NULL',
        ),
        # (iri, version) is the versioned unit — no dup versions per iri.
        sa.UniqueConstraint('iri', 'version', name='uq_concept_version_iri_version'),
    )
    op.create_index('ix_concept_version_iri', 'concept_version', ['iri'])
    op.create_index('ix_concept_version_version', 'concept_version', ['version'])
    op.create_index('ix_concept_version_is_current', 'concept_version', ['is_current'])
    op.create_index('ix_concept_version_parent_version_id', 'concept_version',
                    ['parent_version_id'])

    # PARTIAL UNIQUE INDEX: at most one is_current=true row per iri. This makes
    # the "two current versions of one concept" corruption structurally
    # impossible at the DB level (P0-1 hard requirement).
    op.create_index(
        'uq_concept_version_current_per_iri',
        'concept_version',
        ['iri'],
        unique=True,
        postgresql_where=sa.text('is_current'),
    )

    # ------------------------------------------------------------------
    # 2. rdf_triples: the ONE new column — which concept-version owns the triple.
    # ------------------------------------------------------------------
    op.add_column(
        'rdf_triples',
        sa.Column('concept_version_id', PG_UUID(as_uuid=True), nullable=True),
    )
    op.create_index('ix_rdf_triples_concept_version_id', 'rdf_triples',
                    ['concept_version_id'])
    op.create_foreign_key(
        'fk_rdf_triples_concept_version_id',
        'rdf_triples', 'concept_version',
        ['concept_version_id'], ['id'],
        ondelete='SET NULL',
    )

    # ------------------------------------------------------------------
    # 3. scheme_membership — unversioned m:n (concept_iri, scheme_iri).
    # ------------------------------------------------------------------
    op.create_table(
        'scheme_membership',
        sa.Column('id', PG_UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('concept_iri', sa.Text(), nullable=False),
        sa.Column('scheme_iri', sa.Text(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.UniqueConstraint('concept_iri', 'scheme_iri',
                            name='uq_scheme_membership_concept_scheme'),
    )
    op.create_index('ix_scheme_membership_concept_iri', 'scheme_membership',
                    ['concept_iri'])
    op.create_index('ix_scheme_membership_scheme_iri', 'scheme_membership',
                    ['scheme_iri'])

    # ------------------------------------------------------------------
    # 4. Backfill (idempotent). Reversibility is provided by downgrade()
    #    dropping every object created above.
    # ------------------------------------------------------------------
    _backfill()


def _backfill() -> None:
    concept_types = ", ".join("'%s'" % t for t in _CONCEPT_TYPES)

    # 4a. Every existing concept -> version 1, is_current=true. Idempotent via
    #     NOT EXISTS so a re-run mints nothing new.
    op.execute(f"""
        INSERT INTO concept_version (id, iri, version, is_current, status, created_at)
        SELECT gen_random_uuid(), t.subject_uri, 1, true, 'active', now()
        FROM (
            SELECT DISTINCT subject_uri
            FROM rdf_triples
            WHERE predicate_uri = '{_RDF_TYPE}'
              AND object_is_uri = true
              AND object_value IN ({concept_types})
        ) t
        WHERE NOT EXISTS (
            SELECT 1 FROM concept_version cv WHERE cv.iri = t.subject_uri
        );
    """)

    # 4b. Own every triple by its SUBJECT IRI (triple-ownership rule). Idempotent
    #     via the IS NULL guard; only sets triples whose subject is a concept IRI.
    op.execute("""
        UPDATE rdf_triples r
        SET concept_version_id = cv.id
        FROM concept_version cv
        WHERE cv.iri = r.subject_uri
          AND cv.is_current = true
          AND r.concept_version_id IS NULL;
    """)

    # 4c. Seed scheme membership from existing skos:inScheme triples. Idempotent
    #     via NOT EXISTS.
    op.execute(f"""
        INSERT INTO scheme_membership (id, concept_iri, scheme_iri, created_at)
        SELECT gen_random_uuid(), t.subject_uri, t.object_value, now()
        FROM (
            SELECT DISTINCT subject_uri, object_value
            FROM rdf_triples
            WHERE predicate_uri = '{_SKOS_IN_SCHEME}'
              AND object_is_uri = true
        ) t
        WHERE NOT EXISTS (
            SELECT 1 FROM scheme_membership sm
            WHERE sm.concept_iri = t.subject_uri
              AND sm.scheme_iri = t.object_value
        );
    """)


def downgrade() -> None:
    # Reverse order. Dropping concept_version_id + the tables removes all backfilled data.
    op.drop_index('ix_scheme_membership_scheme_iri', 'scheme_membership')
    op.drop_index('ix_scheme_membership_concept_iri', 'scheme_membership')
    op.drop_table('scheme_membership')

    op.drop_constraint('fk_rdf_triples_concept_version_id', 'rdf_triples',
                       type_='foreignkey')
    op.drop_index('ix_rdf_triples_concept_version_id', 'rdf_triples')
    op.drop_column('rdf_triples', 'concept_version_id')

    op.drop_index('uq_concept_version_current_per_iri', 'concept_version')
    op.drop_index('ix_concept_version_parent_version_id', 'concept_version')
    op.drop_index('ix_concept_version_is_current', 'concept_version')
    op.drop_index('ix_concept_version_version', 'concept_version')
    op.drop_index('ix_concept_version_iri', 'concept_version')
    op.drop_table('concept_version')

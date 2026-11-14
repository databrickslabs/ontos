"""Move asset tags onto the shared tag store and drop assets.tags

Revision ID: s4_asset_tags_shared_store
Revises: r2_canonical_relationship_types
Create Date: 2026-11-12

#1422: assets kept their tags in ``assets.tags``, a JSON list of plain strings
that the tag picker and the tags panel don't read. Each entry moves onto
``entity_tag_associations`` (entity type ``asset``), and the column is dropped
in the same migration; there is no read-only release.

An entry is a tag name in the default namespace, or ``namespace/name`` in that
namespace, matched the way ``TagRepository.find_or_create_tag`` does: an existing
tag is reused, a missing one is created. An entry whose namespace doesn't exist
is kept whole as a name in the default namespace, so nothing is lost. Duplicate
entries are assigned once; the entries carry no values.

Downgrade re-adds ``assets.tags`` from the associations (best effort): the name
for default-namespace tags, ``namespace/name`` for the others. The associations
stay.
"""
import json
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 's4_asset_tags_shared_store'
down_revision: Union[str, None] = 'r2_canonical_relationship_types'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_NAMESPACE = 'default'
_SEPARATOR = '/'
_ENTITY_TYPE = 'asset'


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if not {'assets', 'tag_namespaces', 'tags', 'entity_tag_associations'} <= tables:
        return
    if 'tags' not in {c['name'] for c in inspector.get_columns('assets')}:
        return
    uuid_param = 'CAST(:{} AS UUID)' if bind.dialect.name == 'postgresql' else ':{}'

    rows = bind.execute(sa.text("SELECT id, tags FROM assets WHERE tags IS NOT NULL")).all()

    namespaces = {name: str(ns_id) for ns_id, name in bind.execute(sa.text(
        "SELECT id, name FROM tag_namespaces"
    )).all()}
    tags = {(str(ns_id), name): str(tag_id) for tag_id, name, ns_id in bind.execute(sa.text(
        "SELECT id, name, namespace_id FROM tags"
    )).all()}
    assigned = {(str(eid), str(tid)) for eid, tid in bind.execute(sa.text(
        "SELECT entity_id, tag_id FROM entity_tag_associations WHERE entity_type = :entity_type"
    ), {'entity_type': _ENTITY_TYPE}).all()}

    def namespace_id(name: str):
        if name not in namespaces and name == _DEFAULT_NAMESPACE:
            ns_id = str(uuid.uuid4())
            bind.execute(sa.text(
                f"INSERT INTO tag_namespaces (id, name, description, created_by) "
                f"VALUES ({uuid_param.format('id')}, :name, 'Default system namespace', 'system')"
            ), {'id': ns_id, 'name': name})
            namespaces[name] = ns_id
        return namespaces.get(name)

    def tag_id_for(entry: str):
        ns_name, tag_name = _DEFAULT_NAMESPACE, entry
        if _SEPARATOR in entry:
            head, tail = entry.split(_SEPARATOR, 1)
            if tail.strip() and (head == _DEFAULT_NAMESPACE or head in namespaces):
                ns_name, tag_name = head, tail.strip()
        ns_id = namespace_id(ns_name)
        if ns_id is None:
            return None
        if (ns_id, tag_name) not in tags:
            tag_id = str(uuid.uuid4())
            bind.execute(sa.text(
                f"INSERT INTO tags (id, name, status, namespace_id, created_by) "
                f"VALUES ({uuid_param.format('id')}, :name, 'active', {uuid_param.format('ns')}, 'system')"
            ), {'id': tag_id, 'name': tag_name, 'ns': ns_id})
            tags[(ns_id, tag_name)] = tag_id
        return tags[(ns_id, tag_name)]

    for asset_id, raw in rows:
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, list):
            continue
        for entry in raw:
            if not isinstance(entry, str) or not entry.strip():
                continue
            tag_id = tag_id_for(entry.strip())
            if tag_id is None or (str(asset_id), tag_id) in assigned:
                continue
            bind.execute(sa.text(
                f"INSERT INTO entity_tag_associations (id, tag_id, entity_id, entity_type, assigned_by) "
                f"VALUES ({uuid_param.format('id')}, {uuid_param.format('tag')}, :entity, :entity_type, 'system')"
            ), {'id': str(uuid.uuid4()), 'tag': tag_id, 'entity': str(asset_id), 'entity_type': _ENTITY_TYPE})
            assigned.add((str(asset_id), tag_id))

    with op.batch_alter_table('assets') as batch:
        batch.drop_column('tags')


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if 'assets' not in tables:
        return
    if 'tags' not in {c['name'] for c in inspector.get_columns('assets')}:
        with op.batch_alter_table('assets') as batch:
            batch.add_column(sa.Column('tags', sa.JSON(), nullable=True))
    if not {'tag_namespaces', 'tags', 'entity_tag_associations'} <= tables:
        return

    entries: dict = {}
    for entity_id, ns_name, tag_name in bind.execute(sa.text(
        "SELECT eta.entity_id, ns.name, t.name FROM entity_tag_associations eta "
        "JOIN tags t ON t.id = eta.tag_id "
        "JOIN tag_namespaces ns ON ns.id = t.namespace_id "
        "WHERE eta.entity_type = :entity_type "
        "ORDER BY ns.name, t.name"
    ), {'entity_type': _ENTITY_TYPE}).all():
        entry = tag_name if ns_name == _DEFAULT_NAMESPACE else f"{ns_name}{_SEPARATOR}{tag_name}"
        entries.setdefault(str(entity_id), []).append(entry)

    for (asset_id,) in bind.execute(sa.text("SELECT id FROM assets")).all():
        bind.execute(sa.text("UPDATE assets SET tags = :tags WHERE id = :id"),
                     {'tags': json.dumps(entries.get(str(asset_id), [])), 'id': asset_id})

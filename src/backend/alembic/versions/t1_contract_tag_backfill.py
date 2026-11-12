"""Backfill contract tag assignments from the ODCS tag rows

Revision ID: t1_contract_tag_backfill
Revises: s1_workflow_is_customized
Create Date: 2026-11-12

#1484: contracts imported from ODCS files kept their tags only in
``data_contract_tags``, which the contract page doesn't show. New imports also
write the tag assignments the page shows (``entity_tag_associations``); this
backfills them for contracts imported before.

For each ODCS tag row: a bare name is a tag in the default namespace, and
``namespace/name`` a tag in that namespace. A missing tag is created; a row whose
namespace doesn't exist is skipped (the ODCS export keeps it). Assignments that
exist are left as they are. The ODCS rows stay.

Downgrade does nothing: a backfilled assignment can't be told apart from one a
user made since.
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 't1_contract_tag_backfill'
down_revision: Union[str, None] = 's1_workflow_is_customized'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_NAMESPACE = 'default'
_SEPARATOR = '/'


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if not {'data_contract_tags', 'tag_namespaces', 'tags', 'entity_tag_associations'} <= tables:
        return
    uuid_param = 'CAST(:{} AS UUID)' if bind.dialect.name == 'postgresql' else ':{}'

    rows = bind.execute(sa.text(
        "SELECT contract_id, name FROM data_contract_tags WHERE name IS NOT NULL"
    )).all()
    rows = [(str(cid), name.strip()) for cid, name in rows if name and name.strip()]
    if not rows:
        return

    namespaces = {name: str(ns_id) for ns_id, name in bind.execute(sa.text(
        "SELECT id, name FROM tag_namespaces"
    )).all()}
    tags = {(str(ns_id), name): str(tag_id) for tag_id, name, ns_id in bind.execute(sa.text(
        "SELECT id, name, namespace_id FROM tags"
    )).all()}
    assigned = {(str(eid), str(tid)) for eid, tid in bind.execute(sa.text(
        "SELECT entity_id, tag_id FROM entity_tag_associations WHERE entity_type = 'data_contract'"
    )).all()}

    def namespace_id(name: str):
        if name not in namespaces and name == _DEFAULT_NAMESPACE:
            ns_id = str(uuid.uuid4())
            bind.execute(sa.text(
                f"INSERT INTO tag_namespaces (id, name, description, created_by) "
                f"VALUES ({uuid_param.format('id')}, :name, 'Default system namespace', 'system')"
            ), {'id': ns_id, 'name': name})
            namespaces[name] = ns_id
        return namespaces.get(name)

    for contract_id, raw in rows:
        ns_name, tag_name = raw.split(_SEPARATOR, 1) if _SEPARATOR in raw else (_DEFAULT_NAMESPACE, raw)
        ns_id = namespace_id(ns_name)
        if ns_id is None or not tag_name:
            continue
        tag_id = tags.get((ns_id, tag_name))
        if tag_id is None:
            tag_id = str(uuid.uuid4())
            bind.execute(sa.text(
                f"INSERT INTO tags (id, name, status, namespace_id, created_by) "
                f"VALUES ({uuid_param.format('id')}, :name, 'active', {uuid_param.format('ns')}, 'system')"
            ), {'id': tag_id, 'name': tag_name, 'ns': ns_id})
            tags[(ns_id, tag_name)] = tag_id
        if (contract_id, tag_id) in assigned:
            continue
        bind.execute(sa.text(
            f"INSERT INTO entity_tag_associations (id, tag_id, entity_id, entity_type, assigned_by) "
            f"VALUES ({uuid_param.format('id')}, {uuid_param.format('tag')}, :entity, 'data_contract', 'system')"
        ), {'id': str(uuid.uuid4()), 'tag': tag_id, 'entity': contract_id})
        assigned.add((contract_id, tag_id))


def downgrade() -> None:
    pass

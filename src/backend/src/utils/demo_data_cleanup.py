"""Plan and run the demo data clear (#1044).

The demo teardown deletes the rows listed in the demo packs. Rows created
after the demo was loaded have their own ids, so they are not in the packs.
Some of them are part of a demo row and can't exist without it (a compliance
run of a demo policy and its results, a custom property added to a demo
product, a team member re-created by an edit): those are deleted with it.

Other rows are user content that merely refers to demo data (an asset of a
demo asset type, a tag in a demo tag namespace, an MDM configuration on a demo
contract, a product owned by a demo team). Deleting or detaching them would
change the user's data, so the clear stops instead and lists them, and the
admin decides what to do with them.

Only the foreign keys known to point at a part of the referenced row
(``PART_OF``), or a link whose other end is demo data too (``LINKS``), lead to
deletes. Every other reference to a demo row blocks the clear.
"""
from __future__ import annotations

import importlib
import pkgutil
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import Table, and_, delete, or_, select
from sqlalchemy.orm import Session

from src.common.database import Base

# (child table, foreign key column): the child row is part of the referenced
# row (its details, runs and results, members), so it goes with it.
PART_OF: Set[Tuple[str, str]] = {
    # Data products and their ports and teams
    ('data_product_descriptions', 'product_id'),
    ('data_product_authoritative_definitions', 'product_id'),
    ('data_product_custom_properties', 'product_id'),
    ('data_product_input_ports', 'product_id'),
    ('data_product_output_ports', 'product_id'),
    ('data_product_management_ports', 'product_id'),
    ('data_product_support_channels', 'product_id'),
    ('data_product_teams', 'product_id'),
    ('data_product_subscriptions', 'product_id'),
    ('data_product_output_port_sbom', 'output_port_id'),
    ('data_product_output_port_input_contracts', 'output_port_id'),
    ('data_product_team_members', 'team_id'),
    # Data contracts, their schema, servers, roles and runs
    ('data_contract_tags', 'contract_id'),
    ('data_contract_servers', 'contract_id'),
    ('data_contract_roles', 'contract_id'),
    ('data_contract_team', 'contract_id'),
    ('data_contract_support', 'contract_id'),
    ('data_contract_pricing', 'contract_id'),
    ('data_contract_authoritative_definitions', 'contract_id'),
    ('data_contract_custom_properties', 'contract_id'),
    ('data_contract_sla_properties', 'contract_id'),
    ('data_contract_schema_objects', 'contract_id'),
    ('data_contract_comments', 'contract_id'),
    ('data_contract_team_metadata', 'contract_id'),
    ('data_contract_validation_runs', 'contract_id'),
    ('data_contract_validation_results', 'run_id'),
    ('data_quality_check_runs', 'contract_id'),
    ('data_quality_check_results', 'run_id'),
    ('data_profiling_runs', 'contract_id'),
    ('suggested_quality_checks', 'contract_id'),
    ('suggested_quality_checks', 'profile_run_id'),
    ('data_contract_server_properties', 'server_id'),
    ('data_contract_role_properties', 'role_id'),
    ('data_contract_schema_properties', 'object_id'),
    ('data_contract_schema_properties', 'parent_property_id'),
    ('data_contract_quality_checks', 'object_id'),
    ('data_contract_quality_checks', 'property_id'),
    ('data_contract_schema_object_authoritative_definitions', 'schema_object_id'),
    ('data_contract_schema_object_custom_properties', 'schema_object_id'),
    ('data_contract_schema_object_relationships', 'schema_object_id'),
    ('data_contract_schema_property_authoritative_definitions', 'property_id'),
    # Added by #609; an entry for a table that doesn't exist yet is never matched
    ('data_contract_schema_property_custom_properties', 'property_id'),
    ('data_contract_schema_property_relationships', 'property_id'),
    # Compliance policies: their runs and results
    ('compliance_runs', 'policy_id'),
    ('compliance_results', 'run_id'),
    # Asset reviews and MDM configurations: their items, runs and results
    ('reviewed_assets', 'review_request_id'),
    ('term_mapping_suggestions', 'review_request_id'),
    ('term_mapping_suggestions', 'reviewed_asset_id'),
    ('mdm_source_links', 'config_id'),
    ('mdm_match_runs', 'config_id'),
    ('mdm_match_runs', 'source_link_id'),
    ('mdm_match_candidates', 'run_id'),
    # Workflows: their steps and executions
    ('workflow_steps', 'workflow_id'),
    ('workflow_executions', 'workflow_id'),
    ('workflow_step_executions', 'execution_id'),
    ('workflow_step_executions', 'step_id'),
    ('agreement_wizard_sessions', 'workflow_id'),
    # Teams, projects and tag namespaces: their members and permissions
    ('team_members', 'team_id'),
    ('project_teams', 'project_id'),
    ('tag_namespace_permissions', 'namespace_id'),
}

# (child table, foreign key column) -> the columns naming the link's other
# end. The link goes with the demo row only when its other end is demo data
# too; a link to the user's own entity blocks the clear.
LINKS: Dict[Tuple[str, str], Tuple[str, ...]] = {
    ('entity_tag_associations', 'tag_id'): ('entity_id',),
    ('entity_domain_associations', 'domain_id'): ('entity_id',),
    ('business_owners', 'role_id'): ('object_id',),
    ('asset_relationships', 'source_asset_id'): ('target_asset_id',),
    ('asset_relationships', 'target_asset_id'): ('source_asset_id',),
    ('project_teams', 'team_id'): ('project_id',),
}

RowKey = Tuple[str, ...]
_MAX_DEPTH = 20

# referenced table -> [(child table, child column, referenced column)]
_references: Optional[Dict[str, List[Tuple[Table, str, str]]]] = None


def _referencing_foreign_keys() -> Dict[str, List[Tuple[Table, str, str]]]:
    global _references
    if _references is None:
        import src.db_models as models
        for module in pkgutil.iter_modules(models.__path__):
            importlib.import_module(f"{models.__name__}.{module.name}")
        refs: Dict[str, List[Tuple[Table, str, str]]] = defaultdict(list)
        for table in Base.metadata.tables.values():
            for fk in table.foreign_keys:
                refs[fk.column.table.name].append((table, fk.parent.name, fk.column.name))
        _references = refs
    return _references


def _key(value) -> str:
    return str(value).lower()


def _typed(column, values: Iterable) -> list:
    """Convert ids (strings in the demo packs) to the column's Python type,
    so comparisons use the column as is (no cast that would skip its index)."""
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return list(values)
    if python_type is uuid.UUID:
        typed = []
        for value in values:
            try:
                typed.append(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))
            except ValueError:
                continue  # not an id of this column
        return typed
    if python_type is int:
        typed = []
        for value in values:
            try:
                typed.append(int(value))
            except (TypeError, ValueError):
                continue
        return typed
    return [str(value) for value in values]


def _rows_where(table: Table, keys: Sequence[RowKey]):
    pk = list(table.primary_key.columns)
    if len(pk) == 1:
        return pk[0].in_(_typed(pk[0], [k[0] for k in keys]))
    return or_(*[
        and_(*[col == _typed(col, [value])[0] for col, value in zip(pk, key, strict=True)])
        for key in keys
    ])


@dataclass
class DemoClearPlan:
    """What clearing the demo data deletes, and what stops it."""

    # (table, primary key column, ids) from the demo packs, in delete order
    demo: List[Tuple[str, str, List[str]]]
    # table -> row keys of rows that are part of demo rows, with their depth
    dependents: Dict[str, Dict[RowKey, int]] = field(default_factory=dict)
    # (table, column, referenced table) -> ids of user rows referring to demo rows
    blocking: Dict[Tuple[str, str, str], List[str]] = field(default_factory=dict)

    def blocking_report(self) -> List[Dict[str, object]]:
        return [
            {
                "table": table,
                "column": column,
                "references": referenced,
                "count": len(ids),
                "ids": ids,
            }
            for (table, column, referenced), ids in sorted(self.blocking.items())
        ]

    def deletes_report(self, db: Session) -> Dict[str, List[str]]:
        """Ids per table that the clear would delete (demo rows that exist, then their parts)."""
        report: Dict[str, List[str]] = {}
        tables = Base.metadata.tables
        for table_name, pk_column, ids in self.demo:
            table = tables[table_name]
            column = table.c[pk_column]
            # One entry per row (a table with a composite key can have several
            # rows per id of the demo pack)
            existing = [
                "/".join(str(v) for v in row) for row in db.execute(
                    select(*table.primary_key.columns).where(column.in_(_typed(column, ids)))
                )
            ]
            if existing:
                report.setdefault(table_name, []).extend(existing)
        for table_name, rows in self.dependents.items():
            report.setdefault(table_name, []).extend("/".join(key) for key in rows)
        return report


def plan_demo_clear(db: Session, demo: List[Tuple[str, str, List[str]]]) -> DemoClearPlan:
    """Find the rows that are part of the demo rows, and the user rows that
    refer to them, without changing anything.

    The demo rows are deleted children first, by the foreign keys between the
    tables: the order of the packs isn't enough once several presets are
    loaded (a later pack's contracts would come before an earlier pack's MDM
    configurations that reference them).
    """
    _referencing_foreign_keys()  # loads the models
    rank = {t.name: i for i, t in enumerate(reversed(Base.metadata.sorted_tables))}
    demo = sorted(demo, key=lambda entry: rank.get(entry[0], len(rank)))
    plan = DemoClearPlan(demo=demo)
    tables = Base.metadata.tables
    # table -> (column the demo pack identifies its rows by, ids)
    demo_rows: Dict[str, Tuple[str, Set[str]]] = {}
    demo_ids: Set[str] = set()
    for table_name, pk_column, ids in demo:
        demo_rows[table_name] = (pk_column, {_key(i) for i in ids})
        demo_ids.update(_key(i) for i in ids)

    candidates: Dict[Tuple[str, str, str], Set[RowKey]] = defaultdict(set)
    # (table, referenced column, ids of rows being removed, depth)
    queue: List[Tuple[str, str, List[str], int]] = [
        (table_name, pk_column, ids, 0) for table_name, pk_column, ids in demo
    ]
    while queue:
        table_name, column, ids, depth = queue.pop(0)
        for child, child_column, referenced in _referencing_foreign_keys().get(table_name, []):
            if referenced != column or child.name not in tables:
                continue
            fk_column = child.c[child_column]
            values = _typed(fk_column, ids)
            if not values:
                continue
            pk = list(child.primary_key.columns)
            others = LINKS.get((child.name, child_column), ())
            extra = [child.c[name] for name in others]
            demo_column, demo_values = demo_rows.get(child.name, (None, set()))
            marker = [child.c[demo_column]] if demo_column else []
            new_keys: List[RowKey] = []
            for row in db.execute(select(*pk, *marker, *extra).where(fk_column.in_(values))):
                key = tuple(_key(v) for v in row[:len(pk)])
                if marker and _key(row[len(pk)]) in demo_values:
                    continue  # a demo row itself, deleted with the demo rows
                row = tuple(row[:len(pk)]) + tuple(row[len(pk) + len(marker):])
                if (child.name, child_column) in PART_OF:
                    part = True
                elif others:
                    part = all(
                        v is None or _key(v) in demo_ids for v in row[len(pk):]
                    )
                else:
                    part = False
                if not part:
                    candidates[(child.name, child_column, table_name)].add(key)
                    continue
                known = plan.dependents.setdefault(child.name, {})
                if key not in known or (known[key] < depth + 1 and depth < _MAX_DEPTH):
                    # New, or reached through a deeper row: (re)visit what refers
                    # to it so it is deleted before the rows it depends on
                    known[key] = depth + 1
                    new_keys.append(key)
            if new_keys and len(pk) == 1:
                queue.append((child.name, pk[0].name, [k[0] for k in new_keys], depth + 1))

    for (table_name, column, referenced), keys in candidates.items():
        # A row that is also part of a demo row (through another foreign key) goes anyway
        left = sorted("/".join(k) for k in keys if k not in plan.dependents.get(table_name, {}))
        if left:
            plan.blocking[(table_name, column, referenced)] = left
    return plan


def run_demo_clear(db: Session, plan: DemoClearPlan) -> Dict[str, int]:
    """Delete the parts of the demo rows (deepest first), then the demo rows.

    Runs in the caller's transaction; the caller commits, or rolls back if
    anything fails, so the clear is all or nothing.
    """
    tables = Base.metadata.tables
    deleted: Dict[str, int] = defaultdict(int)
    by_depth: Dict[int, Dict[str, List[RowKey]]] = defaultdict(lambda: defaultdict(list))
    for table_name, rows in plan.dependents.items():
        for key, depth in rows.items():
            by_depth[depth][table_name].append(key)
    for depth in sorted(by_depth, reverse=True):
        for table_name, keys in by_depth[depth].items():
            table = tables[table_name]
            result = db.execute(delete(table).where(_rows_where(table, keys)))
            deleted[table_name] += result.rowcount or 0
    for table_name, pk_column, ids in plan.demo:
        table = tables[table_name]
        column = table.c[pk_column]
        result = db.execute(delete(table).where(column.in_(_typed(column, ids))))
        deleted[table_name] += result.rowcount or 0
    return {name: count for name, count in deleted.items() if count}

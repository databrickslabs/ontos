"""Resolve erwin tables to Unity Catalog tables and report drift.

Resolution never creates assets. A table resolves when an existing Ontos
table/view asset's location equals the FQN built from the catalog mapping
(``owner`` → ``catalog.schema``) or a per-table override, compared
case-insensitively. Everything else is reported as unresolved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.model_import.erwin.ir import ErwinEntity, ErwinModel
from src.model_import.erwin.map_contracts import _column_name, table_name
from src.model_import.erwin.types import databricks_type_for, same_type
from src.models.model_import import ModelImportOptions


def candidate_fqn(entity: ErwinEntity, options: ModelImportOptions) -> Optional[str]:
    """The UC FQN the table should have, or None when no mapping applies."""
    override = options.table_overrides.get(entity.id)
    if override:
        return override.strip().lower()
    owner = (entity.schema_name or "").strip().lower()
    target = None
    for m in options.catalog_mappings:
        if m.source.strip().lower() == owner and owner:
            target = m.target
            break
    if target is None:
        target = next((m.target for m in options.catalog_mappings if m.source.strip() == "*"), None)
    if target is None:
        return None
    return f"{target.strip()}.{table_name(entity)}".lower()


@dataclass
class UcColumn:
    name: str
    data_type: Optional[str] = None
    nullable: Optional[bool] = None


@dataclass
class TableDrift:
    missing_in_uc: List[str] = field(default_factory=list)
    extra_in_uc: List[str] = field(default_factory=list)
    type_mismatches: List[Dict[str, str]] = field(default_factory=list)
    nullability_mismatches: List[Dict[str, object]] = field(default_factory=list)

    def is_clean(self) -> bool:
        return not (self.missing_in_uc or self.extra_in_uc or self.type_mismatches or self.nullability_mismatches)

    def as_dict(self) -> Dict[str, object]:
        return {
            "missing_in_uc": self.missing_in_uc,
            "extra_in_uc": self.extra_in_uc,
            "type_mismatches": self.type_mismatches,
            "nullability_mismatches": self.nullability_mismatches,
        }


def table_drift(entity: ErwinEntity, uc_columns: List[UcColumn], dbms: str,
                pk_ids: Optional[set] = None, model: Optional[ErwinModel] = None) -> TableDrift:
    """Compare a modeled table with the columns of its UC table.

    With ``model``, a column typed only through its erwin domain is compared
    using the domain's physical type (as the contract does).
    """
    drift = TableDrift()
    by_name = {c.name.lower(): c for c in uc_columns}
    modeled = [a for a in entity.attributes if not a.logical_only]
    modeled_names = set()
    pk_ids = pk_ids if pk_ids is not None else (
        set(entity.primary_key().attribute_ids) if entity.primary_key() else set()
    )
    for a in modeled:
        name = _column_name(a)
        modeled_names.add(name.lower())
        uc = by_name.get(name.lower())
        if uc is None:
            drift.missing_in_uc.append(name)
            continue
        modeled_type = a.physical_type
        if not modeled_type and model is not None and a.domain_id:
            domain = model.domain(a.domain_id)
            modeled_type = domain.physical_type if domain else None
        if modeled_type and uc.data_type and not same_type(modeled_type, uc.data_type, dbms):
            drift.type_mismatches.append({
                "column": name,
                "modeled": modeled_type,
                "modeled_databricks": databricks_type_for(modeled_type, dbms) or "",
                "actual": uc.data_type,
            })
        required = a.id in pk_ids or a.nullable is False
        if uc.nullable is not None and a.nullable is not None and required == uc.nullable:
            drift.nullability_mismatches.append({
                "column": name, "modeled_required": required, "uc_nullable": uc.nullable,
            })
    drift.extra_in_uc = [c.name for c in uc_columns if c.name.lower() not in modeled_names]
    return drift

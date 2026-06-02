"""Adapter for Data Contracts and their normalised schema objects/properties.

Yields three flavours of target:
  * data_contract            — the contract itself (entity_assignment candidate)
  * data_contract_schema     — each SchemaObjectDb (entity_assignment candidate)
  * data_contract_property   — each SchemaPropertyDb (attribute_assignment candidate)

entity_id encoding follows the existing semantic-links convention:
  data_contract            -> contract_id
  data_contract_schema     -> "{contract_id}#{schema_name}"
  data_contract_property   -> "{contract_id}#{schema_name}#{property_name}"
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb, SchemaPropertyDb
from src.models.term_mappings import RunTargetFilter

from ..types import TargetEntity

logger = get_logger(__name__)


class ContractAdapter:
    entity_types: List[str] = [
        "data_contract",
        "data_contract_schema",
        "data_contract_property",
    ]

    def get_target(self, db: Session, entity_id: str) -> Optional[TargetEntity]:
        # entity_id encoding:
        #   data_contract            -> contract_id
        #   data_contract_schema     -> "{contract_id}#{schema_name}"
        #   data_contract_property   -> "{contract_id}#{schema_name}#{prop_name}"
        parts = entity_id.split("#")
        contract = db.query(DataContractDb).filter(DataContractDb.id == parts[0]).first()
        if not contract:
            return None
        contract_id = str(contract.id)
        if len(parts) == 1:
            return TargetEntity(
                entity_type="data_contract",
                entity_id=contract_id,
                name=contract.name or "",
                label=contract.name or contract_id,
                extras={"version": contract.version, "status": contract.status},
            )
        schema_obj = next(
            (s for s in (contract.schema_objects or []) if s.name == parts[1]), None
        )
        if not schema_obj:
            return None
        schema_id = f"{contract_id}#{schema_obj.name}"
        if len(parts) == 2:
            return TargetEntity(
                entity_type="data_contract_schema",
                entity_id=schema_id,
                name=schema_obj.name,
                label=schema_obj.business_name or schema_obj.name,
                type_label=schema_obj.logical_type or "object",
                parent_entity_type="data_contract",
                parent_entity_id=contract_id,
                parent_name=contract.name,
                extras={
                    "physical_type": schema_obj.physical_type,
                    "description": schema_obj.description,
                },
            )
        prop = next(
            (p for p in (schema_obj.properties or []) if p.name == parts[2] and not p.parent_property_id),
            None,
        )
        if not prop:
            return None
        return TargetEntity(
            entity_type="data_contract_property",
            entity_id=f"{contract_id}#{schema_obj.name}#{prop.name}",
            name=prop.name,
            label=prop.business_name or prop.name,
            type_label=prop.logical_type or prop.physical_type or "",
            parent_entity_type="data_contract_schema",
            parent_entity_id=schema_id,
            parent_name=schema_obj.name,
            is_pk=bool(prop.primary_key),
            extras={
                "classification": prop.classification,
                "required": prop.required,
            },
        )

    def list_targets(self, db: Session, filters: RunTargetFilter) -> Iterable[TargetEntity]:
        wanted_types = set(filters.entity_types or self.entity_types)

        q = db.query(DataContractDb)
        if filters.contract_ids:
            q = q.filter(DataContractDb.id.in_(filters.contract_ids))
        if filters.domain_ids:
            q = q.filter(DataContractDb.domain_id.in_(filters.domain_ids))

        contracts = q.all()
        emitted = 0

        for contract in contracts:
            contract_id = str(contract.id)

            if "data_contract" in wanted_types:
                yield TargetEntity(
                    entity_type="data_contract",
                    entity_id=contract_id,
                    name=contract.name or "",
                    label=contract.name or contract_id,
                    extras={"version": contract.version, "status": contract.status},
                )
                emitted += 1
                if filters.limit and emitted >= filters.limit:
                    return

            for schema_obj in contract.schema_objects or []:
                schema_id = f"{contract_id}#{schema_obj.name}"

                if "data_contract_schema" in wanted_types:
                    yield TargetEntity(
                        entity_type="data_contract_schema",
                        entity_id=schema_id,
                        name=schema_obj.name,
                        label=schema_obj.business_name or schema_obj.name,
                        type_label=schema_obj.logical_type or "object",
                        parent_entity_type="data_contract",
                        parent_entity_id=contract_id,
                        parent_name=contract.name,
                        extras={
                            "physical_type": schema_obj.physical_type,
                            "description": schema_obj.description,
                        },
                    )
                    emitted += 1
                    if filters.limit and emitted >= filters.limit:
                        return

                if "data_contract_property" not in wanted_types:
                    continue

                for prop in schema_obj.properties or []:
                    # Only top-level properties for v1; nested struct fields
                    # could be added later by recursing on parent_property_id.
                    if prop.parent_property_id:
                        continue
                    prop_id = f"{contract_id}#{schema_obj.name}#{prop.name}"
                    yield TargetEntity(
                        entity_type="data_contract_property",
                        entity_id=prop_id,
                        name=prop.name,
                        label=prop.business_name or prop.name,
                        type_label=prop.logical_type or prop.physical_type or "",
                        parent_entity_type="data_contract_schema",
                        parent_entity_id=schema_id,
                        parent_name=schema_obj.name,
                        is_pk=bool(prop.primary_key),
                        # Note: there is no isForeignKey flag on SchemaPropertyDb;
                        # the heuristic engine infers FK from the *_id naming
                        # convention anyway.
                        extras={
                            "classification": prop.classification,
                            "required": prop.required,
                        },
                    )
                    emitted += 1
                    if filters.limit and emitted >= filters.limit:
                        return

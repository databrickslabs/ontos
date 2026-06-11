"""Maturity evaluation engine.

Evaluates an entity against admin-configured maturity levels.
Levels are cumulative: evaluation stops at the first level where a required gate fails.
"""
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.controller.entity_dict_builder import (
    build_data_product_dict,
    build_data_contract_dict,
)
from src.models.maturity import (
    MaturityReport,
    LevelResult,
    GateResult,
)
from src.repositories.maturity_repository import maturity_repo

logger = get_logger(__name__)

_ENTITY_DICT_BUILDERS = {
    "DataProduct": build_data_product_dict,
    "DataContract": build_data_contract_dict,
}


class MaturityEvaluator:
    """Evaluates maturity for Data Products and Data Contracts."""

    def evaluate(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        persist: bool = True,
        evaluated_by: Optional[str] = None,
    ) -> Optional[MaturityReport]:
        """Evaluate maturity for an entity.

        Returns None if the entity is not found.
        """
        builder = _ENTITY_DICT_BUILDERS.get(entity_type)
        if not builder:
            logger.warning(f"No entity dict builder for type: {entity_type}")
            return None

        entity_dict = builder(db, entity_id)
        if entity_dict is None:
            return None

        entity_name = entity_dict.get("name")

        # Load levels applicable to this entity type
        levels = maturity_repo.get_all_ordered(db, entity_type=entity_type)
        if not levels:
            return MaturityReport(
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=entity_name,
                evaluated_at=datetime.now(timezone.utc),
                evaluated_by=evaluated_by,
            )

        level_results = []
        achieved_order = None
        achieved_name = None
        total_gates_passed = 0
        total_gates = 0

        for level in levels:
            gates = level.gates or []
            gate_results = []
            all_required_pass = True

            for gate in gates:
                total_gates += 1
                policy = gate.compliance_policy
                if not policy:
                    gate_results.append(GateResult(
                        gate_id=str(gate.id),
                        policy_id=gate.compliance_policy_id,
                        policy_name="(missing policy)",
                        required=gate.required,
                        passed=False,
                        message="Compliance policy not found",
                    ))
                    if gate.required:
                        all_required_pass = False
                    continue

                passed, message = self._evaluate_gate(policy.rule, entity_dict)
                if passed:
                    total_gates_passed += 1
                elif gate.required:
                    all_required_pass = False

                gate_results.append(GateResult(
                    gate_id=str(gate.id),
                    policy_id=gate.compliance_policy_id,
                    policy_name=policy.name,
                    required=gate.required,
                    passed=passed,
                    message=message if not passed else None,
                ))

            level_results.append(LevelResult(
                level_order=level.level_order,
                level_name=level.name,
                level_icon=level.icon,
                level_color=level.color,
                achieved=all_required_pass,
                gates=gate_results,
            ))

            if all_required_pass:
                achieved_order = level.level_order
                achieved_name = level.name
            else:
                # Cumulative: stop evaluating higher levels
                break

        now = datetime.now(timezone.utc)
        report = MaturityReport(
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            achieved_level_order=achieved_order,
            achieved_level_name=achieved_name,
            total_levels=len(levels),
            gates_passed=total_gates_passed,
            gates_total=total_gates,
            levels=level_results,
            evaluated_at=now,
            evaluated_by=evaluated_by,
        )

        if persist:
            # Detect level change for trigger / change log
            prev_snapshot = maturity_repo.get_latest_snapshot(
                db, entity_type=entity_type, entity_id=entity_id
            )
            prev_level = prev_snapshot.achieved_level_order if prev_snapshot else None

            self._persist(db, report)

            if achieved_order != prev_level:
                self._log_change(
                    db,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    from_level=prev_level,
                    to_level=achieved_order,
                    entity_name=entity_name,
                    evaluated_by=evaluated_by,
                )

        return report

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _evaluate_gate(rule: str, entity_dict: dict) -> tuple[bool, Optional[str]]:
        """Evaluate a compliance DSL rule against an entity dict."""
        try:
            from src.common.compliance_dsl import evaluate_rule_on_object
            return evaluate_rule_on_object(rule, entity_dict)
        except Exception as e:
            logger.error(f"Gate evaluation error: {e}", exc_info=True)
            return False, str(e)

    @staticmethod
    def _persist(db: Session, report: MaturityReport) -> None:
        """Persist a snapshot and update the cached maturity level on the entity."""
        gate_results_data = []
        for lr in report.levels:
            for gr in lr.gates:
                gate_results_data.append({
                    "level_order": lr.level_order,
                    "level_name": lr.level_name,
                    "gate_id": gr.gate_id,
                    "policy_id": gr.policy_id,
                    "policy_name": gr.policy_name,
                    "required": gr.required,
                    "passed": gr.passed,
                    "message": gr.message,
                })

        maturity_repo.create_snapshot(
            db,
            entity_type=report.entity_type,
            entity_id=report.entity_id,
            achieved_level_order=report.achieved_level_order,
            achieved_level_name=report.achieved_level_name,
            total_levels=report.total_levels,
            gates_passed=report.gates_passed,
            gates_total=report.gates_total,
            gate_results_json=json.dumps(gate_results_data),
            evaluated_by=report.evaluated_by,
        )

        # Update cached maturity on entity table
        _update_entity_cache(
            db,
            entity_type=report.entity_type,
            entity_id=report.entity_id,
            level_order=report.achieved_level_order,
        )

        db.commit()


    @staticmethod
    def _log_change(
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        from_level: Optional[int],
        to_level: Optional[int],
        entity_name: Optional[str] = None,
        evaluated_by: Optional[str] = None,
    ) -> None:
        """Log maturity change to change log and fire workflow trigger."""
        try:
            from src.controller.change_log_manager import ChangeLogManager
            cl = ChangeLogManager()
            cl.log_change_with_details(
                db,
                entity_type=entity_type,
                entity_id=entity_id,
                action="MATURITY_CHANGED",
                username=evaluated_by or "system",
                details={
                    "from_maturity_level": from_level,
                    "to_maturity_level": to_level,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to log maturity change: {e}")

        try:
            from src.common.workflow_triggers import TriggerRegistry
            from src.models.process_workflows import EntityType
            et_map = {"DataProduct": EntityType.DATA_PRODUCT, "DataContract": EntityType.DATA_CONTRACT}
            et_enum = et_map.get(entity_type)
            if et_enum:
                registry = TriggerRegistry(db)
                registry.on_maturity_change(
                    entity_type=et_enum,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    from_level=from_level,
                    to_level=to_level,
                    user_email=evaluated_by,
                )
        except Exception as e:
            logger.warning(f"Failed to fire maturity trigger: {e}")


def _update_entity_cache(db: Session, *, entity_type: str, entity_id: str,
                          level_order: Optional[int]) -> None:
    """Update the cached maturity_level_order on the entity table."""
    now = datetime.now(timezone.utc)
    if entity_type == "DataProduct":
        from src.db_models.data_products import DataProductDb
        db.query(DataProductDb).filter(DataProductDb.id == entity_id).update(
            {"maturity_level_order": level_order, "maturity_evaluated_at": now},
            synchronize_session=False,
        )
    elif entity_type == "DataContract":
        from src.db_models.data_contracts import DataContractDb
        db.query(DataContractDb).filter(DataContractDb.id == entity_id).update(
            {"maturity_level_order": level_order, "maturity_evaluated_at": now},
            synchronize_session=False,
        )

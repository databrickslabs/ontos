"""Repository for maturity levels, gates, and snapshots."""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select, and_
from sqlalchemy.orm import Session

from src.db_models.maturity import MaturityLevelDb, MaturityGateDb, MaturitySnapshotDb
from src.common.logging import get_logger

logger = get_logger(__name__)


class MaturityLevelRepository:

    # ------------------------------------------------------------------
    # Levels
    # ------------------------------------------------------------------

    def get_all_ordered(self, db: Session, *, entity_type: Optional[str] = None) -> List[MaturityLevelDb]:
        """Return levels ordered by level_order, optionally filtered by entity_type."""
        q = db.query(MaturityLevelDb)
        if entity_type:
            q = q.filter(
                MaturityLevelDb.entity_type.in_([entity_type, "all"])
            )
        return q.order_by(MaturityLevelDb.level_order).all()

    def get_by_id(self, db: Session, level_id: UUID) -> Optional[MaturityLevelDb]:
        return db.query(MaturityLevelDb).filter(MaturityLevelDb.id == level_id).first()

    def get_by_order(self, db: Session, level_order: int, entity_type: str) -> Optional[MaturityLevelDb]:
        return db.query(MaturityLevelDb).filter(
            and_(
                MaturityLevelDb.level_order == level_order,
                MaturityLevelDb.entity_type == entity_type,
            )
        ).first()

    def create(self, db: Session, *, name: str, level_order: int,
               entity_type: str = "all", description: Optional[str] = None,
               icon: Optional[str] = None, color: Optional[str] = None) -> MaturityLevelDb:
        obj = MaturityLevelDb(
            name=name,
            level_order=level_order,
            entity_type=entity_type,
            description=description,
            icon=icon,
            color=color,
        )
        db.add(obj)
        db.flush()
        db.refresh(obj)
        logger.info(f"Created maturity level '{name}' (order={level_order}, entity_type={entity_type})")
        return obj

    def update(self, db: Session, *, db_obj: MaturityLevelDb, update_data: dict) -> MaturityLevelDb:
        for field, value in update_data.items():
            if hasattr(db_obj, field) and field != "id":
                setattr(db_obj, field, value)
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        logger.info(f"Updated maturity level '{db_obj.name}'")
        return db_obj

    def delete(self, db: Session, *, db_obj: MaturityLevelDb) -> None:
        db.delete(db_obj)
        db.flush()
        logger.info(f"Deleted maturity level '{db_obj.name}' (order={db_obj.level_order})")

    def reorder(self, db: Session, *, order_map: dict[str, int]) -> List[MaturityLevelDb]:
        """Bulk reorder: order_map = {str(uuid): new_order, ...}.
        Two-pass to avoid unique constraint violations.
        """
        all_levels = self.get_all_ordered(db)
        changed = []
        for level in all_levels:
            new_order = order_map.get(str(level.id))
            if new_order is not None and new_order != level.level_order:
                changed.append((level, new_order))

        if not changed:
            return all_levels

        for i, (level, _) in enumerate(changed):
            level.level_order = -(i + 1)
            db.add(level)
        db.flush()

        for level, new_order in changed:
            level.level_order = new_order
            db.add(level)
        db.flush()

        return self.get_all_ordered(db)

    def count_snapshots_for_level(self, db: Session, level_order: int) -> int:
        return db.query(func.count(MaturitySnapshotDb.id)).filter(
            MaturitySnapshotDb.achieved_level_order == level_order
        ).scalar() or 0

    def is_empty(self, db: Session, entity_type: Optional[str] = None) -> bool:
        q = db.query(MaturityLevelDb)
        if entity_type:
            q = q.filter(MaturityLevelDb.entity_type == entity_type)
        return q.count() == 0

    # ------------------------------------------------------------------
    # Gates
    # ------------------------------------------------------------------

    def add_gate(self, db: Session, *, maturity_level_id: UUID,
                 compliance_policy_id: str, required: bool = True,
                 display_order: int = 0) -> MaturityGateDb:
        gate = MaturityGateDb(
            maturity_level_id=maturity_level_id,
            compliance_policy_id=compliance_policy_id,
            required=required,
            display_order=display_order,
        )
        db.add(gate)
        db.flush()
        db.refresh(gate)
        logger.info(f"Added gate: level={maturity_level_id}, policy={compliance_policy_id}")
        return gate

    def get_gate_by_id(self, db: Session, gate_id: UUID) -> Optional[MaturityGateDb]:
        return db.query(MaturityGateDb).filter(MaturityGateDb.id == gate_id).first()

    def remove_gate(self, db: Session, *, db_obj: MaturityGateDb) -> None:
        db.delete(db_obj)
        db.flush()
        logger.info(f"Removed gate {db_obj.id}")

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def create_snapshot(self, db: Session, **kwargs) -> MaturitySnapshotDb:
        snap = MaturitySnapshotDb(**kwargs)
        db.add(snap)
        db.flush()
        db.refresh(snap)
        return snap

    def list_snapshots(self, db: Session, *, entity_type: str,
                       entity_id: str, limit: int = 50) -> List[MaturitySnapshotDb]:
        return (
            db.query(MaturitySnapshotDb)
            .filter(
                and_(
                    MaturitySnapshotDb.entity_type == entity_type,
                    MaturitySnapshotDb.entity_id == entity_id,
                )
            )
            .order_by(MaturitySnapshotDb.evaluated_at.desc())
            .limit(limit)
            .all()
        )

    def get_latest_snapshot(self, db: Session, *, entity_type: str,
                            entity_id: str) -> Optional[MaturitySnapshotDb]:
        return (
            db.query(MaturitySnapshotDb)
            .filter(
                and_(
                    MaturitySnapshotDb.entity_type == entity_type,
                    MaturitySnapshotDb.entity_id == entity_id,
                )
            )
            .order_by(MaturitySnapshotDb.evaluated_at.desc())
            .first()
        )


    def seed_defaults(self, db: Session) -> List[MaturityLevelDb]:
        """Seed default 5-level maturity model with compliance policy gates.

        Only seeds if no maturity levels exist yet. Creates compliance policies
        for each gate and wires them up.
        """
        if not self.is_empty(db):
            return self.get_all_ordered(db)

        from src.db_models.compliance import CompliancePolicyDb
        import uuid as _uuid

        # Define the 5-level model
        LEVELS = [
            {
                "level_order": 1, "name": "Accessible", "entity_type": "all",
                "description": "Data can be found and requested through clear procedures",
                "icon": "lock-keyhole", "color": "blue",
                "gates": [
                    {"name": "Owner is known", "rule": "ASSERT obj.has_owner = True",
                     "severity": "high", "category": "Maturity"},
                    {"name": "Name is defined", "rule": "ASSERT obj.name != ''",
                     "severity": "high", "category": "Maturity"},
                ],
            },
            {
                "level_order": 2, "name": "Described", "entity_type": "all",
                "description": "Purpose and usage are properly documented",
                "icon": "file-text", "color": "cyan",
                "gates": [
                    {"name": "Description present", "rule": "ASSERT obj.has_description = True",
                     "severity": "high", "category": "Maturity"},
                    {"name": "Tags assigned", "rule": "ASSERT obj.tag_count > 0",
                     "severity": "medium", "category": "Maturity", "required": False},
                ],
            },
            {
                "level_order": 3, "name": "Defined", "entity_type": "all",
                "description": "Business definitions and governance roles are established",
                "icon": "book-open", "color": "green",
                "gates": [
                    {"name": "Business terms linked",
                     "rule": "ASSERT obj.business_term_count > 0",
                     "severity": "high", "category": "Maturity"},
                    {"name": "Upstream lineage defined",
                     "rule": "ASSERT obj.has_upstream_lineage = True",
                     "severity": "high", "category": "Maturity"},
                ],
            },
            {
                "level_order": 4, "name": "Monitored", "entity_type": "all",
                "description": "Data quality is actively monitored and issues are followed up",
                "icon": "activity", "color": "amber",
                "gates": [
                    {"name": "Quality checks active",
                     "rule": "ASSERT obj.quality_check_count > 0",
                     "severity": "high", "category": "Maturity"},
                ],
            },
            {
                "level_order": 5, "name": "Trusted", "entity_type": "all",
                "description": "Certified, reusable data product with complete governance",
                "icon": "shield-check", "color": "purple",
                "gates": [
                    {"name": "Entity is certified",
                     "rule": "ASSERT obj.effective_certification >= 1",
                     "severity": "high", "category": "Maturity"},
                    {"name": "Delivery channels defined",
                     "rule": "ASSERT obj.has_delivery_channels = True",
                     "severity": "medium", "category": "Maturity", "required": False},
                    {"name": "Has output contracts",
                     "rule": "ASSERT obj.has_contract = True",
                     "severity": "high", "category": "Maturity"},
                ],
            },
        ]

        created_levels = []
        for level_def in LEVELS:
            gate_defs = level_def.pop("gates")
            level = self.create(db, **level_def)

            for idx, gate_def in enumerate(gate_defs):
                is_required = gate_def.pop("required", True)
                policy = CompliancePolicyDb(
                    id=str(_uuid.uuid4()),
                    slug=f"maturity-{level_def['level_order']}-{gate_def['name'].lower().replace(' ', '-')}",
                    name=f"[Maturity L{level_def['level_order']}] {gate_def['name']}",
                    description=f"Maturity gate for level '{level_def.get('name', level_def['level_order'])}': {gate_def['name']}",
                    failure_message=f"Gate failed: {gate_def['name']}",
                    rule=gate_def["rule"],
                    category=gate_def.get("category", "Maturity"),
                    severity=gate_def.get("severity", "medium"),
                    is_active=True,
                )
                db.add(policy)
                db.flush()

                self.add_gate(
                    db,
                    maturity_level_id=level.id,
                    compliance_policy_id=policy.id,
                    required=is_required,
                    display_order=idx,
                )

            created_levels.append(level)

        logger.info("Seeded default 5-level maturity model with compliance policy gates")
        return created_levels


maturity_repo = MaturityLevelRepository()

"""Database access for Lifecycle Stage Groups, their stages and transitions."""
from typing import Dict, Iterable, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.common.lifecycle_defaults import LIFECYCLE_ENTITY_TYPES, default_group_definition
from src.common.logging import get_logger
from src.db_models.lifecycle_stage_groups import (
    LifecycleStageDb, LifecycleStageGroupDb, LifecycleStageTransitionDb,
)

logger = get_logger(__name__)


def entity_model(entity_type: str):
    """The ORM model that stores entities of ``entity_type``."""
    if entity_type == 'data_product':
        from src.db_models.data_products import DataProductDb
        return DataProductDb
    if entity_type == 'data_contract':
        from src.db_models.data_contracts import DataContractDb
        return DataContractDb
    if entity_type == 'asset':
        from src.db_models.assets import AssetDb
        return AssetDb
    raise ValueError(f"No lifecycle for entity type '{entity_type}'")


class LifecycleStageGroupsRepository:

    def get(self, db: Session, group_id: str) -> Optional[LifecycleStageGroupDb]:
        return db.get(LifecycleStageGroupDb, group_id)

    def list(self, db: Session, entity_type: Optional[str] = None) -> List[LifecycleStageGroupDb]:
        query = db.query(LifecycleStageGroupDb)
        if entity_type:
            query = query.filter(LifecycleStageGroupDb.entity_type == entity_type)
        return query.order_by(
            LifecycleStageGroupDb.entity_type,
            LifecycleStageGroupDb.is_default_for_type.desc(),
            LifecycleStageGroupDb.name,
        ).all()

    def get_default(self, db: Session, entity_type: str) -> Optional[LifecycleStageGroupDb]:
        return (
            db.query(LifecycleStageGroupDb)
            .filter(
                LifecycleStageGroupDb.entity_type == entity_type,
                LifecycleStageGroupDb.is_default_for_type.is_(True),
            )
            .first()
        )

    def get_by_name(
        self, db: Session, entity_type: str, name: str,
    ) -> Optional[LifecycleStageGroupDb]:
        return (
            db.query(LifecycleStageGroupDb)
            .filter(
                LifecycleStageGroupDb.entity_type == entity_type,
                func.lower(LifecycleStageGroupDb.name) == (name or '').strip().lower(),
            )
            .first()
        )

    def replace_stages(
        self, db: Session, group: LifecycleStageGroupDb, stages: Iterable[dict],
        transitions: Iterable[dict],
    ) -> None:
        """Make the group's stages and transitions these (stages matched by key).

        A stage whose key stays keeps its row (and id); the caller checked that
        the removed ones aren't in use.
        """
        stages = list(stages)
        by_key: Dict[str, LifecycleStageDb] = {s.key: s for s in group.stages}
        wanted = {s['key'] for s in stages}
        for transition in list(group.transitions):
            group.transitions.remove(transition)
        db.flush()
        for key, stage in list(by_key.items()):
            if key not in wanted:
                group.stages.remove(stage)
                del by_key[key]
        db.flush()
        for data in stages:
            stage = by_key.get(data['key'])
            if stage is None:
                stage = LifecycleStageDb(key=data['key'])
                group.stages.append(stage)
                by_key[data['key']] = stage
            stage.label = data['label']
            stage.category = data['category']
            stage.color = data.get('color')
            stage.order = data.get('order', 0)
            stage.is_initial = bool(data.get('is_initial'))
        db.flush()
        for data in transitions:
            group.transitions.append(LifecycleStageTransitionDb(
                from_stage_id=by_key[data['from_key']].id,
                to_stage_id=by_key[data['to_key']].id,
            ))
        db.flush()

    def count_entities(self, db: Session, entity_type: str, group_id: str,
                       include_unassigned: bool = False) -> int:
        """Entities of ``entity_type`` in the group (with NULL rows when it is the default)."""
        model = entity_model(entity_type)
        column = model.lifecycle_stage_group_id
        condition = column == group_id
        if include_unassigned:
            condition = condition | column.is_(None)
        return db.query(func.count()).select_from(model).filter(condition).scalar() or 0

    def count_entities_in_stage(self, db: Session, entity_type: str, group_id: str, key: str,
                                include_unassigned: bool = False) -> int:
        model = entity_model(entity_type)
        column = model.lifecycle_stage_group_id
        condition = column == group_id
        if include_unassigned:
            condition = condition | column.is_(None)
        return (
            db.query(func.count()).select_from(model)
            .filter(condition, func.lower(model.status) == key.lower())
            .scalar() or 0
        )

    def assign_unassigned(self, db: Session, entity_type: str, group_id: str) -> int:
        """Store ``group_id`` on the entities that have no group (they use the default)."""
        model = entity_model(entity_type)
        result = db.execute(
            update(model).where(model.lifecycle_stage_group_id.is_(None))
            .values(lifecycle_stage_group_id=group_id)
        )
        return result.rowcount or 0

    def create_from_definition(self, db: Session, definition: dict,
                               user: Optional[str] = None) -> LifecycleStageGroupDb:
        group = LifecycleStageGroupDb(
            id=definition.get('id') or None,
            name=definition['name'],
            description=definition.get('description'),
            entity_type=definition['entity_type'],
            is_default_for_type=bool(definition.get('is_default_for_type')),
            created_by=user, updated_by=user,
        )
        db.add(group)
        db.flush()
        self.replace_stages(db, group, definition['stages'], definition['transitions'])
        return group

    def seed_defaults(self, db: Session) -> int:
        """Create the seeded default group of every entity type that has no group yet."""
        created = 0
        for entity_type in LIFECYCLE_ENTITY_TYPES:
            has_group = db.execute(
                select(LifecycleStageGroupDb.id)
                .where(LifecycleStageGroupDb.entity_type == entity_type).limit(1)
            ).first()
            if has_group:
                continue
            self.create_from_definition(db, default_group_definition(entity_type), 'system')
            created += 1
        if created:
            logger.info("Seeded %d default lifecycle stage group(s)", created)
        return created


lifecycle_stage_groups_repo = LifecycleStageGroupsRepository()

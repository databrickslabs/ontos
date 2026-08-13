"""Repository for Compliance Templates: definitions, fields, and per-entity values."""
from uuid import UUID

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.compliance_templates import (
    DEFAULT_SCOPE_ID,
    DEFAULT_SCOPE_TYPE,
    ComplianceTemplateDb,
    ComplianceTemplateFieldDb,
    ComplianceTemplateValueDb,
)

logger = get_logger(__name__)


class ComplianceTemplatesRepository:

    # ----- Templates ------------------------------------------------------

    def list_templates(self, db: Session, *, entity_type: str | None = None) -> list[ComplianceTemplateDb]:
        q = db.query(ComplianceTemplateDb)
        if entity_type:
            q = q.filter(ComplianceTemplateDb.entity_type == entity_type)
        return q.order_by(ComplianceTemplateDb.created_at).all()

    def get_template(self, db: Session, template_id: UUID) -> ComplianceTemplateDb | None:
        return db.query(ComplianceTemplateDb).filter(ComplianceTemplateDb.id == template_id).first()

    def get_active_template(
        self,
        db: Session,
        *,
        entity_type: str,
        scope_type: str = DEFAULT_SCOPE_TYPE,
        scope_id: str = DEFAULT_SCOPE_ID,
    ) -> ComplianceTemplateDb | None:
        return (
            db.query(ComplianceTemplateDb)
            .filter(
                ComplianceTemplateDb.entity_type == entity_type,
                ComplianceTemplateDb.scope_type == scope_type,
                ComplianceTemplateDb.scope_id == scope_id,
                ComplianceTemplateDb.is_active.is_(True),
            )
            .first()
        )

    def create_template(
        self,
        db: Session,
        *,
        name: str,
        entity_type: str,
        description: str | None = None,
        created_by: str | None = None,
    ) -> ComplianceTemplateDb:
        obj = ComplianceTemplateDb(
            name=name,
            entity_type=entity_type,
            description=description,
            scope_type=DEFAULT_SCOPE_TYPE,
            scope_id=DEFAULT_SCOPE_ID,
            is_active=False,
            created_by=created_by,
        )
        db.add(obj)
        db.flush()
        db.refresh(obj)
        logger.info(f"Created compliance template '{name}' for entity_type '{entity_type}'")
        return obj

    def update_template(self, db: Session, *, db_obj: ComplianceTemplateDb, update_data: dict) -> ComplianceTemplateDb:
        for field, value in update_data.items():
            if hasattr(db_obj, field) and field not in ("id", "is_active", "entity_type"):
                setattr(db_obj, field, value)
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        return db_obj

    def delete_template(self, db: Session, *, db_obj: ComplianceTemplateDb) -> None:
        db.delete(db_obj)
        db.flush()
        logger.info(f"Deleted compliance template '{db_obj.name}'")

    def activate_template(self, db: Session, *, db_obj: ComplianceTemplateDb) -> ComplianceTemplateDb:
        """Activate a template, deactivating any currently-active one for the same scope.

        Deactivation happens first (and is flushed) so the partial unique index
        on (entity_type, scope_type, scope_id) is never violated.
        """
        current = self.get_active_template(
            db,
            entity_type=db_obj.entity_type,
            scope_type=db_obj.scope_type,
            scope_id=db_obj.scope_id,
        )
        if current and current.id != db_obj.id:
            current.is_active = False
            db.add(current)
            db.flush()
        db_obj.is_active = True
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        logger.info(f"Activated compliance template '{db_obj.name}' ({db_obj.entity_type})")
        return db_obj

    def deactivate_template(self, db: Session, *, db_obj: ComplianceTemplateDb) -> ComplianceTemplateDb:
        db_obj.is_active = False
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        return db_obj

    # ----- Fields ---------------------------------------------------------

    def add_field(self, db: Session, *, template_id: UUID, **field_data) -> ComplianceTemplateFieldDb:
        obj = ComplianceTemplateFieldDb(template_id=template_id, **field_data)
        db.add(obj)
        db.flush()
        db.refresh(obj)
        return obj

    def get_field(self, db: Session, field_id: UUID) -> ComplianceTemplateFieldDb | None:
        return db.query(ComplianceTemplateFieldDb).filter(ComplianceTemplateFieldDb.id == field_id).first()

    def list_fields(self, db: Session, *, template_id: UUID) -> list[ComplianceTemplateFieldDb]:
        return (
            db.query(ComplianceTemplateFieldDb)
            .filter(ComplianceTemplateFieldDb.template_id == template_id)
            .order_by(ComplianceTemplateFieldDb.group_order, ComplianceTemplateFieldDb.field_order)
            .all()
        )

    def update_field(self, db: Session, *, field_id: UUID, update_data: dict) -> ComplianceTemplateFieldDb | None:
        """Update a field's safe attributes (label, hint_text, default_value, is_mandatory, group metadata).

        Does NOT support value_type or possible_values changes — those are destructive
        edits guarded by the manager.
        """
        field = self.get_field(db, field_id)
        if not field:
            return None
        # Whitelist safe fields: label, hint_text, default_value, is_mandatory, group_title, group_order, field_order
        safe_fields = {"label", "hint_text", "default_value", "is_mandatory", "group_title", "group_order", "field_order"}
        for key, value in update_data.items():
            if key in safe_fields and hasattr(field, key):
                setattr(field, key, value)
        db.add(field)
        db.flush()
        db.refresh(field)
        return field

    def delete_field(self, db: Session, *, field_id: UUID) -> None:
        """Delete a field and its values."""
        field = self.get_field(db, field_id)
        if field:
            db.delete(field)
            db.flush()
            logger.info(f"Deleted compliance field '{field.label}' (id={field_id})")

    def count_field_values(self, db: Session, *, field_id: UUID) -> int:
        """Count how many entities have stored values for this field."""
        return db.query(ComplianceTemplateValueDb).filter(ComplianceTemplateValueDb.field_id == field_id).count()

    def reorder_fields(self, db: Session, *, template_id: UUID, order_map: list[dict]) -> list[ComplianceTemplateFieldDb]:
        """Bulk reorder fields and groups: order_map = [{id, group_title, group_order, field_order}, ...].

        Uses two-pass approach to avoid unique constraint violations on field_order:
        first sets all changing rows to negative temp values, then to final values.
        """
        fields = self.list_fields(db, template_id=template_id)
        field_by_id = {f.id: f for f in fields}
        changed = []

        for item in order_map:
            field_id = item["id"]
            field = field_by_id.get(field_id)
            if not field:
                continue
            # Check if any field is actually changing
            new_group_title = item.get("group_title", field.group_title)
            new_group_order = item.get("group_order", field.group_order)
            new_field_order = item.get("field_order", field.field_order)
            if (
                new_group_title != field.group_title
                or new_group_order != field.group_order
                or new_field_order != field.field_order
            ):
                changed.append((field, item))

        if not changed:
            return fields

        # Pass 1: set to temp negative values
        for i, (field, _) in enumerate(changed):
            field.field_order = -(i + 1)
            db.add(field)
        db.flush()

        # Pass 2: set to final values
        for field, item in changed:
            field.group_title = item.get("group_title", field.group_title)
            field.group_order = item.get("group_order", field.group_order)
            field.field_order = item.get("field_order", field.field_order)
            db.add(field)
        db.flush()

        return self.list_fields(db, template_id=template_id)

    # ----- Values (polymorphic, per-entity) -------------------------------

    def list_values(self, db: Session, *, entity_type: str, entity_id: str, field_ids: list[UUID]) -> list[ComplianceTemplateValueDb]:
        if not field_ids:
            return []
        return (
            db.query(ComplianceTemplateValueDb)
            .filter(
                ComplianceTemplateValueDb.entity_type == entity_type,
                ComplianceTemplateValueDb.entity_id == entity_id,
                ComplianceTemplateValueDb.field_id.in_(field_ids),
            )
            .all()
        )

    def replace_values(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        valid_field_ids: set[UUID],
        values_by_field: dict[UUID, object],
        filled_by: str | None,
    ) -> list[ComplianceTemplateValueDb]:
        """Replace-all write: upsert the given field values, delete omitted ones.

        Only fields in ``valid_field_ids`` (the active template's fields) are
        written; unknown field ids in the payload are ignored. This is the
        materialization event. Mirrors ``set_tags_for_entity``.
        """
        current = (
            db.query(ComplianceTemplateValueDb)
            .filter(
                ComplianceTemplateValueDb.entity_type == entity_type,
                ComplianceTemplateValueDb.entity_id == entity_id,
                ComplianceTemplateValueDb.field_id.in_(valid_field_ids),
            )
            .all()
        )
        current_by_field = {v.field_id: v for v in current}
        written_field_ids: set[UUID] = set()

        for field_id, value in values_by_field.items():
            if field_id not in valid_field_ids:
                continue
            written_field_ids.add(field_id)
            existing = current_by_field.get(field_id)
            if existing:
                existing.value = value
                existing.filled_by = filled_by
                db.add(existing)
            else:
                db.add(
                    ComplianceTemplateValueDb(
                        field_id=field_id,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        value=value,
                        filled_by=filled_by,
                    )
                )

        # Remove rows for template fields omitted from the replace-all payload.
        for field_id, existing in current_by_field.items():
            if field_id not in written_field_ids:
                db.delete(existing)

        db.flush()
        return self.list_values(db, entity_type=entity_type, entity_id=entity_id, field_ids=list(valid_field_ids))


compliance_templates_repo = ComplianceTemplatesRepository()

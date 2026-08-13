"""Manager for Compliance Templates: validation + composed reads over the repository."""
import re
from uuid import UUID

from sqlalchemy.orm import Session

from src.common.compliance_completeness import CompletenessResult, FieldSpec, check_completeness
from src.common.compliance_value_types import ValueTypeError, coerce_value
from src.common.logging import get_logger
from src.models.compliance_templates import (
    ComplianceFieldCreate,
    ComplianceFieldRead,
    ComplianceTemplateCreate,
    ComplianceTemplateRead,
    ComplianceValueRead,
    ComplianceValueWrite,
    EntityComplianceRead,
)
from src.repositories.compliance_templates_repository import compliance_templates_repo

logger = get_logger(__name__)

# Reference ids are validated slugs: lowercase alphanumerics and separators.
_REFERENCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ComplianceTemplateError(ValueError):
    """Raised for validation failures; routes convert to HTTP 4xx."""


def _validate_reference_id(reference_id: str) -> None:
    if not _REFERENCE_ID_RE.match(reference_id):
        raise ComplianceTemplateError(
            f"Invalid reference id '{reference_id}': must be a slug "
            "(lowercase letters, digits, '-' or '_', starting alphanumeric)."
        )


def _assert_unique_reference_ids(fields: list[ComplianceFieldCreate]) -> None:
    seen_refs, seen_keys = set(), set()
    for f in fields:
        _validate_reference_id(f.reference_id)
        if f.reference_id in seen_refs:
            raise ComplianceTemplateError(f"Duplicate reference id '{f.reference_id}' within template.")
        if f.key in seen_keys:
            raise ComplianceTemplateError(f"Duplicate field key '{f.key}' within template.")
        seen_refs.add(f.reference_id)
        seen_keys.add(f.key)


class ComplianceTemplatesManager:

    # ----- Template CRUD --------------------------------------------------

    def list_templates(self, db: Session, *, entity_type: str | None = None) -> list[ComplianceTemplateRead]:
        return [ComplianceTemplateRead.model_validate(t) for t in compliance_templates_repo.list_templates(db, entity_type=entity_type)]

    def get_template(self, db: Session, template_id: UUID) -> ComplianceTemplateRead | None:
        t = compliance_templates_repo.get_template(db, template_id)
        return ComplianceTemplateRead.model_validate(t) if t else None

    def create_template(self, db: Session, *, payload: ComplianceTemplateCreate, user_email: str | None) -> ComplianceTemplateRead:
        _assert_unique_reference_ids(payload.fields)
        template = compliance_templates_repo.create_template(
            db,
            name=payload.name,
            entity_type=payload.entity_type,
            description=payload.description,
            created_by=user_email,
        )
        for f in payload.fields:
            # Coerce the default against the field's type + vocabulary so it is
            # stored in canonical form and can never be an invalid value.
            try:
                default_value = coerce_value(f.value_type, f.default_value, f.possible_values)
            except ValueTypeError as e:
                db.rollback()
                raise ComplianceTemplateError(f"{f.label} default: {e}")
            compliance_templates_repo.add_field(
                db,
                template_id=template.id,
                group_title=f.group_title,
                group_order=f.group_order,
                key=f.key,
                label=f.label,
                reference_id=f.reference_id,
                value_type=f.value_type.value,
                possible_values=f.possible_values,
                default_value=default_value,
                hint_text=f.hint_text,
                is_mandatory=f.is_mandatory,
                field_order=f.field_order,
            )
        db.commit()
        db.refresh(template)
        return ComplianceTemplateRead.model_validate(template)

    def update_template(self, db: Session, *, template_id: UUID, update_data: dict) -> ComplianceTemplateRead:
        t = compliance_templates_repo.get_template(db, template_id)
        if not t:
            raise ComplianceTemplateError("Template not found")
        compliance_templates_repo.update_template(db, db_obj=t, update_data=update_data)
        db.commit()
        db.refresh(t)
        return ComplianceTemplateRead.model_validate(t)

    def delete_template(self, db: Session, *, template_id: UUID) -> None:
        t = compliance_templates_repo.get_template(db, template_id)
        if not t:
            raise ComplianceTemplateError("Template not found")
        compliance_templates_repo.delete_template(db, db_obj=t)
        db.commit()

    def set_active(self, db: Session, *, template_id: UUID, active: bool) -> ComplianceTemplateRead:
        t = compliance_templates_repo.get_template(db, template_id)
        if not t:
            raise ComplianceTemplateError("Template not found")
        if active:
            compliance_templates_repo.activate_template(db, db_obj=t)
        else:
            compliance_templates_repo.deactivate_template(db, db_obj=t)
        db.commit()
        db.refresh(t)
        return ComplianceTemplateRead.model_validate(t)

    # ----- Composed read + replace-all write ------------------------------

    def read_for_entity(self, db: Session, *, entity_type: str, entity_id: str) -> EntityComplianceRead:
        """Return { template, fields, values } for the active template of an entity type.

        Values are read for the union of the active template's fields AND any
        fields that already have stored values for this entity — so historical
        values remain visible even after their template is deactivated.
        """
        active = compliance_templates_repo.get_active_template(db, entity_type=entity_type)
        if not active:
            return EntityComplianceRead(template=None, fields=[], values=[])

        fields = compliance_templates_repo.list_fields(db, template_id=active.id)
        field_ids = [f.id for f in fields]
        ref_by_field = {f.id: f.reference_id for f in fields}
        value_rows = compliance_templates_repo.list_values(
            db, entity_type=entity_type, entity_id=entity_id, field_ids=field_ids
        )
        values = [
            ComplianceValueRead(
                field_id=v.field_id,
                reference_id=ref_by_field.get(v.field_id, ""),
                entity_type=v.entity_type,
                entity_id=v.entity_id,
                value=v.value,
                filled_by=v.filled_by,
                filled_at=v.filled_at,
            )
            for v in value_rows
        ]
        return EntityComplianceRead(
            template=ComplianceTemplateRead.model_validate(active),
            fields=[ComplianceFieldRead.model_validate(f) for f in fields],
            values=values,
        )

    def replace_values(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        writes: list[ComplianceValueWrite],
        user_email: str | None,
    ) -> EntityComplianceRead:
        """Replace-all write of an entity's values against the active template."""
        active = compliance_templates_repo.get_active_template(db, entity_type=entity_type)
        if not active:
            raise ComplianceTemplateError(f"No active compliance template for entity type '{entity_type}'.")
        fields = compliance_templates_repo.list_fields(db, template_id=active.id)
        valid_field_ids = {f.id for f in fields}
        fields_by_id = {f.id: f for f in fields}

        # Validate/coerce each written value against its field's type + vocabulary.
        values_by_field: dict = {}
        for w in writes:
            field = fields_by_id.get(w.field_id)
            if field is None:
                # Unknown field ids are ignored by the repository's replace-all.
                continue
            try:
                values_by_field[w.field_id] = coerce_value(
                    field.value_type, w.value, field.possible_values
                )
            except ValueTypeError as e:
                raise ComplianceTemplateError(f"{field.label}: {e}")
        compliance_templates_repo.replace_values(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            valid_field_ids=valid_field_ids,
            values_by_field=values_by_field,
            filled_by=user_email,
        )
        db.commit()
        return self.read_for_entity(db, entity_type=entity_type, entity_id=entity_id)

    # ----- Completeness ---------------------------------------------------

    def check_completeness(self, db: Session, *, entity_type: str, entity_id: str) -> CompletenessResult:
        """Run the completeness check for an entity against its active template.

        Returns a result with ``applicable=False`` semantics handled by the
        caller: when no template is active, this returns a passing result over
        zero fields (nothing to complete).
        """
        active = compliance_templates_repo.get_active_template(db, entity_type=entity_type)
        if not active:
            return CompletenessResult(passed=True)
        fields = compliance_templates_repo.list_fields(db, template_id=active.id)
        field_ids = [f.id for f in fields]
        value_rows = compliance_templates_repo.list_values(
            db, entity_type=entity_type, entity_id=entity_id, field_ids=field_ids
        )
        stored = {v.field_id: v.value for v in value_rows}
        specs = [
            FieldSpec(
                field_id=f.id,
                label=f.label,
                value_type=f.value_type,
                is_mandatory=f.is_mandatory,
                default_value=f.default_value,
            )
            for f in fields
        ]
        return check_completeness(specs, stored)

    def has_active_template(self, db: Session, *, entity_type: str) -> bool:
        return compliance_templates_repo.get_active_template(db, entity_type=entity_type) is not None


compliance_templates_manager = ComplianceTemplatesManager()

"""File model for Access Policy releases (Indirect delivery writes Ontos YAML)."""

from typing import Any, Dict

from src.db_models.access_policies import AccessPolicyReleaseDb

from .base import FileModel, register_file_model


@register_file_model
class AccessPolicyReleaseFileModel(FileModel[AccessPolicyReleaseDb]):
    """One YAML file per release: the full desired state, the diff and a SQL runbook.

    External CI applies ``spec.changes`` (or reconciles to ``spec.grants``) and an
    admin then marks the release as applied in Ontos, which updates the Grant Ledger.
    """

    ENTITY_TYPE = "AccessPolicyRelease"
    SUBDIRECTORY = "access-policies/releases"
    ONE_FILE_PER_RECORD = True

    # ``entity`` is the release row or the delivery snapshot (same attributes, ``changes`` = what ships).
    @classmethod
    def get_filename(cls, entity: AccessPolicyReleaseDb) -> str:
        return f"{entity.target}-release-{entity.sequence:05d}.yaml"

    @classmethod
    def _get_metadata(cls, entity: AccessPolicyReleaseDb) -> Dict[str, Any]:
        metadata = super()._get_metadata(entity)
        metadata['name'] = f"{entity.target}-release-{entity.sequence}"
        return metadata

    @classmethod
    def to_yaml_dict(cls, entity: AccessPolicyReleaseDb) -> Dict[str, Any]:
        changes = entity.changes or {}
        result: Dict[str, Any] = {
            'target': entity.target,
            'sequence': entity.sequence,
            'releaseKind': entity.release_kind,
            'approvedBy': entity.approved_by,
            'sourcePolicies': entity.source_policies or [],
            'changes': {
                'grant': changes.get('add') or [],
                'revoke': changes.get('remove') or [],
                'updateExpiry': changes.get('update') or [],
                # Pre-existing platform grants Ontos stops tracking; never revoke these.
                'untrack': changes.get('untrack') or [],
            },
            'sql': changes.get('sql') or [],
            'grants': (entity.plan or {}).get('grants') or [],
        }
        if entity.notes:
            result['notes'] = entity.notes
        return result

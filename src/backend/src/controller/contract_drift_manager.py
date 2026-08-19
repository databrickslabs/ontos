"""Contract drift detection and adoption.

Detects when an external catalog's schema has drifted from the data contract
that governs it, surfaces the diff through an Asset Review, and adopts an
approved change as either a new contract version (semver-bumped) or an in-place
update.

Deterministic only: the diff and the suggested semver bump come from
``ContractChangeAnalyzer`` (via ``DataContractsManager.compare_contracts``); no
LLM is involved. The in-place-vs-new-version choice is driven by the diff
severity — a breaking change forces a new version.

See docs/plans/nebw-contract-drift.md.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.db_models.data_contracts import DataContractDb
from src.db_models.entity_relationships import EntityRelationshipDb
from src.repositories.data_contracts_repository import data_contract_repo
from src.common.errors import ConflictError, NotFoundError
from src.common.logging import get_logger

logger = get_logger(__name__)

# Relationship types that link an Asset to the Contract it implements.
_CONTRACT_ASSET_REL_TYPES = ("implementsContract", "governedBy")


class DriftAdoptionMode:
    NEW_VERSION = "new_version"
    IN_PLACE = "in_place"


class ContractDriftManager:
    """Detects contract/catalog schema drift and adopts approved changes."""

    def __init__(self, contracts_manager, connections_manager=None, asset_reviews_manager=None):
        self._contracts = contracts_manager
        self._connections = connections_manager
        self._reviews = asset_reviews_manager

    # ------------------------------------------------------------------
    # Drift detection
    # ------------------------------------------------------------------

    def analyze_contract_drift(
        self,
        db: Session,
        contract_id: str,
        schema_info: Any,
    ) -> Dict[str, Any]:
        """Compare a contract against a live asset ``SchemaInfo``.

        Returns the compare_contracts result dict (version_bump, breaking/feature/
        fix lists, schema_changes, summary). ``version_bump == "none"`` means no
        drift.
        """
        contract = data_contract_repo.get_with_all(db, id=contract_id)
        if not contract:
            raise NotFoundError(f"Contract not found: {contract_id}")

        current = self._contracts.build_odcs_from_db(contract, db)
        candidate = self._contracts.build_candidate_odcs_from_schema_info(contract, schema_info, db)
        return self._contracts.compare_contracts(current, candidate)

    def find_linked_asset_fqn(self, db: Session, contract_id: str) -> Optional[str]:
        """Return the FQN of an Asset that implements/ is governed by the contract."""
        rel = (
            db.query(EntityRelationshipDb)
            .filter(
                EntityRelationshipDb.target_id == contract_id,
                EntityRelationshipDb.target_type == "data_contract",
                EntityRelationshipDb.relationship_type.in_(_CONTRACT_ASSET_REL_TYPES),
            )
            .first()
        )
        if not rel:
            return None
        # The source of the relationship is the asset; its FQN is stored on the
        # asset record's location/name. Resolve lazily to avoid a hard import cycle.
        from src.repositories.assets_repository import asset_repo

        asset = asset_repo.get(db, rel.source_id)
        if not asset:
            return None
        return asset.location or asset.name

    # ------------------------------------------------------------------
    # Adoption
    # ------------------------------------------------------------------

    def _resolve_bump(self, analysis: Dict[str, Any], bump_override: Optional[str]) -> str:
        """Resolve the effective semver bump, honoring a valid override.

        The override may not *lower* severity below what the diff requires: if the
        diff is breaking (major), the bump stays major regardless of override.
        """
        suggested = analysis.get("version_bump") or "patch"
        if suggested == "none":
            suggested = "patch"
        if not bump_override:
            return suggested
        if bump_override not in ("major", "minor", "patch"):
            raise ConflictError(f"Invalid version bump: {bump_override}")
        rank = {"patch": 0, "minor": 1, "major": 2}
        # Never adopt below the severity the diff requires.
        if rank[bump_override] < rank[suggested]:
            raise ConflictError(
                f"Requested bump '{bump_override}' is weaker than the required '{suggested}'"
            )
        return bump_override

    def adopt_drift(
        self,
        db: Session,
        contract_id: str,
        schema_info: Any,
        mode: str,
        bump_override: Optional[str] = None,
        current_user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Adopt drifted schema into the contract.

        - ``new_version``: clone the contract to a bumped version, then apply the
          drifted schema to the clone (status draft).
        - ``in_place``: replace the existing contract's schema and bump its version.
          Rejected when the diff is breaking (major) — breaking changes must go to
          a new version so existing consumers are not silently broken.
        """
        contract = data_contract_repo.get_with_all(db, id=contract_id)
        if not contract:
            raise NotFoundError(f"Contract not found: {contract_id}")

        analysis = self.analyze_contract_drift(db, contract_id, schema_info)
        if analysis.get("version_bump", "none") == "none":
            raise ConflictError("No drift detected; nothing to adopt.")

        is_breaking = analysis.get("change_type") == "breaking" or analysis.get("version_bump") == "major"
        if mode == DriftAdoptionMode.IN_PLACE and is_breaking:
            raise ConflictError(
                "Breaking changes cannot be adopted in place; create a new version."
            )

        bump = self._resolve_bump(analysis, bump_override)
        candidate_odcs = self._contracts.build_candidate_odcs_from_schema_info(contract, schema_info, db)
        summary = analysis.get("summary") or "Adopted schema drift from source catalog"

        if mode == DriftAdoptionMode.NEW_VERSION:
            new_version = self._contracts._calculate_next_version(contract.version, bump)
            # Deep-clone to the bumped version (copies the old schema + lineage),
            # then overwrite the clone's schema with the drifted one.
            new_contract = self._contracts.clone_contract_for_new_version(
                db,
                contract_id=contract_id,
                new_version=new_version,
                change_summary=summary,
                current_user=current_user,
            )
            self._contracts.replace_contract_schema(
                db,
                contract_id=new_contract.id,
                schema_data=candidate_odcs.get("schema", []),
                change_summary=summary,
                current_user=current_user,
            )
            return {
                "mode": mode,
                "version_bump": bump,
                "new_version": new_version,
                "contract_id": new_contract.id,
                "analysis": analysis,
            }

        if mode == DriftAdoptionMode.IN_PLACE:
            new_version = self._contracts._calculate_next_version(contract.version, bump)
            self._contracts.replace_contract_schema(
                db,
                contract_id=contract_id,
                schema_data=candidate_odcs.get("schema", []),
                new_version=new_version,
                change_summary=summary,
                current_user=current_user,
            )
            return {
                "mode": mode,
                "version_bump": bump,
                "new_version": new_version,
                "contract_id": contract_id,
                "analysis": analysis,
            }

        raise ConflictError(f"Unknown adoption mode: {mode}")

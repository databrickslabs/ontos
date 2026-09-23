"""Authority Resolution manager (ARF).

Owns the Authority Relation lifecycle, evidence-bound DNA-Coefficient
computation, the N-functional affirmation gate, and the deterministic runtime
resolution used by both the MCP tool and Ontos-native flows.

Design notes:
* The manager is a stateless singleton (mirrors ``ComplianceManager``); the DB
  session is passed per call.
* The DNAco scoring itself is a pure function in ``src.common.authority_resolution_dna`` so
  it is unit-testable without a DB or a warehouse. Evidence reading is
  best-effort and isolated in ``_read_evidence_rows``.
* Runtime resolution is deterministic — it evaluates request parameters against
  the AR's compiled ``decision_logic`` and never (re)computes the DNAco. The
  DNAco is an *activation-time* gate only.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common import authority_resolution_dna as authority_dna
from src.common.authority_resolution_dna import ARSpec, DIR_NONE
from src.db_models.authority_resolution import (
    AuthorityRelationDb,
    AuthorityAffirmationDb,
    AuthorityDecisionDb,
    AuthorityDnaRunDb,
)
from src.repositories.authority_resolution_repository import (
    authority_relation_repo,
    authority_affirmation_repo,
    authority_dna_run_repo,
    authority_decision_repo,
)
from src.repositories.entity_domain_association_repository import entity_domain_repo

logger = get_logger(__name__)

ENTITY_TYPE = "authority_relation"

# Verdicts returned by the runtime gate.
VERDICT_APPROVED = "approved"
VERDICT_DENIED = "denied"
VERDICT_NO_AUTHORITY = "no_authority"
VERDICT_CONFLICT = "conflict"

# AR lifecycle statuses.
STATUS_DRAFT = "draft"
STATUS_ACTIVE = "active"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_RETIRED = "retired"

# Controlled vocabulary for the Action element (ARF §3.2 business domain).
ACTION_VOCAB = {"approve", "escalate", "override", "delegate", "veto"}

_MODEL_COLUMNS = {c.name for c in AuthorityRelationDb.__table__.columns}


class AuthorityResolutionManager:
    # --------------------------------------------------------------- helpers

    @staticmethod
    def _now() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _compile_decision_logic(fields: Dict[str, Any]) -> Dict[str, Any]:
        """Compile the deterministic runtime rule from the AR's fields.

        Author-provided ``decision_logic`` wins; otherwise a sensible default is
        derived (allowed signer = the documented actor identity, plus the
        Domain-Context threshold and the action)."""
        provided = fields.get("decision_logic") or {}
        domain_context = fields.get("domain_context") or {}
        threshold = authority_dna._to_float(domain_context.get("threshold"))
        compiled = {
            "allowed_principals": provided.get(
                "allowed_principals",
                [fields["actor_identity"]] if fields.get("actor_identity") else [],
            ),
            "threshold": provided.get("threshold", threshold),
            "required_cosign": bool(provided.get("required_cosign", False)),
            "action": provided.get("action", fields.get("action")),
        }
        return compiled

    def _ar_spec(self, relation: AuthorityRelationDb) -> ARSpec:
        dl = relation.decision_logic or {}
        domain_context = relation.domain_context or {}
        threshold = authority_dna._to_float(dl.get("threshold", domain_context.get("threshold")))
        return ARSpec(
            documented_approver=relation.actor_identity,
            threshold=threshold,
            action=relation.action,
            required_cosign=bool(dl.get("required_cosign", False)),
        )

    # ------------------------------------------------------------------ CRUD

    def create_relation(self, db: Session, payload, current_user: Optional[str] = None) -> AuthorityRelationDb:
        data = payload.dict() if hasattr(payload, "dict") else dict(payload)
        rel_id = str(uuid.uuid4())

        evidence = data.get("evidence_binding")
        if evidence is not None and hasattr(evidence, "dict"):
            evidence = evidence.dict()

        fields = {
            "id": rel_id,
            "slug": data.get("slug"),
            "name": data["name"],
            "description": data.get("description"),
            "status": STATUS_DRAFT,
            "version": 1,
            "version_family_id": rel_id,
            "actor_role": data.get("actor_role"),
            "actor_identity": data.get("actor_identity"),
            "actor_since": data.get("actor_since"),
            "action": data.get("action"),
            "object_type": data.get("object_type"),
            "object_id": data.get("object_id"),
            "object_resolves_to": data.get("object_resolves_to"),
            "domain_context": data.get("domain_context"),
            "justification_chain": data.get("justification_chain"),
            "evidence_binding": evidence,
            "dna_max_threshold": data.get("dna_max_threshold", 0.3),
            "dna_scoring_config": data.get("dna_scoring_config"),
            "schedule_cron": data.get("schedule_cron"),
            "created_by": current_user,
        }
        fields["decision_logic"] = self._compile_decision_logic(
            {**fields, "decision_logic": data.get("decision_logic")}
        )

        relation = authority_relation_repo.create(db, obj_in={k: v for k, v in fields.items() if k in _MODEL_COLUMNS})

        # Domains (multi-domain, mirrors contracts/products/teams).
        domain_ids = data.get("domain_ids") or []
        if domain_ids:
            entity_domain_repo.set_domains_for_entity(
                db, entity_type=ENTITY_TYPE, entity_id=rel_id,
                domain_ids=domain_ids, primary_domain_id=data.get("primary_domain_id"),
                assigned_by=current_user,
            )

        # N-functional affirmation stakeholders.
        self._replace_affirmations(db, rel_id, data.get("affirmations") or [])
        return relation

    def get_relation(self, db: Session, relation_id: str) -> Optional[AuthorityRelationDb]:
        return authority_relation_repo.get(db, relation_id)

    def get_relation_by_slug(self, db: Session, slug: str) -> Optional[AuthorityRelationDb]:
        return authority_relation_repo.get_by_slug(db, slug)

    def list_relations(self, db: Session, domain_ids: Optional[List[str]] = None) -> List[AuthorityRelationDb]:
        if domain_ids:
            ids = entity_domain_repo.find_entity_ids_by_domains(
                db, domain_ids=domain_ids, entity_type=ENTITY_TYPE
            )
            return authority_relation_repo.list_by_ids(db, ids)
        return authority_relation_repo.list_all(db)

    def update_relation(self, db: Session, relation_id: str, payload, current_user: Optional[str] = None) -> Optional[AuthorityRelationDb]:
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None
        data = payload.dict(exclude_unset=True) if hasattr(payload, "dict") else dict(payload)

        domain_ids = data.pop("domain_ids", None)
        primary_domain_id = data.pop("primary_domain_id", None)
        affirmations = data.pop("affirmations", None)

        evidence = data.get("evidence_binding")
        if evidence is not None and hasattr(evidence, "dict"):
            data["evidence_binding"] = evidence.dict()

        update_data = {k: v for k, v in data.items() if k in _MODEL_COLUMNS}
        # Recompile decision_logic when any input to it changed.
        if any(k in data for k in ("decision_logic", "domain_context", "actor_identity", "action")):
            merged = {
                "actor_identity": data.get("actor_identity", relation.actor_identity),
                "action": data.get("action", relation.action),
                "domain_context": data.get("domain_context", relation.domain_context),
                "decision_logic": data.get("decision_logic", relation.decision_logic),
            }
            update_data["decision_logic"] = self._compile_decision_logic(merged)

        # A material change bumps the version and re-opens the review gate.
        update_data["version"] = (relation.version or 1) + 1
        relation = authority_relation_repo.update(db, db_obj=relation, obj_in=update_data)

        if domain_ids is not None:
            entity_domain_repo.set_domains_for_entity(
                db, entity_type=ENTITY_TYPE, entity_id=relation_id,
                domain_ids=domain_ids, primary_domain_id=primary_domain_id,
                assigned_by=current_user,
            )
        if affirmations is not None:
            self._replace_affirmations(db, relation_id, affirmations)

        # Changing an active AR triggers recompute + re-review (best-effort recompute).
        if relation.status == STATUS_ACTIVE:
            try:
                self.compute_dnaco(db, relation_id)
            except Exception as e:  # pragma: no cover - evidence read is environment-dependent
                logger.warning(f"DNAco recompute after update failed for {relation_id}: {e}")
        return relation

    def delete_relation(self, db: Session, relation_id: str) -> bool:
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return False
        entity_domain_repo.remove_all_for_entity(db, entity_type=ENTITY_TYPE, entity_id=relation_id)
        authority_relation_repo.remove(db, id=relation_id)
        return True

    # ------------------------------------------------------- affirmations

    def _replace_affirmations(self, db: Session, relation_id: str, affirmations: List[Any]) -> None:
        authority_affirmation_repo.delete_for_relation(db, relation_id=relation_id)
        for idx, aff in enumerate(affirmations):
            a = aff.dict() if hasattr(aff, "dict") else dict(aff)
            authority_affirmation_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": relation_id,
                "role": a["role"],
                "principal": a["principal"],
                "principal_type": a.get("principal_type", "user"),
                "required": a.get("required", True),
                "affirmed": False,
                "sort_order": a.get("sort_order", idx),
            })

    def affirm(self, db: Session, affirmation_id: str, affirmed_by: str, notes: Optional[str] = None) -> Optional[AuthorityAffirmationDb]:
        aff = authority_affirmation_repo.get(db, affirmation_id)
        if not aff:
            return None
        return authority_affirmation_repo.update(db, db_obj=aff, obj_in={
            "affirmed": True, "affirmed_by": affirmed_by, "affirmed_at": self._now(), "notes": notes,
        })

    def is_fully_affirmed(self, db: Session, relation_id: str) -> bool:
        affs = authority_affirmation_repo.list_for_relation(db, relation_id=relation_id)
        required = [a for a in affs if a.required]
        return len(required) > 0 and all(a.affirmed for a in required)

    # ------------------------------------------------------- DNA-Coefficient

    def compute_dnaco(self, db: Session, relation_id: str, rows: Optional[List[Dict[str, Any]]] = None) -> Optional[AuthorityDnaRunDb]:
        """Compute the DNA-Coefficient over the AR's bound evidence.

        ``rows`` may be supplied directly (used by tests); otherwise they are
        read best-effort from the bound Delta table.
        """
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None

        binding = relation.evidence_binding or {}
        column_map = binding.get("column_map") or {}

        run = authority_dna_run_repo.create(db, obj_in={
            "id": str(uuid.uuid4()),
            "relation_id": relation_id,
            "status": "running",
            "started_at": self._now(),
        })

        try:
            if rows is None:
                rows = self._read_evidence_rows(binding)
            result = authority_dna.compute_dnaco(
                self._ar_spec(relation), rows, column_map, relation.dna_scoring_config
            )

            # Persist per-row divergences as evidence AR Decisions (the DNAco sample).
            for rd in result.rows:
                if not rd.diverged:
                    continue
                authority_decision_repo.create(db, obj_in={
                    "id": str(uuid.uuid4()),
                    "relation_id": relation_id,
                    "relation_version": relation.version,
                    "source": "evidence",
                    "dna_run_id": run.id,
                    "actor_identity": rd.actor_identity,
                    "action": rd.action,
                    "object_id": rd.object_id,
                    "verdict": None,
                    "reason": ", ".join(rd.reasons),
                    "divergence_magnitude": 1.0,
                    "direction": None,
                })

            run = authority_dna_run_repo.update(db, db_obj=run, obj_in={
                "status": "succeeded",
                "finished_at": self._now(),
                "sampled_count": result.sampled_count,
                "divergent_count": result.divergent_count,
                "magnitude": result.magnitude,
                "direction": result.direction,
            })

            # Roll the run up onto the Definition's aggregate DNAco.
            agg = {
                "dna_magnitude": result.magnitude,
                "dna_direction": result.direction,
                "dna_measured_at": self._now(),
            }
            # An active AR whose divergence exceeded its ceiling is auto-flagged.
            if relation.status == STATUS_ACTIVE and result.magnitude > (relation.dna_max_threshold or 0.3):
                agg["status"] = STATUS_NEEDS_REVIEW
            authority_relation_repo.update(db, db_obj=relation, obj_in=agg)
            return run
        except Exception as e:
            logger.error(f"DNAco computation failed for {relation_id}: {e}", exc_info=True)
            authority_dna_run_repo.update(db, db_obj=run, obj_in={
                "status": "failed", "finished_at": self._now(), "error_message": str(e),
            })
            raise

    def _read_evidence_rows(self, binding: Dict[str, Any], limit: int = 500) -> List[Dict[str, Any]]:
        """Best-effort read of the bound UC Delta table via the SQL warehouse.

        Isolated and defensive: any failure returns an empty sample rather than
        breaking the run (the manager surfaces the failure via the run status).
        """
        table = (binding or {}).get("source_table_fqn")
        if not table:
            return []
        try:
            from src.common.config import get_settings
            from src.common.workspace_client import get_workspace_client

            settings = get_settings()
            warehouse_id = (
                getattr(settings, "DATABRICKS_WAREHOUSE_ID", None)
                or getattr(settings, "DATABRICKS_SQL_WAREHOUSE_ID", None)
            )
            if not warehouse_id:
                logger.warning("No SQL warehouse configured; cannot read AR evidence table.")
                return []
            ws = get_workspace_client(settings)
            row_filter = (binding or {}).get("row_filter")
            where = f" WHERE {row_filter}" if row_filter else ""
            stmt = f"SELECT * FROM {table}{where} LIMIT {int(limit)}"
            resp = ws.statement_execution.execute_statement(
                warehouse_id=warehouse_id, statement=stmt, wait_timeout="30s",
            )
            manifest = getattr(resp, "manifest", None)
            result = getattr(resp, "result", None)
            if not manifest or not result or not getattr(result, "data_array", None):
                return []
            columns = [c.name for c in manifest.schema.columns]
            return [dict(zip(columns, r)) for r in result.data_array]
        except Exception as e:  # pragma: no cover - depends on live warehouse
            logger.warning(f"Evidence read failed for table '{table}': {e}")
            return []

    # ------------------------------------------------------------- lifecycle

    def set_status(self, db: Session, relation_id: str, status: str) -> Tuple[Optional[AuthorityRelationDb], Optional[str]]:
        """Transition an AR's status. Returns (relation, error_message)."""
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None, "not_found"
        if status == STATUS_ACTIVE:
            # Activation gate: DNAco measured & within ceiling, AND fully affirmed.
            if relation.dna_magnitude is None:
                return relation, "DNA-Coefficient has not been measured yet."
            if relation.dna_magnitude > (relation.dna_max_threshold or 0.3):
                return relation, (
                    f"DNA-Coefficient {relation.dna_magnitude} exceeds the maximum "
                    f"{relation.dna_max_threshold}."
                )
            if not self.is_fully_affirmed(db, relation_id):
                return relation, "All required affirmations must be completed before activation."
        updated = authority_relation_repo.update(db, db_obj=relation, obj_in={"status": status})
        return updated, None

    # --------------------------------------------------------- runtime gate

    def _evaluate_decision(self, relation: AuthorityRelationDb, req: Dict[str, Any]) -> Tuple[str, str]:
        """Deterministic evaluation of request params against the AR's decision_logic."""
        dl = relation.decision_logic or {}
        reasons: List[str] = []

        # Action must match when the AR constrains it.
        if dl.get("action") and req.get("action") and str(req["action"]) != str(dl["action"]):
            return VERDICT_DENIED, f"action '{req['action']}' does not match required '{dl['action']}'"

        # The signer must be an allowed principal (when the AR enumerates them).
        allowed = dl.get("allowed_principals") or []
        signer = req.get("actor_identity")
        if allowed:
            if not signer or signer not in allowed:
                return VERDICT_DENIED, f"signer '{signer}' is not an allowed principal"
            reasons.append("signer authorized")

        # Threshold: exceeding it requires an escalation flag.
        threshold = authority_dna._to_float(dl.get("threshold"))
        value = authority_dna._to_float(req.get("value"))
        if threshold is not None and value is not None and value > threshold:
            if not bool(req.get("escalated")):
                return VERDICT_DENIED, f"value {value} exceeds threshold {threshold} without escalation"
            reasons.append("escalation present for over-threshold value")

        # Required co-sign must be present.
        if dl.get("required_cosign") and not bool(req.get("cosign_present")):
            return VERDICT_DENIED, "required co-sign is missing"

        return VERDICT_APPROVED, "; ".join(reasons) or "all checks passed"

    def resolve(self, db: Session, ar_ref: str, req: Dict[str, Any], record: bool = True) -> Dict[str, Any]:
        """Deterministically resolve a decision against an *active* AR (by id or slug).

        Returns a verdict dict; ``no_authority`` when no matching active AR exists.
        """
        relation = authority_relation_repo.get(db, ar_ref) or authority_relation_repo.get_by_slug(db, ar_ref)
        if not relation or relation.status != STATUS_ACTIVE:
            return {
                "verdict": VERDICT_NO_AUTHORITY,
                "reason": "no active Authority Relation matches the supplied id",
                "relation_id": relation.id if relation else None,
                "relation_slug": relation.slug if relation else None,
            }

        verdict, reason = self._evaluate_decision(relation, req)

        if record:
            authority_decision_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": relation.id,
                "relation_version": relation.version,
                "source": "mcp",
                "actor_identity": req.get("actor_identity"),
                "action": req.get("action"),
                "object_id": req.get("object_id"),
                "request_params": req,
                "verdict": verdict,
                "reason": reason,
            })
            counters = {"usage_count": (relation.usage_count or 0) + 1}
            if verdict == VERDICT_APPROVED:
                counters["approved_count"] = (relation.approved_count or 0) + 1
            elif verdict == VERDICT_DENIED:
                counters["denied_count"] = (relation.denied_count or 0) + 1
            authority_relation_repo.update(db, db_obj=relation, obj_in=counters)

        return {
            "verdict": verdict,
            "reason": reason,
            "relation_id": relation.id,
            "relation_slug": relation.slug,
            "relation_version": relation.version,
            "dna_magnitude": relation.dna_magnitude,
            "dna_direction": relation.dna_direction,
        }

    # --------------------------------------------------------- read assembly

    def to_read_dict(self, db: Session, relation: AuthorityRelationDb) -> Dict[str, Any]:
        affs = authority_affirmation_repo.list_for_relation(db, relation_id=relation.id)
        domains = entity_domain_repo.get_domains_for_entity(db, entity_type=ENTITY_TYPE, entity_id=relation.id)
        fully_affirmed = self.is_fully_affirmed(db, relation.id)
        maturity = authority_dna.maturity_level(
            has_object=bool(relation.object_id),
            dna_measured=relation.dna_magnitude is not None,
            fully_affirmed=fully_affirmed,
        )
        return {
            "id": relation.id,
            "slug": relation.slug,
            "name": relation.name,
            "description": relation.description,
            "status": relation.status,
            "maturity_level": maturity,
            "version": relation.version,
            "version_family_id": relation.version_family_id,
            "actor_role": relation.actor_role,
            "actor_identity": relation.actor_identity,
            "actor_since": relation.actor_since,
            "action": relation.action,
            "object_type": relation.object_type,
            "object_id": relation.object_id,
            "object_resolves_to": relation.object_resolves_to,
            "domain_context": relation.domain_context,
            "justification_chain": relation.justification_chain,
            "decision_logic": relation.decision_logic,
            "evidence_binding": relation.evidence_binding,
            "dna_magnitude": relation.dna_magnitude,
            "dna_direction": relation.dna_direction,
            "dna_measured_at": relation.dna_measured_at,
            "dna_max_threshold": relation.dna_max_threshold,
            "schedule_cron": relation.schedule_cron,
            "fully_affirmed": fully_affirmed,
            "usage_count": relation.usage_count,
            "approved_count": relation.approved_count,
            "denied_count": relation.denied_count,
            "domains": [d.dict() if hasattr(d, "dict") else d for d in domains],
            "affirmations": [
                {
                    "id": a.id, "role": a.role, "principal": a.principal,
                    "principal_type": a.principal_type, "required": a.required,
                    "affirmed": a.affirmed, "affirmed_by": a.affirmed_by,
                    "affirmed_at": a.affirmed_at, "sort_order": a.sort_order,
                }
                for a in affs
            ],
            "created_at": relation.created_at,
            "updated_at": relation.updated_at,
            "created_by": relation.created_by,
        }

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
import json
import re
import uuid
import yaml
from sqlalchemy.orm import Session

from src.controller.entity_data_cleanup import remove_entity_data
from src.common.timestamps import utc_now
from src.common.logging import get_logger
from src.db_models.compliance import CompliancePolicyDb, ComplianceRunDb, ComplianceResultDb
from src.repositories.compliance_repository import (
    compliance_policy_repo,
    compliance_run_repo,
    compliance_result_repo,
)
from ..models.compliance import (
    CompliancePolicy,
    CompliancePolicyCreate,
    ComplianceResult,
    ComplianceRun,
    LlmCheckOutcome,
    LlmCheckTestResponse,
)
from src.common.compliance_dsl import evaluate_rule_on_object as eval_dsl, parse_rule, Evaluator
from src.common.compliance_actions import (
    APP_ENTITY_TYPES, ActionContext, ActionError, ActionExecutor, get_action_registry,
)
from src.common.compliance_notifications import ComplianceRunNotifier
from src.common.api_errors import CodedValueError, UserTokenRequiredError
from src.common.run_identity import RunIdentity
from src.common.compliance_llm_check import (
    BUDGET_EXCEEDED, QUOTA_EXCEEDED, DbLlmCallQuota, DbLlmCheckCache,
    LlmCheckError, LlmChecker, counts_as_failure, served_model_of,
)
from src.common.compliance_entities import (
    create_entity_iterator,
    llm_check_calls,
    llm_check_tag_actions,
    parse_entity_filter,
    EntityFilter,
    TableEnrichment,
)
from src.common.uc_table_enrichment import (
    FIELD_GROUP,
    KEYS,
    TableConstraintsReader,
    NOT_EVALUATED_CODE,
    StatementCache,
    WarehouseSqlRunner,
    conditions_without,
    fields_read,
    groups_for_fields,
    unavailable_fields_read,
)

if TYPE_CHECKING:
    from src.common.compliance_result_visibility import ViewerReadChecks


logger = get_logger(__name__)


TAG_ACTIONS = ('ASSIGN_TAG', 'REMOVE_TAG')
# Rule test (test_rule_on_sample): entities scanned for the named one, and model calls
SAMPLE_SCAN_LIMIT = 200
TEST_MAX_CALLS = 5


class SampleEntityNotFoundError(CodedValueError):
    """A rule test found no entity to try the rule on."""

    code = 'sample_entity_not_found'


def _str_or_none(value) -> Optional[str]:
    return None if value is None else str(value)


def _result_details(action_outcomes, llm_checks) -> Optional[str]:
    """The result's details_json: the actions' outcomes and the LLM_CHECK outcomes."""
    details: Dict[str, object] = {}
    if action_outcomes:
        details['actions'] = action_outcomes
    if llm_checks:
        details['llm_checks'] = [c.to_dict() for c in llm_checks]
    return json.dumps(details) if details else None


def _rule_actions(rule: Optional[str]) -> List[dict]:
    if not rule:
        return []
    try:
        parsed = parse_rule(rule)
    except Exception:
        return []
    return (parsed.get('on_pass_actions') or []) + (parsed.get('on_fail_actions') or [])


def rule_sends_notifications(rule: Optional[str]) -> bool:
    """Whether a rule has NOTIFY actions (False if it doesn't parse)."""
    return any(action.get('type') == 'NOTIFY' for action in _rule_actions(rule))


def _yaml_rule_refusal(rule: Optional[str]) -> Optional[str]:
    """Why a policy rule from the YAML file is not loaded, or None to load it.

    The YAML load checks what the API save refuses for a run's writes: tag actions on
    a rule with LLM_CHECK. A rule that doesn't parse is loaded as before (its runs fail
    with ``rule_parse_failed``).
    """
    if not rule:
        return None
    try:
        refused = llm_check_tag_actions(parse_rule(rule))
    except Exception:
        return None
    if refused:
        return f"llm_check_tag_action: a rule with LLM_CHECK can't use {', '.join(refused)}"
    return None


def _yaml_mapping_refusal(raw: Dict[str, Any], mapping: Any) -> Optional[str]:
    """Why a YAML policy with LLM_CHECK is not loaded: the self-service mapping lists it.

    Self-service evaluates the mapping's policies without a model, so the policy
    would fail every object there. The policy save and the mapping save refuse the
    same pair (``refuse_llm_check_where_it_cannot_run``).
    """
    from types import SimpleNamespace

    from src.controller.self_service_manager import mapping_object_types_of

    if not rule_uses_llm_check(raw.get('rule')):
        return None
    policy = SimpleNamespace(id=raw.get('id'), slug=raw.get('slug'), name=raw.get('name'))
    object_types = mapping_object_types_of(mapping, policy)
    if object_types:
        return (
            "llm_check_policy_in_self_service: the self-service compliance mapping "
            f"lists it for {', '.join(object_types)}"
        )
    return None


def rule_uses_llm_check(rule: Optional[str]) -> bool:
    """Whether a rule calls LLM_CHECK.

    A rule that doesn't parse counts when its text names LLM_CHECK, so the gates
    that use this err on the safe side.
    """
    if not rule:
        return False
    try:
        return bool(llm_check_calls(parse_rule(rule)))
    except Exception:
        return re.search(r'\bLLM_CHECK\s*\(', rule, re.IGNORECASE) is not None


def rule_changes_tags(rule: Optional[str]) -> bool:
    """Whether a rule has ASSIGN_TAG / REMOVE_TAG actions (False if it doesn't parse)."""
    if not rule:
        return False
    try:
        parsed = parse_rule(rule)
    except Exception:
        return False
    actions = (parsed.get('on_pass_actions') or []) + (parsed.get('on_fail_actions') or [])
    return any(action.get('type') in TAG_ACTIONS for action in actions)


class TagsManagerTagAdapter:
    """EntityTagManager for compliance policy actions (ASSIGN_TAG / REMOVE_TAG).

    Writes tag associations for the entities a policy evaluates, as part of the
    policy run's transaction: nothing is committed here (the run commits once at
    the end), and each write runs in a savepoint so a failing action is rolled
    back on its own without breaking the session for the rest of the run.

    Keys are fully qualified tag names (``namespace/name``); a bare name is a tag
    in the default namespace. Tags must already exist. Only Ontos entities whose
    tags the app displays are supported; Unity Catalog objects are rejected
    explicitly.

    Values: ``None`` (``ASSIGN_TAG 'k'``) assigns the key and keeps a value the
    entity already has; ``''`` clears it; any other string sets it, and must be
    one of the tag's ``possible_values`` when the tag defines them. Failures
    raise ``ActionError`` with a code the run results show translated.

    No permission check happens here: the compliance routes require write
    access to tags (``require_tag_write_for_tag_actions``) before a policy with
    tag actions is saved or run. Any other caller must check it first.
    """

    # Compliance entity type -> entity_type used by tag associations in the app
    ENTITY_TYPES = APP_ENTITY_TYPES

    def __init__(self, db: Session, user_email: Optional[str] = None):
        self._db = db
        self._user_email = user_email
        self._tags: Dict[str, object] = {}

    def _tag_entity_type(self, entity_type: str) -> str:
        mapped = self.ENTITY_TYPES.get(entity_type)
        if not mapped:
            supported = ', '.join(sorted(self.ENTITY_TYPES))
            raise ActionError(
                'tag_entity_type_unsupported',
                f"Tag actions are not supported for '{entity_type}' entities (supported: {supported})",
                entityType=entity_type, supported=supported,
            )
        return mapped

    @staticmethod
    def _check_entity_id(entity_id: str) -> None:
        if not entity_id or entity_id == 'unknown':
            raise ActionError('tag_entity_without_id', "Entity has no id; tag actions need a stable entity id")

    def _resolve(self, key: str):
        if key not in self._tags:
            from src.repositories.tags_repository import tag_repo

            self._tags[key] = tag_repo.get_by_fully_qualified_name(self._db, fqn=key)
        tag = self._tags[key]
        if not tag:
            raise ActionError(
                'tag_not_found',
                f"Tag '{key}' not found; create it first (a bare name is looked up in the default namespace)",
                tag=key,
            )
        return tag

    @staticmethod
    def _check_value(tag, key: str, value: Optional[str]) -> None:
        allowed = [str(v) for v in (tag.possible_values or [])]
        if value and allowed and value not in allowed:
            raise ActionError(
                'tag_value_not_allowed',
                f"Value '{value}' is not allowed for tag '{key}' (allowed: {', '.join(allowed)})",
                tag=key, value=value, allowed=', '.join(allowed),
            )

    def _log_change(self, entity_type: str, entity_id: str, action: str, details: dict) -> None:
        # Same entry change_log_manager writes, without its commit.
        from src.db_models.change_log import ChangeLogDb

        self._db.add(ChangeLogDb(
            entity_type=entity_type,
            entity_id=str(entity_id),
            action=action,
            username=self._user_email,
            details_json=json.dumps(details),
        ))

    def assign_tag(self, entity_type: str, entity_id: str, key: str, value: Optional[str]) -> None:
        from src.db_models.tags import EntityTagAssociationDb
        from src.repositories.tags_repository import entity_tag_repo

        tag_entity_type = self._tag_entity_type(entity_type)
        self._check_entity_id(entity_id)
        tag = self._resolve(key)
        self._check_value(tag, key, value)
        if value is None:
            existing = self._db.query(EntityTagAssociationDb).filter_by(
                entity_id=str(entity_id), entity_type=tag_entity_type, tag_id=tag.id,
            ).first()
            if existing:
                # Key-only: the tag is already assigned; keep its value and assigner.
                return
        with self._db.begin_nested():
            entity_tag_repo.add_tag_to_entity(
                self._db,
                entity_id=str(entity_id),
                entity_type=tag_entity_type,
                tag_id=tag.id,
                assigned_value=value,
                assigned_by=self._user_email,
            )
            self._log_change(tag_entity_type, entity_id, "TAG_ASSIGN", {
                "tag": key,
                "assigned_value": value,
                "summary": (
                    f"Tag '{key}' assigned by compliance policy" if value is None
                    else f"Tag '{key}' assigned with value '{value}' by compliance policy"
                ),
            })

    def remove_tag(self, entity_type: str, entity_id: str, key: str) -> None:
        from src.repositories.tags_repository import entity_tag_repo

        tag_entity_type = self._tag_entity_type(entity_type)
        self._check_entity_id(entity_id)
        tag = self._resolve(key)
        with self._db.begin_nested():
            removed = entity_tag_repo.remove_tag_from_entity(
                self._db, entity_id=str(entity_id), entity_type=tag_entity_type, tag_id=tag.id
            )
            if removed:
                self._log_change(tag_entity_type, entity_id, "TAG_REMOVE", {
                    "tag": key,
                    "summary": f"Tag '{key}' removed by compliance policy",
                })
        if not removed:
            logger.info(f"REMOVE_TAG {key}: tag was not assigned to {tag_entity_type} {entity_id}")


def _action_outcomes(action_results) -> List[Dict[str, object]]:
    """What each action did, stored on the result so the run details can show it.

    Side-effect actions only (PASS / FAIL decide the result itself). A failure
    carries its code and params, never raw exception text.
    """
    outcomes: List[Dict[str, object]] = []
    for result in action_results:
        if result.action_type in ('PASS', 'FAIL'):
            continue
        outcome: Dict[str, object] = {'type': result.action_type, 'success': bool(result.success)}
        if result.target is not None:
            outcome['target'] = result.target
        if not result.success:
            outcome['code'] = result.code or 'action_failed'
            outcome['params'] = result.params or {}
        outcomes.append(outcome)
    return outcomes


def _run_scored(run: ComplianceRunDb) -> bool:
    """Whether a run's score measures anything: it succeeded and evaluated at
    least one entity (passed or failed). A failed run, or one whose entities
    were all not evaluated (or that matched none), has no score."""
    return run.status == 'succeeded' and bool(
        (run.success_count or 0) + (run.failure_count or 0)
    )


def run_score_fields(
    run: ComplianceRunDb, not_evaluated: Optional[int] = None,
) -> Dict[str, object]:
    """``score`` (None when the run has none, see ``_run_scored``) and ``coverage``.

    ``coverage``: entities evaluated (passed or failed) and not evaluated (by
    default the run's ``not_evaluated_count``), so a score measured on a few of
    many entities says so. A run without a score stores None
    (``o3_compliance_run_score_nullable``).
    """
    if not_evaluated is None:
        not_evaluated = getattr(run, 'not_evaluated_count', None)
    evaluated = (run.success_count or 0) + (run.failure_count or 0)
    return {
        'score': run.score if _run_scored(run) else None,
        'coverage': {'evaluated': evaluated, 'not_evaluated': int(not_evaluated or 0)},
    }


def viewer_run_fields(run: ComplianceRunDb, counts: Dict[str, int]) -> Dict[str, object]:
    """A run's counts, ``score`` and ``coverage`` over the results one viewer can
    read (``counts``: ``ComplianceManager.viewer_run_counts``), and ``hidden_count``.

    Without a hidden result they are the stored ones (``run_score_fields``). With
    some, the score is recomputed from the visible passes and failures, so it
    says nothing about the objects the viewer can't read.
    """
    success, failure = counts['success'], counts['failure']
    hidden = counts['hidden']
    fields = run_score_fields(run, counts['not_evaluated'])
    if hidden:
        evaluated = success + failure
        fields['score'] = (
            round(100.0 * success / evaluated, 2)
            if run.status == 'succeeded' and evaluated else None
        )
        fields['coverage']['evaluated'] = evaluated
    return {
        'success_count': success, 'failure_count': failure, **fields, 'hidden_count': hidden,
    }


class ComplianceManager:
    def __init__(self):
        # Stateless; uses DB via repositories
        self.action_executor = ActionExecutor(get_action_registry())

    # --- Policy CRUD ---
    def load_from_yaml(self, db: Session, yaml_path: str) -> None:
        from src.controller.self_service_manager import load_compliance_mapping

        mapping = load_compliance_mapping()
        with open(yaml_path) as f:
            data = yaml.safe_load(f) or []
            for raw in data:
                model = CompliancePolicy(**{k: v for k, v in raw.items() if k not in {'examples', 'sample_runs'}})
                refused = _yaml_rule_refusal(model.rule) or _yaml_mapping_refusal(raw, mapping)
                if refused:
                    # Not stored (a stored one stays as it is): runs would refuse it anyway
                    logger.warning(
                        "Skipped compliance policy %s from %s: %s", model.id, yaml_path, refused,
                    )
                    continue
                # Upsert by id
                existing = db.get(CompliancePolicyDb, str(model.id))
                if existing:
                    existing.name = model.name
                    existing.description = model.description
                    existing.rule = model.rule
                    existing.category = model.category
                    existing.severity = model.severity
                    existing.is_active = model.is_active
                    existing.updated_at = utc_now()
                    policy_db = existing
                else:
                    policy_db = CompliancePolicyDb(
                        id=str(model.id),
                        name=model.name,
                        description=model.description,
                        rule=model.rule,
                        category=model.category,
                        severity=model.severity,
                        is_active=model.is_active,
                    )
                    db.add(policy_db)
                db.flush()

                # Optional: seed sample runs and results
                sample_runs = raw.get('sample_runs') or []
                if isinstance(sample_runs, list) and sample_runs:
                    for rdef in sample_runs:
                        try:
                            run_id = str(rdef.get('id') or uuid.uuid4())
                            # Avoid duplicate seeding if run already exists
                            if db.get(ComplianceRunDb, run_id):
                                continue
                            # Parse timestamps
                            def _parse_dt(val):
                                if not val:
                                    return None
                                try:
                                    parsed = datetime.fromisoformat(val.replace('Z', '+00:00'))
                                except Exception:
                                    return utc_now()
                                # Seeded times without an offset are UTC
                                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                            results_defs = rdef.get('results') or []
                            success_count = rdef.get('success_count')
                            failure_count = rdef.get('failure_count')
                            score = rdef.get('score')
                            if success_count is None or failure_count is None:
                                # compute from results
                                s = sum(1 for it in results_defs if bool(it.get('passed')))
                                f = sum(1 for it in results_defs if not bool(it.get('passed')))
                                success_count = s
                                failure_count = f
                            if score is None:
                                total = max(1, (success_count or 0) + (failure_count or 0))
                                score = round(100.0 * (float(success_count) / float(total)), 2)
                            run_db = ComplianceRunDb(
                                id=run_id,
                                policy_id=policy_db.id,
                                status=str(rdef.get('status') or 'succeeded'),
                                started_at=_parse_dt(rdef.get('started_at')) or utc_now(),
                                finished_at=_parse_dt(rdef.get('finished_at')),
                                success_count=int(success_count or 0),
                                failure_count=int(failure_count or 0),
                                score=float(score or 0.0),
                                error_message=rdef.get('error_message'),
                            )
                            db.add(run_db)
                            db.flush()
                            # Seed results
                            for resdef in results_defs:
                                res_db = ComplianceResultDb(
                                    id=str(resdef.get('id') or uuid.uuid4()),
                                    run_id=run_db.id,
                                    object_type=str(resdef.get('object_type') or 'object'),
                                    object_id=str(resdef.get('object_id') or resdef.get('object_name') or 'unknown'),
                                    object_name=resdef.get('object_name'),
                                    passed=bool(resdef.get('passed', False)),
                                    message=resdef.get('message'),
                                    details_json=(resdef.get('details_json')),
                                )
                                db.add(res_db)
                        except Exception:
                            logger.exception("Failed seeding sample compliance run from YAML for policy %s", policy_db.id)
                db.flush()

                # Optional: generate historical daily runs (no per-object results)
                history_seed = raw.get('history_seed') or {}
                try:
                    days = int(history_seed.get('days', 0) or 0)
                except Exception:
                    days = 0
                if days > 0:
                    base_score = float(history_seed.get('base_score', 85.0))
                    variance = float(history_seed.get('variance', 6.0))
                    total_checks = int(history_seed.get('total_checks', 40))
                    # Build set of existing date keys to avoid duplicates
                    existing_runs = db.query(ComplianceRunDb).filter(ComplianceRunDb.policy_id == policy_db.id).all()
                    existing_dates = { (r.started_at.date().isoformat() if r.started_at else None) for r in existing_runs }
                    today = datetime.utcnow().date()
                    for i in range(days-1, -1, -1):
                        d = today - timedelta(days=i)
                        key = d.isoformat()
                        if key in existing_dates:
                            continue
                        # Slight deterministic variation by day
                        wave = ((hash(key) % 7) - 3)  # -3..+3
                        score = base_score + (variance * wave / 3.0)
                        score = max(75.0, min(100.0, score))
                        success_count = int(round(total_checks * (score / 100.0)))
                        failure_count = max(0, total_checks - success_count)
                        dt = datetime(d.year, d.month, d.day, 9, 0, 0)
                        run_db = ComplianceRunDb(
                            id=str(uuid.uuid4()),
                            policy_id=policy_db.id,
                            status='succeeded',
                            started_at=dt,
                            finished_at=dt + timedelta(minutes=1),
                            success_count=success_count,
                            failure_count=failure_count,
                            score=round(score, 2),
                        )
                        db.add(run_db)
                    db.flush()
            db.commit()

    def list_policies(self, db: Session) -> List[CompliancePolicyDb]:
        return compliance_policy_repo.list_all(db)

    def get_policy(self, db: Session, policy_id: str) -> Optional[CompliancePolicyDb]:
        return db.get(CompliancePolicyDb, policy_id)

    def create_policy(
        self,
        db: Session,
        policy: CompliancePolicyCreate,
        current_user: Optional[str] = None,
    ) -> CompliancePolicyDb:
        db_obj = CompliancePolicyDb(
            id=str(uuid.uuid4()),  # Server-generated UUID
            name=policy.name,
            description=policy.description,
            failure_message=policy.failure_message,
            rule=policy.rule,
            category=policy.category,
            severity=policy.severity,
            is_active=policy.is_active,
        )
        db.add(db_obj)
        
        # Log to change log for timeline
        try:
            from src.controller.change_log_manager import change_log_manager
            change_log_manager.log_change_with_details(
                db,
                entity_type='compliance_policy',
                entity_id=db_obj.id,
                action='CREATE',
                username=current_user,
                details={"name": db_obj.name}
            )
        except Exception as log_err:
            logger.warning(f"Failed to log change for policy creation: {log_err}")
        
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def update_policy(
        self, 
        db: Session, 
        policy_id: str, 
        policy: CompliancePolicy,
        current_user: Optional[str] = None,
    ) -> Optional[CompliancePolicyDb]:
        existing = db.get(CompliancePolicyDb, policy_id)
        if not existing:
            return None
        existing.name = policy.name
        existing.description = policy.description
        existing.failure_message = policy.failure_message
        existing.rule = policy.rule
        existing.category = policy.category
        existing.severity = policy.severity
        existing.is_active = policy.is_active
        existing.updated_at = utc_now()
        
        # Log to change log for timeline
        try:
            from src.controller.change_log_manager import change_log_manager
            change_log_manager.log_change_with_details(
                db,
                entity_type='compliance_policy',
                entity_id=policy_id,
                action='UPDATE',
                username=current_user,
                details={"name": existing.name}
            )
        except Exception as log_err:
            logger.warning(f"Failed to log change for policy update: {log_err}")
        
        db.commit()
        db.refresh(existing)
        return existing

    def delete_policy(
        self, 
        db: Session, 
        policy_id: str,
        current_user: Optional[str] = None,
    ) -> bool:
        existing = db.get(CompliancePolicyDb, policy_id)
        if not existing:
            return False
        
        # Log to change log for timeline (before deletion)
        try:
            from src.controller.change_log_manager import change_log_manager
            change_log_manager.log_change_with_details(
                db,
                entity_type='compliance_policy',
                entity_id=policy_id,
                action='DELETE',
                username=current_user,
                details={"name": existing.name},
            )
        except Exception as log_err:
            logger.warning(f"Failed to log change for policy deletion: {log_err}")
        
        remove_entity_data(db, entity_type='compliance_policy', entity_id=policy_id)
        db.delete(existing)
        db.commit()
        return True

    # --- Stats ---
    @staticmethod
    def _latest_score(db: Session, policy_id: str) -> Optional[float]:
        """Score of the policy's latest run that has one; None if no recent run has one.

        A failed run, or one whose entities were all not evaluated (a source
        could not be read), has no score of its own; it keeps the one before it.
        """
        runs = compliance_run_repo.list_for_policy(db, policy_id=policy_id, limit=20)
        return next((r.score for r in runs if _run_scored(r)), None)

    def get_compliance_stats(self, db: Session) -> Dict[str, Optional[float]]:
        """Overall compliance, active policies and critical issues.

        ``overall_compliance`` averages the policies that have a score (see
        ``_latest_score``); a policy without one is left out, not counted as 0,
        and with none at all it is None. ``critical_issues`` counts the critical
        policies whose score is below 70: one without a score is not an issue
        found, so it isn't counted.
        """
        policies = self.list_policies(db)
        # Use latest run score per policy
        scores: List[float] = []
        critical_issues = 0
        for p in policies:
            score = self._latest_score(db, p.id)
            if score is None:
                continue
            scores.append(score)
            if (p.severity or '').lower() == 'critical' and score < 70:
                critical_issues += 1
        overall = sum(scores) / len(scores) if scores else None
        active = len([p for p in policies if p.is_active])
        return {
            "overall_compliance": overall,
            "active_policies": active,
            "critical_issues": critical_issues,
        }

    def get_policies_with_stats(self, db: Session, yaml_path: Optional[str] = None) -> Dict:
        """Get all policies with compliance stats and scores.
        
        Args:
            db: Database session
            yaml_path: Optional path to YAML file for lazy loading
            
        Returns:
            Dict with 'policies' list and 'stats' dict
        """
        # Lazy-load YAML into DB if DB has no policies yet
        if yaml_path:
            try:
                from pathlib import Path
                import os
                count = db.query(CompliancePolicyDb).count()
                if count == 0 and os.path.exists(yaml_path):
                    self.load_from_yaml(db, yaml_path)
            except Exception as e:
                logger.exception(f"Failed preloading compliance YAML: {e}")
        
        rows = self.list_policies(db)
        stats = self.get_compliance_stats(db)
        
        # Format policies with compliance scores
        policies = []
        for r in rows:
            # Get latest run score for this policy
            compliance_score = self._latest_score(db, r.id)
            
            policies.append({
                'id': r.id,
                'name': r.name,
                'description': r.description,
                'failure_message': r.failure_message,
                'rule': r.rule,
                'created_at': r.created_at,
                'updated_at': r.updated_at,
                'is_active': r.is_active,
                'severity': r.severity,
                'category': r.category,
                'compliance': compliance_score,
                'history': [],
            })
        
        return {
            "policies": policies,
            "stats": stats
        }
    
    def get_policy_with_examples(self, db: Session, policy_id: str, yaml_path: Optional[str] = None) -> Optional[Dict]:
        """Get a specific policy with examples from YAML.
        
        Args:
            db: Database session
            policy_id: Policy ID to retrieve
            yaml_path: Optional path to YAML file containing examples
            
        Returns:
            Dict with policy details and examples, or None if not found
        """
        r = self.get_policy(db, policy_id)
        if not r:
            return None
        
        # Try reading examples from YAML for this policy
        examples = None
        if yaml_path:
            try:
                from pathlib import Path
                import os
                if os.path.exists(yaml_path):
                    with open(yaml_path) as _f:
                        _data = yaml.safe_load(_f) or []
                        if isinstance(_data, list):
                            for _item in _data:
                                if isinstance(_item, dict) and str(_item.get('id')) == r.id:
                                    ex = _item.get('examples')
                                    if isinstance(ex, dict):
                                        examples = ex
                                    break
            except Exception as e:
                # Non-fatal; just omit examples on error
                logger.debug(f"Could not load examples for policy {policy_id}: {e}")
        
        return {
            'id': r.id,
            'name': r.name,
            'description': r.description,
            'failure_message': r.failure_message,
            'rule': r.rule,
            'created_at': r.created_at,
            'updated_at': r.updated_at,
            'is_active': r.is_active,
            'severity': r.severity,
            'category': r.category,
            'examples': examples,
        }

    def get_compliance_trend(
        self, db: Session, days: int = 30
    ) -> List[Dict[str, Optional[float]]]:
        end = datetime.utcnow().date()
        start = end - timedelta(days=days - 1)
        # Gather runs within the window
        runs = db.query(ComplianceRunDb).all()
        by_date: Dict[str, List[float]] = {}
        for r in runs:
            if not r.started_at or not _run_scored(r):
                continue
            d = r.started_at.date()
            if d < start or d > end:
                continue
            key = d.isoformat()
            by_date.setdefault(key, []).append(float(r.score or 0.0))
        # One point per day; a day without a scored run has no score (None), not 0 %
        trend: List[Dict[str, Optional[float]]] = []
        for i in range(days - 1, -1, -1):
            d = (end - timedelta(days=i)).isoformat()
            vals = by_date.get(d, [])
            avg = round(sum(vals) / len(vals), 2) if vals else None
            trend.append({"date": d, "compliance": avg})
        return trend

    # --- Runs ---
    def create_run(self, db: Session, *, policy_id: str) -> ComplianceRunDb:
        run = ComplianceRunDb(
            id=str(uuid.uuid4()),
            policy_id=policy_id,
            status='running',
            started_at=utc_now(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def complete_run(
        self, db: Session, run: ComplianceRunDb, *, success_count: int, failure_count: int,
        score: Optional[float], error_message: Optional[str] = None,
        error_code: Optional[str] = None, error_params: Optional[dict] = None,
        warning_code: Optional[str] = None,
        warning_params: Optional[dict] = None, llm_calls: Optional[int] = None,
        llm_cache_hits: Optional[int] = None, not_evaluated_count: Optional[int] = None,
    ) -> ComplianceRunDb:
        run.success_count = success_count
        run.llm_calls, run.llm_cache_hits = llm_calls, llm_cache_hits
        run.not_evaluated_count = not_evaluated_count
        run.failure_count = failure_count
        run.score = score
        run.finished_at = utc_now()
        run.status = 'succeeded' if error_message is None else 'failed'
        run.error_message = error_message
        # A code the UI translates (see common/compliance_errors.py); the message is the fallback
        run.error_code = error_code if error_message is not None else None
        run.error_params = json.dumps(error_params) if error_code and error_params else None
        # What a finished run has to report; a failed run reports its error only
        run.warning_code = warning_code if error_message is None else None
        run.warning_params = (
            json.dumps(warning_params) if run.warning_code and warning_params else None
        )
        db.commit()
        db.refresh(run)
        return run

    def list_runs(self, db: Session, *, policy_id: str, limit: int = 50) -> List[ComplianceRunDb]:
        return compliance_run_repo.list_for_policy(db, policy_id=policy_id, limit=limit)

    def not_evaluated_counts(self, db: Session, run_ids: List[str]) -> Dict[str, int]:
        """Results not evaluated, per run id (for the runs' coverage)."""
        return compliance_result_repo.not_evaluated_counts(db, run_ids)

    def list_results(self, db: Session, *, run_id: str, only_failed: bool = False, limit: int = 1000) -> List[ComplianceResultDb]:
        return compliance_result_repo.list_for_run(db, run_id=run_id, only_failed=only_failed, limit=limit)

    def viewer_run_counts(
        self, db: Session, runs: List[ComplianceRunDb], checks: 'ViewerReadChecks',
    ) -> Dict[str, Dict[str, int]]:
        """Per run id: ``success``, ``failure`` and ``not_evaluated`` over the results
        the viewer can read (``checks``), and ``hidden``, how many they can't.

        The stored counts less the hidden results: only results on Unity Catalog
        objects are checked (app entities are visible to compliance readers), and
        runs seeded without results keep their counts.
        """
        from src.common.compliance_result_visibility import (
            UC_RESULT_TYPES, hidden_result_tallies,
        )

        ids = [r.id for r in runs]
        not_evaluated = self.not_evaluated_counts(db, ids)
        hidden = hidden_result_tallies(
            compliance_result_repo.typed_result_rows(db, ids, UC_RESULT_TYPES), checks,
        )
        counts: Dict[str, Dict[str, int]] = {}
        for run in runs:
            h = hidden.get(run.id, {})
            counts[run.id] = {
                'success': max(0, (run.success_count or 0) - h.get('passed', 0)),
                'failure': max(0, (run.failure_count or 0) - h.get('failed', 0)),
                'not_evaluated': max(0, not_evaluated.get(run.id, 0) - h.get('not_evaluated', 0)),
                'hidden': sum(h.values()),
            }
        return counts

    def viewer_results_page(
        self, db: Session, *, run_id: str, checks: 'ViewerReadChecks',
        only_failed: bool = False, offset: int = 0, limit: int = 500,
    ) -> Tuple[List[ComplianceResultDb], int, int]:
        """One page of the run's results the viewer can read, newest first.

        Returns ``(page, total, hidden)``: ``total`` counts every visible result
        (all pages), ``hidden`` the results left out, both under ``only_failed``.
        """
        from src.common.compliance_result_visibility import (
            UC_RESULT_TYPES, hidden_result_tallies,
        )

        hidden_by_outcome = hidden_result_tallies(
            compliance_result_repo.typed_result_rows(db, [run_id], UC_RESULT_TYPES), checks,
        ).get(run_id, {})
        hidden = (hidden_by_outcome.get('failed', 0) if only_failed
                  else sum(hidden_by_outcome.values()))
        total = compliance_result_repo.count_for_run(
            db, run_id=run_id, only_failed=only_failed,
        ) - hidden
        page: List[ComplianceResultDb] = []
        skipped = 0
        if limit > 0:
            for r in compliance_result_repo.iter_for_run(
                db, run_id=run_id, only_failed=only_failed,
            ):
                if not checks.can_read(r.object_type, r.object_id):
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                page.append(r)
                if len(page) >= limit:
                    break
        return page, max(0, total), hidden

    # --- DSL evaluation (minimal): iterate over UC and app objects ---
    def _evaluate_rule_on_object(self, rule: str, obj: Dict[str, any]) -> Tuple[bool, Optional[str]]:
        return eval_dsl(rule, obj)

    def _iterate_objects(self, db: Session, scope: str) -> List[Dict[str, any]]:
        """Yield objects based on scope keywords in the rule: catalog objects or app entities."""
        objs: List[Dict[str, any]] = []
        scope_lower = scope.lower()
        # Unity Catalog objects
        if 'table' in scope_lower or 'view' in scope_lower or 'schema' in scope_lower or 'catalog' in scope_lower:
            try:
                from src.common.workspace_client import get_workspace_client
                ws = get_workspace_client()
                for cat in ws.catalogs.list():
                    objs.append({"type": "catalog", "name": cat.name})
                    for sch in ws.schemas.list(catalog_name=cat.name):
                        objs.append({"type": "schema", "name": sch.name, "catalog": cat.name})
                        for tbl in ws.tables.list(catalog_name=cat.name, schema_name=sch.name):
                            ttype = getattr(tbl, 'table_type', None)
                            objs.append({
                                "type": "view" if ttype == 'VIEW' else 'table',
                                "name": tbl.name,
                                "full_name": getattr(tbl, 'full_name', f"{cat.name}.{sch.name}.{tbl.name}")
                            })
            except Exception:
                logger.exception("Failed iterating UC objects for compliance evaluation")
        # App objects: data contracts
        if 'data contract' in scope_lower or 'data_contract' in scope_lower or 'contract' in scope_lower:
            from src.repositories.data_contracts_repository import data_contract_repo
            rows = data_contract_repo.list(db)
            for r in rows:
                objs.append({
                    "type": "data_contract",
                    "name": r.name,
                    "id": r.id,
                    "status": r.status,
                })
        return objs

    @staticmethod
    def policy_gate_uses(db: Session, policy_id: str) -> Dict[str, int]:
        """Where a policy is evaluated without a model: policy_check steps of ACTIVE
        workflows and maturity gates (counts). ``LLM_CHECK`` always fails there.

        An inactive workflow isn't counted: it saves with a warning, and can't be
        activated while its step uses an ``LLM_CHECK`` policy.
        """
        from src.common.workflow_step_config import policy_id_of
        from src.db_models.maturity import MaturityGateDb
        from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb

        steps = 0
        active_steps = (
            db.query(WorkflowStepDb)
            .join(ProcessWorkflowDb, WorkflowStepDb.workflow_id == ProcessWorkflowDb.id)
            .filter(
                WorkflowStepDb.step_type == 'policy_check',
                ProcessWorkflowDb.is_active.is_(True),
            )
        )
        for step in active_steps:
            try:
                config = json.loads(step.config) if isinstance(step.config, str) else step.config
            except (TypeError, ValueError):
                continue
            if isinstance(config, dict) and policy_id_of(config) == policy_id:
                steps += 1
        gates = db.query(MaturityGateDb).filter(
            MaturityGateDb.compliance_policy_id == policy_id,
        ).count()
        return {'workflowSteps': steps, 'maturityGates': gates}

    @staticmethod
    def _settings():
        from src.common.config import get_settings

        try:
            return get_settings()
        except RuntimeError:
            # Not initialized: LLM_CHECK then fails closed (llm_check_disabled)
            return None

    @classmethod
    def llm_quota(cls, db: Session, user: str) -> DbLlmCallQuota:
        """The daily LLM_CHECK calls of ``user``.

        The limit is COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_USER_PER_DAY.
        """
        limit = getattr(
            cls._settings(), 'COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_USER_PER_DAY', 400,
        )
        return DbLlmCallQuota(db, user, limit)

    @classmethod
    def llm_checker(
        cls, db: Session, max_calls: Optional[int] = None, *, purge_expired: bool = False,
        quota_user: Optional[str] = None,
    ) -> LlmChecker:
        """The LLM_CHECK runner of a run: the configured endpoint and budget, the DB cache.

        ``purge_expired`` deletes the cached verdicts past their max age first
        (when a run starts). A Compliance Checks job run makes one and passes it
        to every policy run, so the budget covers the whole job run.
        ``quota_user``: the user who started the run or test, whose daily calls
        it counts against (see ``DbLlmCallQuota``); None for scheduled runs.
        """
        settings = cls._settings()
        cache = DbLlmCheckCache(
            db, max_age_days=getattr(settings, 'COMPLIANCE_LLM_CHECK_CACHE_MAX_AGE_DAYS', 30),
        )
        if purge_expired:
            try:
                cache.purge_expired()
            except Exception as e:
                logger.warning("Could not delete expired LLM_CHECK verdicts: %s", e)
        quota = cls.llm_quota(db, quota_user) if quota_user else None
        return LlmChecker(
            settings, cache=cache, max_calls=max_calls, quota=quota,
            model_resolver=served_model_of,
        )

    def test_rule_on_sample(
        self, db: Session, *, rule: str, entity: Optional[str] = None,
        run_identity: Optional[RunIdentity] = None, quota_user: Optional[str] = None,
    ) -> LlmCheckTestResponse:
        """Evaluate a rule's ASSERT on one entity it matches, LLM_CHECKs included.

        For trying a criterion in the rule editor before the rule is saved: no
        run, result or action is written, only the verdicts to the cache. The
        entity is the one named ``entity`` (name, id or full name) among the
        first ``SAMPLE_SCAN_LIMIT`` the rule matches, else the first match.
        ``run_identity``: whose permissions Unity Catalog is read with (the
        caller's own, see ``run_policy_inline``); default: the app's.
        ``quota_user``: the user whose daily LLM_CHECK calls the test counts against.

        Raises:
            ValueError: the rule doesn't parse.
            SampleEntityNotFoundError: no entity matches.
        """
        from types import SimpleNamespace

        parsed = parse_rule(rule)
        entity_filter = parse_entity_filter(rule, parsed=parsed)
        source = SimpleNamespace(name='rule test', id='unsaved')
        ws = self._workspace_client_for(entity_filter.entity_types, source, run_identity)
        iterator = create_entity_iterator(db=db, workspace_client=ws)
        wanted = (entity or '').strip()
        sample = None
        for obj in iterator.iterate(
            entity_filter, limit=SAMPLE_SCAN_LIMIT if wanted else 1, source='a rule test',
        ):
            names = {str(obj.get(k)) for k in ('name', 'id', 'full_name') if obj.get(k) is not None}
            if not wanted or wanted in names:
                sample = obj
                break
        if sample is None:
            named = f" with the name '{wanted}'" if wanted else ""
            raise SampleEntityNotFoundError(
                f"No entity the rule matches was found{named}", entity=wanted,
            )

        evaluator = Evaluator(sample, llm_checker=self.llm_checker(
            db, max_calls=TEST_MAX_CALLS, quota_user=quota_user,
        ))
        passed, error_code = True, None
        if parsed.get('assert_clause') is not None:
            try:
                passed = bool(evaluator.evaluate(parsed['assert_clause']))
            except LlmCheckError as e:
                passed, error_code = False, e.code
            except Exception as e:
                logger.warning("Rule test evaluation failed: %s", e)
                passed, error_code = False, 'rule_evaluation_failed'
        db.commit()
        return LlmCheckTestResponse(
            entity_type=str(sample.get('type') or 'object'),
            entity_id=_str_or_none(sample.get('id') or sample.get('full_name')),
            entity_name=_str_or_none(sample.get('name')),
            passed=passed,
            error_code=error_code,
            llm_checks=[LlmCheckOutcome(**c.to_dict()) for c in evaluator.llm_checks],
        )

    def _workspace_client_for(
        self, entity_types: List[str], policy: CompliancePolicyDb,
        identity: Optional[RunIdentity] = None,
    ):
        """Workspace client for a run, or None when the rule doesn't need one.

        Rules whose MATCH covers Unity Catalog types (including ``Object``,
        which covers every type) need the client: without it the run fails
        instead of passing after evaluating only part of its scope. Rules on
        app entities alone run without it. The client is the identity's: the
        user's own for a run they start, the app's for a scheduled run.
        """
        from src.common.compliance_entities import UnityCatalogLoader

        identity = identity or RunIdentity.app()
        needs_uc = any(t in UnityCatalogLoader.SUPPORTED_TYPES for t in entity_types)
        if not needs_uc:
            # Only the Unity Catalog loader uses the client. Building one a run on
            # app entities doesn't use waits on the SDK's retries (5 minutes)
            # where no workspace answers
            return None
        try:
            ws = identity.workspace_client()
        except Exception as e:
            # A code the UI translates; the exception text stays in the
            # stored message and the log, not in what the UI shows
            code = ('user_token_required' if isinstance(e, UserTokenRequiredError)
                    else 'workspace_client_unavailable')
            e.error_code, e.error_params = code, {}
            raise
        if ws is None:
            error = RuntimeError(
                "Databricks workspace client unavailable; this rule matches Unity Catalog "
                "objects and cannot be evaluated without it"
            )
            error.error_code, error.error_params = 'workspace_client_unavailable', {}
            raise error
        return ws

    @staticmethod
    def _flush_notifications(
        db: Session, notifier: 'ComplianceRunNotifier', policy, *, failed: int, passed: int,
    ) -> bool:
        """Send the run's NOTIFY notifications. A failure is logged, doesn't fail the run,
        and returns False so the run carries the ``notifications_failed`` warning."""
        try:
            with db.begin_nested():
                notifier.flush(failed=failed, passed=passed)
            return True
        except Exception:
            logger.exception(
                "Could not create the NOTIFY notifications of policy '%s' (%s)", policy.name, policy.id,
            )
            return False

    def _table_enrichment_for(
        self, parsed_rule: Dict, entity_types: List[str], ws,
        statement_cache: Optional[StatementCache] = None,
    ) -> Optional[TableEnrichment]:
        """Tags / lineage / key columns to load for a run, or None when the rule reads none.

        Tags and lineage come from system tables through the SQL warehouse, the
        key columns from one ``tables.get`` per table (``tables.list`` has no
        constraints). They are read only for rules on tables or views that use
        them, and only for the tables selected by the parts of the rule's WHERE
        that don't read them.
        """
        if ws is None or not any(t in ('table', 'view') for t in entity_types):
            return None
        where = parsed_rule.get('where_clause')
        groups = groups_for_fields(fields_read(where, parsed_rule.get('assert_clause')))
        if not groups:
            return None
        try:
            from src.common.config import get_settings
            warehouse_id = (get_settings().DATABRICKS_WAREHOUSE_ID or '').strip()
        except Exception:
            logger.warning("Settings unavailable; no SQL warehouse for tags and lineage")
            warehouse_id = ''
        runner = None
        if warehouse_id:
            cache = statement_cache or StatementCache()
            runner = cache.runner(WarehouseSqlRunner(ws, warehouse_id))
        # Key columns are read per table with tables.get (tables.list has no constraints)
        table_reader = TableConstraintsReader(ws) if KEYS in groups else None
        return TableEnrichment(
            groups=groups, runner=runner, scope=conditions_without(where, FIELD_GROUP),
            table_reader=table_reader,
        )

    def run_policy_inline(
        self, 
        db: Session, 
        *, 
        policy: CompliancePolicyDb, 
        limit: Optional[int] = None,
        current_user: Optional[str] = None,
        run_identity: Optional[RunIdentity] = None,
        statement_cache: Optional[StatementCache] = None,
        llm_checker: Optional[LlmChecker] = None,
        quota_user: Optional[str] = None,
    ) -> ComplianceRunDb:
        """Run a compliance policy with enhanced DSL support.

        This method supports both the old simple DSL syntax and the new enhanced syntax
        with MATCH, WHERE, ASSERT, ON_PASS, and ON_FAIL clauses.

        ``run_identity``: whose permissions Unity Catalog is read with (the
        tables listed, their tags and lineage). Required with ``current_user``:
        a run a user starts passes theirs (``ValueError`` without it). Without a
        user, the default is the app's, for scheduled runs.

        ``statement_cache``: the warehouse statements (tags, lineage), shared by
        the policies of one job run; each policy run gets its own statement count
        and deadline (``StatementCache.start_run``). A new one by default.

        ``quota_user``: the user who started the run, whose daily LLM_CHECK calls
        it counts against; None for scheduled runs (per-run budget only).
        """
        if run_identity is None and current_user:
            # A run a user starts reads as the user; the app's identity is for
            # scheduled runs, and is never taken by omission
            raise ValueError("a run started by a user needs their RunIdentity")
        if statement_cache is not None:
            # A job's policies share the cached rows, not the count or the deadline
            statement_cache.start_run()
        run = self.create_run(db, policy_id=policy.id)
        success = 0
        failure = 0
        # Entities not evaluated because a field the rule reads could not be loaded
        not_evaluated = 0
        unavailable_sources: Dict[str, str] = {}
        skipped = 0  # not evaluated: an LLM_CHECK without a verdict
        # Tag actions (ASSIGN_TAG / REMOVE_TAG) need a tag manager in the context;
        # NOTIFY collects per recipient and sends one notification when the run ends
        tag_manager = TagsManagerTagAdapter(db, user_email=current_user)
        notifier = ComplianceRunNotifier(
            db, policy_id=policy.id, policy_name=policy.name, run_id=run.id, run_user=current_user,
        )
        # LLM_CHECK calls: one budget for this run (or the job run that passes
        # its checker), verdicts cached across runs
        if llm_checker is None:
            llm_checker = self.llm_checker(db, purge_expired=True, quota_user=quota_user)
        budget_exceeded_before = llm_checker.budget_exceeded
        quota_exceeded_before = llm_checker.quota_exceeded
        calls_before, hits_before = llm_checker.calls, llm_checker.cache_hits

        def llm_usage() -> dict:
            # This run's share, also when a job run passes one checker to every policy run
            return {
                'llm_calls': llm_checker.calls - calls_before,
                'llm_cache_hits': llm_checker.cache_hits - hits_before,
                'not_evaluated_count': skipped + not_evaluated,
            }

        try:
            # Parse the rule using enhanced DSL
            parsed_rule = parse_rule(policy.rule, source=f"policy '{policy.name}' ({policy.id})")
            refused = llm_check_tag_actions(parsed_rule)
            if refused:
                # Also refused on save and in the YAML load; a rule stored another way
                # (an older save, the database) fails here before any entity is read,
                # so a model's verdict writes no tag
                from src.common.compliance_errors import ComplianceRunError
                raise ComplianceRunError(
                    f"A rule with LLM_CHECK can't use {', '.join(refused)}",
                    'llm_check_tag_action', actions=', '.join(refused),
                )

            # Parse entity filter
            entity_filter = parse_entity_filter(policy.rule, parsed=parsed_rule)

            # Create entity iterator
            ws = self._workspace_client_for(entity_filter.entity_types, policy, run_identity)
            entity_iterator = create_entity_iterator(
                db=db, workspace_client=ws,
                table_enrichment=self._table_enrichment_for(
                    parsed_rule, entity_filter.entity_types, ws, statement_cache,
                ),
            )
            rule_fields = fields_read(
                parsed_rule.get('where_clause'), parsed_rule.get('assert_clause'),
            )

            # Iterate over entities
            for obj in entity_iterator.iterate(
                entity_filter, limit=limit, source=f"policy '{policy.name}' ({policy.id})",
            ):
                # Evaluate ASSERT clause
                ok = True
                msg = None
                details = None
                missing = unavailable_fields_read(obj, rule_fields)
                no_verdict = llm_not_evaluated = False
                evaluator = Evaluator(obj, llm_checker=llm_checker)

                if missing:
                    # Neither pass nor a real failure: the result says which
                    # source is missing, and no ON_PASS / ON_FAIL action runs
                    ok = False
                    fields = ', '.join(sorted(missing))
                    sources = ', '.join(sorted({m['source'] for m in missing.values()}))
                    reasons = ', '.join(sorted({m['reason'] for m in missing.values()}))
                    for m in missing.values():
                        unavailable_sources[m['source']] = m['reason']
                    not_evaluated += 1
                    msg = (f"Not evaluated: {fields} could not be read from {sources} "
                           f"({reasons})")
                    details = json.dumps({
                        'code': NOT_EVALUATED_CODE,
                        'params': {'fields': fields, 'sources': sources, 'reason': reasons},
                    })
                elif parsed_rule.get('assert_clause'):
                    try:
                        result = evaluator.evaluate(parsed_rule['assert_clause'])
                        ok = bool(result)
                        if not ok:
                            msg = f"Assertion failed for {obj.get('type')} {obj.get('name')}"
                    except LlmCheckError as e:
                        # Failed closed without a model verdict (no endpoint,
                        # budget, refusal...): the entity doesn't pass, its actions
                        # don't run, and unless the text was empty it is not evaluated
                        # (left out of the counts and the score)
                        ok, no_verdict = False, True
                        llm_not_evaluated = not counts_as_failure(e.code)
                        msg = f"Evaluation error: {str(e)}"
                    except Exception as e:
                        ok = False
                        msg = f"Evaluation error: {str(e)}"

                # Execute actions
                actions = [] if missing or no_verdict else parsed_rule.get(
                    'on_pass_actions' if ok else 'on_fail_actions', [],
                )
                action_outcomes = None
                if actions:
                    action_context = ActionContext(
                        entity=obj,
                        entity_type=obj.get('type', 'object'),
                        entity_id=obj.get('id') or obj.get('full_name') or obj.get('name') or 'unknown',
                        rule_id=policy.id,
                        rule_name=policy.name,
                        passed=ok,
                        message=msg,
                        tag_manager=tag_manager,
                        notification_manager=notifier,
                    )
                    action_results = self.action_executor.execute_actions(actions, action_context)
                    action_outcomes = _action_outcomes(action_results)

                    # Use the FAIL action messages, in order, if present
                    fail_messages = [
                        ar.message for ar in action_results
                        if ar.action_type == 'FAIL' and ar.message
                    ]
                    if fail_messages:
                        msg = "; ".join(fail_messages)
                if not missing:
                    # The actions' outcomes, and the outcome of each LLM_CHECK: the model's
                    # reason, or the code of why there is no verdict (the UI shows them by
                    # the message). Actions run only on evaluated entities, so this never
                    # replaces the not-evaluated details above
                    details = _result_details(action_outcomes, evaluator.llm_checks)

                # Store result
                res = ComplianceResultDb(
                    id=str(uuid.uuid4()),
                    run_id=run.id,
                    object_type=obj.get('type') or 'object',
                    object_id=obj.get('id') or obj.get('full_name') or obj.get('name') or 'unknown',
                    object_name=obj.get('name'),
                    passed=bool(ok),
                    not_evaluated=bool(missing) or llm_not_evaluated,
                    message=msg,
                    details_json=details,
                )
                db.add(res)

                if llm_not_evaluated:
                    skipped += 1
                elif ok:
                    success += 1
                elif not missing:
                    # Not evaluated is neither: out of the counts and the score
                    failure += 1

            notified = self._flush_notifications(db, notifier, policy, failed=failure, passed=success)

            # No score without an evaluated entity (all not evaluated, or none matched)
            evaluated = success + failure
            score = round(100.0 * (success / evaluated), 2) if evaluated else None
            # A stored rule with trailing input keeps running with its tail ignored;
            # the run says so, so the policies that need a fix can be found.
            trailing = parsed_rule.get('trailing_input')
            # One warning per run: the rule's tail is what to fix first, then the
            # entities that failed because the run reached its LLM_CHECK budget, then
            # those past the user's daily quota, then the entities whose fields could
            # not be read, then a failed notification flush
            warning_code, warning_params = None, None
            if trailing:
                warning_code, warning_params = 'rule_trailing_input', trailing
            elif llm_checker.budget_exceeded > budget_exceeded_before:
                warning_code, warning_params = BUDGET_EXCEEDED, {
                    'count': llm_checker.budget_exceeded - budget_exceeded_before,
                    'budget': llm_checker.max_calls,
                }
            elif llm_checker.quota_exceeded > quota_exceeded_before:
                warning_code, warning_params = QUOTA_EXCEEDED, {
                    'count': llm_checker.quota_exceeded - quota_exceeded_before,
                    'limit': llm_checker.quota.limit,
                }
            elif not_evaluated:
                # Not in the counts or the score; the warning says how many and which source
                warning_code = 'rule_fields_unavailable'
                warning_params = {
                    'count': not_evaluated,
                    'sources': ', '.join(sorted(unavailable_sources)),
                    'reasons': ', '.join(sorted(set(unavailable_sources.values()))),
                }
            elif not notified:
                warning_code, warning_params = 'notifications_failed', {}
            elif success + failure + skipped == 0:
                # Not a failure: the rule ran but selected nothing (#1150).
                # The warning says why the run has no results. An LLM_CHECK
                # without a verdict (skipped) means an entity was selected.
                warning_code = 'no_entities_matched'
            self.complete_run(
                db, run, success_count=success, failure_count=failure, score=score,
                warning_code=warning_code, warning_params=warning_params, **llm_usage(),
            )
            
            # Log to change log for timeline
            try:
                from src.controller.change_log_manager import change_log_manager
                change_log_manager.log_change_with_details(
                    db,
                    entity_type='compliance_policy',
                    entity_id=policy.id,
                    action='RUN',
                    username=current_user,
                    details={"run_id": run.id, "status": run.status, "score": run.score}
                )
            except Exception as log_err:
                logger.warning(f"Failed to log change for policy run: {log_err}")
            
            return run

        except Exception as e:
            logger.exception("Compliance inline run failed")
            # The entities evaluated before the error stored NOTIFY as done; send those.
            self._flush_notifications(db, notifier, policy, failed=failure, passed=success)
            from src.common.compliance_errors import public_run_error, run_error_code
            error_code, error_params = run_error_code(e)
            self.complete_run(
                db, run, success_count=success, failure_count=failure, score=None,
                error_message=str(e), error_code=error_code, error_params=error_params,
                **llm_usage(),
            )
            
            # Log failed run to change log
            try:
                from src.controller.change_log_manager import change_log_manager
                change_log_manager.log_change_with_details(
                    db,
                    entity_type='compliance_policy',
                    entity_id=policy.id,
                    action='RUN',
                    username=current_user,
                    # The code, not the exception text: the timeline has other readers
                    details={
                        "run_id": run.id, "status": run.status, "score": run.score,
                        "error_code": public_run_error(run.status, error_code, None)[0],
                    }
                )
            except Exception as log_err:
                logger.warning(f"Failed to log change for failed policy run: {log_err}")
            
            return run

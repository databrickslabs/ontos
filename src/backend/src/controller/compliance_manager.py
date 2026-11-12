from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import json
import uuid
import yaml
from sqlalchemy.orm import Session

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
from src.common.api_errors import CodedValueError
from src.common.compliance_llm_check import (
    BUDGET_EXCEEDED, DbLlmCheckCache, LlmCheckError, LlmChecker,
)
from src.common.compliance_entities import (
    create_entity_iterator,
    parse_entity_filter,
    EntityFilter,
)


logger = get_logger(__name__)


TAG_ACTIONS = ('ASSIGN_TAG', 'REMOVE_TAG')
# Rule test (test_rule_on_sample): entities scanned for the named one, and model calls
SAMPLE_SCAN_LIMIT = 500
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


class ComplianceManager:
    def __init__(self):
        # Stateless; uses DB via repositories
        self.action_executor = ActionExecutor(get_action_registry())

    # --- Policy CRUD ---
    def load_from_yaml(self, db: Session, yaml_path: str) -> None:
        with open(yaml_path) as f:
            data = yaml.safe_load(f) or []
            for raw in data:
                model = CompliancePolicy(**{k: v for k, v in raw.items() if k not in {'examples', 'sample_runs'}})
                # Upsert by id
                existing = db.get(CompliancePolicyDb, str(model.id))
                if existing:
                    existing.name = model.name
                    existing.description = model.description
                    existing.rule = model.rule
                    existing.category = model.category
                    existing.severity = model.severity
                    existing.is_active = model.is_active
                    existing.updated_at = datetime.utcnow()
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
                                    return datetime.fromisoformat(val.replace('Z', '+00:00'))
                                except Exception:
                                    return datetime.utcnow()
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
                                started_at=_parse_dt(rdef.get('started_at')) or datetime.utcnow(),
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
        existing.updated_at = datetime.utcnow()
        
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
        
        db.delete(existing)
        db.commit()
        return True

    # --- Stats ---
    def get_compliance_stats(self, db: Session) -> Dict[str, float]:
        policies = self.list_policies(db)
        # Use latest run score per policy
        scores: List[float] = []
        critical_issues = 0
        for p in policies:
            runs = compliance_run_repo.list_for_policy(db, policy_id=p.id, limit=1)
            score = runs[0].score if runs else 0.0
            scores.append(score)
            if (p.severity or '').lower() == 'critical' and score < 70:
                critical_issues += 1
        overall = sum(scores) / len(scores) if scores else 0.0
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
            runs = compliance_run_repo.list_for_policy(db, policy_id=r.id, limit=1)
            compliance_score = runs[0].score if runs else 0.0
            
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

    def get_compliance_trend(self, db: Session, days: int = 30) -> List[Dict[str, float]]:
        end = datetime.utcnow().date()
        start = end - timedelta(days=days - 1)
        # Gather runs within the window
        runs = db.query(ComplianceRunDb).all()
        by_date: Dict[str, List[float]] = {}
        for r in runs:
            if not r.started_at:
                continue
            d = r.started_at.date()
            if d < start or d > end:
                continue
            key = d.isoformat()
            by_date.setdefault(key, []).append(float(r.score or 0.0))
        # Construct time series, filling missing days with previous or 0
        trend: List[Dict[str, float]] = []
        for i in range(days - 1, -1, -1):
            d = (end - timedelta(days=i)).isoformat()
            vals = by_date.get(d, [])
            if vals:
                avg = sum(vals) / len(vals)
            else:
                avg = 0.0
            trend.append({"date": d, "compliance": round(avg, 2)})
        return trend

    # --- Runs ---
    def create_run(self, db: Session, *, policy_id: str) -> ComplianceRunDb:
        run = ComplianceRunDb(
            id=str(uuid.uuid4()),
            policy_id=policy_id,
            status='running',
            started_at=datetime.utcnow(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def complete_run(
        self, db: Session, run: ComplianceRunDb, *, success_count: int, failure_count: int,
        score: float, error_message: Optional[str] = None, error_code: Optional[str] = None,
        error_params: Optional[dict] = None, warning_code: Optional[str] = None,
        warning_params: Optional[dict] = None,
    ) -> ComplianceRunDb:
        run.success_count = success_count
        run.failure_count = failure_count
        run.score = score
        run.finished_at = datetime.utcnow()
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

    def list_results(self, db: Session, *, run_id: str, only_failed: bool = False, limit: int = 1000) -> List[ComplianceResultDb]:
        return compliance_result_repo.list_for_run(db, run_id=run_id, only_failed=only_failed, limit=limit)

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
    def _llm_checker(db: Session, max_calls: Optional[int] = None) -> LlmChecker:
        """The LLM_CHECK runner of one run: the configured endpoint and budget, the DB cache."""
        from src.common.config import get_settings

        try:
            settings = get_settings()
        except RuntimeError:
            # Not initialized: LLM_CHECK then fails closed (llm_check_disabled)
            settings = None
        return LlmChecker(settings, cache=DbLlmCheckCache(db), max_calls=max_calls)

    def test_rule_on_sample(
        self, db: Session, *, rule: str, entity: Optional[str] = None,
    ) -> LlmCheckTestResponse:
        """Evaluate a rule's ASSERT on one entity it matches, LLM_CHECKs included.

        For trying a criterion in the rule editor before the rule is saved: no
        run, result or action is written, only the verdicts to the cache. The
        entity is the one named ``entity`` (name, id or full name) among the
        first ``SAMPLE_SCAN_LIMIT`` the rule matches, else the first match.

        Raises:
            ValueError: the rule doesn't parse.
            SampleEntityNotFoundError: no entity matches.
        """
        from types import SimpleNamespace

        parsed = parse_rule(rule)
        entity_filter = parse_entity_filter(rule, parsed=parsed)
        source = SimpleNamespace(name='rule test', id='unsaved')
        ws = self._workspace_client_for(entity_filter.entity_types, source)
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

        evaluator = Evaluator(sample, llm_checker=self._llm_checker(db, max_calls=TEST_MAX_CALLS))
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

    def _workspace_client_for(self, entity_types: List[str], policy: CompliancePolicyDb):
        """Workspace client for a run, or None when the rule doesn't need one.

        Rules whose MATCH covers Unity Catalog types (including ``Object``,
        which covers every type) need the client: without it the run fails
        instead of passing after evaluating only part of its scope. Rules on
        app entities alone run without it.
        """
        from src.common.compliance_entities import UnityCatalogLoader
        from src.common.workspace_client import get_workspace_client

        needs_uc = any(t in UnityCatalogLoader.SUPPORTED_TYPES for t in entity_types)
        try:
            ws = get_workspace_client()
        except Exception as e:
            if needs_uc:
                # A code the UI translates; the exception text stays in the
                # stored message and the log, not in what the UI shows
                e.error_code, e.error_params = 'workspace_client_unavailable', {}
                raise
            logger.warning(
                "Workspace client unavailable, policy '%s' (%s) only matches app entities "
                "and runs without it: %s", policy.name, policy.id, e,
            )
            return None
        if ws is None and needs_uc:
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

    def run_policy_inline(
        self, 
        db: Session, 
        *, 
        policy: CompliancePolicyDb, 
        limit: Optional[int] = None,
        current_user: Optional[str] = None,
    ) -> ComplianceRunDb:
        """Run a compliance policy with enhanced DSL support.

        This method supports both the old simple DSL syntax and the new enhanced syntax
        with MATCH, WHERE, ASSERT, ON_PASS, and ON_FAIL clauses.
        """
        run = self.create_run(db, policy_id=policy.id)
        success = 0
        failure = 0
        # Tag actions (ASSIGN_TAG / REMOVE_TAG) need a tag manager in the context;
        # NOTIFY collects per recipient and sends one notification when the run ends
        tag_manager = TagsManagerTagAdapter(db, user_email=current_user)
        notifier = ComplianceRunNotifier(
            db, policy_id=policy.id, policy_name=policy.name, run_id=run.id, run_user=current_user,
        )
        # LLM_CHECK calls of this run: one budget, verdicts cached across runs
        llm_checker = self._llm_checker(db)

        try:
            # Parse the rule using enhanced DSL
            parsed_rule = parse_rule(policy.rule, source=f"policy '{policy.name}' ({policy.id})")

            # Parse entity filter
            entity_filter = parse_entity_filter(policy.rule, parsed=parsed_rule)

            # Create entity iterator
            ws = self._workspace_client_for(entity_filter.entity_types, policy)
            entity_iterator = create_entity_iterator(db=db, workspace_client=ws)

            # Iterate over entities
            for obj in entity_iterator.iterate(
                entity_filter, limit=limit, source=f"policy '{policy.name}' ({policy.id})",
            ):
                # Evaluate ASSERT clause
                ok = True
                msg = None
                evaluator = Evaluator(obj, llm_checker=llm_checker)

                if parsed_rule.get('assert_clause'):
                    try:
                        result = evaluator.evaluate(parsed_rule['assert_clause'])
                        ok = bool(result)
                        if not ok:
                            msg = f"Assertion failed for {obj.get('type')} {obj.get('name')}"
                    except Exception as e:
                        ok = False
                        msg = f"Evaluation error: {str(e)}"

                # Execute actions
                actions = parsed_rule.get('on_pass_actions' if ok else 'on_fail_actions', [])
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

                # Store result
                res = ComplianceResultDb(
                    id=str(uuid.uuid4()),
                    run_id=run.id,
                    object_type=obj.get('type') or 'object',
                    object_id=obj.get('id') or obj.get('full_name') or obj.get('name') or 'unknown',
                    object_name=obj.get('name'),
                    passed=bool(ok),
                    message=msg,
                    # The actions' outcomes, and the outcome of each LLM_CHECK: the model's
                    # reason, or the code of why there is no verdict (the UI shows them by
                    # the message)
                    details_json=_result_details(action_outcomes, evaluator.llm_checks),
                )
                db.add(res)

                if ok:
                    success += 1
                else:
                    failure += 1

            notified = self._flush_notifications(db, notifier, policy, failed=failure, passed=success)

            total = max(1, success + failure)
            score = round(100.0 * (success / total), 2)
            # A stored rule with trailing input keeps running with its tail ignored;
            # the run says so, so the policies that need a fix can be found. A failed
            # notification flush is the other warning (the tail is what to fix first).
            trailing = parsed_rule.get('trailing_input')
            warning_code, warning_params = None, None
            if trailing:
                warning_code, warning_params = 'rule_trailing_input', trailing
            elif not notified:
                warning_code, warning_params = 'notifications_failed', {}
            if llm_checker.budget_exceeded:
                # Takes the place of the other warnings (a trailing-input warning is also
                # reported when the rule is saved): these entities failed without being checked
                warning_code, warning_params = BUDGET_EXCEEDED, {
                    'count': llm_checker.budget_exceeded, 'budget': llm_checker.max_calls,
                }
            self.complete_run(
                db, run, success_count=success, failure_count=failure, score=score,
                warning_code=warning_code, warning_params=warning_params,
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
            from src.common.compliance_errors import run_error_code
            error_code, error_params = run_error_code(e)
            self.complete_run(
                db, run, success_count=success, failure_count=failure, score=0.0,
                error_message=str(e), error_code=error_code, error_params=error_params,
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
                    details={"run_id": run.id, "status": run.status, "score": run.score, "error": str(e)}
                )
            except Exception as log_err:
                logger.warning(f"Failed to log change for failed policy run: {log_err}")
            
            return run

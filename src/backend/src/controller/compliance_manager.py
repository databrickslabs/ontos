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
from ..models.compliance import CompliancePolicy, CompliancePolicyCreate, ComplianceRun, ComplianceResult
from src.common.compliance_dsl import evaluate_rule_on_object as eval_dsl, parse_rule, Evaluator
from src.common.compliance_actions import ActionExecutor, ActionContext, get_action_registry
from src.common.compliance_entities import (
    create_entity_iterator,
    parse_entity_filter,
    EntityFilter,
)


logger = get_logger(__name__)


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

    def complete_run(self, db: Session, run: ComplianceRunDb, *, success_count: int, failure_count: int, score: float, error_message: Optional[str] = None) -> ComplianceRunDb:
        run.success_count = success_count
        run.failure_count = failure_count
        run.score = score
        run.finished_at = datetime.utcnow()
        run.status = 'succeeded' if error_message is None else 'failed'
        run.error_message = error_message
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

        try:
            # Parse the rule using enhanced DSL
            parsed_rule = parse_rule(policy.rule)

            # Create entity iterator
            from src.common.workspace_client import get_workspace_client
            ws = get_workspace_client()
            entity_iterator = create_entity_iterator(db=db, workspace_client=ws)

            # Parse entity filter
            entity_filter = parse_entity_filter(policy.rule)

            # Iterate over entities
            for obj in entity_iterator.iterate(entity_filter, limit=limit):
                # Evaluate ASSERT clause
                ok = True
                msg = None

                if parsed_rule.get('assert_clause'):
                    try:
                        evaluator = Evaluator(obj)
                        result = evaluator.evaluate(parsed_rule['assert_clause'])
                        ok = bool(result)
                        if not ok:
                            msg = f"Assertion failed for {obj.get('type')} {obj.get('name')}"
                    except Exception as e:
                        ok = False
                        msg = f"Evaluation error: {str(e)}"

                # Execute actions
                actions = parsed_rule.get('on_pass_actions' if ok else 'on_fail_actions', [])
                if actions:
                    action_context = ActionContext(
                        entity=obj,
                        entity_type=obj.get('type', 'object'),
                        entity_id=obj.get('id') or obj.get('full_name') or obj.get('name') or 'unknown',
                        rule_id=policy.id,
                        rule_name=policy.name,
                        passed=ok,
                        message=msg,
                    )
                    action_results = self.action_executor.execute_actions(actions, action_context)

                    # Update message from FAIL action if present
                    for ar in action_results:
                        if ar.action_type == 'FAIL' and ar.message:
                            msg = ar.message

                # Store result
                res = ComplianceResultDb(
                    id=str(uuid.uuid4()),
                    run_id=run.id,
                    object_type=obj.get('type') or 'object',
                    object_id=obj.get('id') or obj.get('full_name') or obj.get('name') or 'unknown',
                    object_name=obj.get('name'),
                    passed=bool(ok),
                    message=msg,
                    details_json=None,
                )
                db.add(res)

                if ok:
                    success += 1
                else:
                    failure += 1

            total = max(1, success + failure)
            score = round(100.0 * (success / total), 2)
            self.complete_run(db, run, success_count=success, failure_count=failure, score=score)
            
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
            self.complete_run(db, run, success_count=success, failure_count=failure, score=0.0, error_message=str(e))
            
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

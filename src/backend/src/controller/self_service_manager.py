from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session

from src.db_models.projects import ProjectDb
from src.db_models.compliance import CompliancePolicyDb
from src.common.logging import get_logger
from src.common.api_errors import CodedValueError

logger = get_logger(__name__)


class SandboxLocationNotAllowedError(CodedValueError):
    """A catalog/schema outside the self-service sandbox allowlist.

    ``str()`` is the English message; ``code`` and ``params`` (the refused
    catalog and schema) let the UI show it in the user's language.
    """

    code = 'sandbox_location_not_allowed'

    def __init__(self, catalog: str, schema: str):
        super().__init__(
            f"Location '{catalog}.{schema}' is not allowed by the self-service "
            "sandbox policy",
            catalog=catalog,
            schema=schema,
        )


class SelfServiceManager:
    """Manager for self-service compliance automation and policy evaluation."""
    
    def apply_autofix(
        self,
        obj_type: str,
        obj: Dict[str, Any],
        mapping: Dict[str, Any],
        current_user_email: Optional[str],
        project: Optional[ProjectDb]
    ) -> Dict[str, Any]:
        """Apply autofix rules from compliance mapping to an object.
        
        Automatically adds required tags based on mapping rules:
        - 'from_user': Uses current user's email
        - 'from_project': Uses project name/title/id
        - string value: Uses the literal value
        
        Args:
            obj_type: Type of object (e.g., 'catalog', 'schema', 'table')
            obj: Object dictionary to apply fixes to
            mapping: Compliance mapping dict with autofix rules
            current_user_email: Current user's email (for 'from_user' tags)
            project: Project object (for 'from_project' tags)
            
        Returns:
            Updated object dictionary with applied fixes
        """
        rules = mapping.get(obj_type, {}) if isinstance(mapping, dict) else {}
        required_tags = rules.get('required_tags', {}) if isinstance(rules, dict) else {}
        
        if not required_tags:
            return obj
            
        tags = dict(obj.get('tags') or {})
        
        for key, val in required_tags.items():
            if val == 'from_user' and current_user_email:
                tags.setdefault(key, current_user_email)
            elif val == 'from_project' and project is not None:
                tags.setdefault(key, getattr(project, 'name', None) or getattr(project, 'title', None) or project.id)
            elif isinstance(val, str):
                tags.setdefault(key, val)
                
        if tags:
            obj['tags'] = tags
            
        return obj

    def evaluate_policies(
        self,
        db: Session,
        obj: Dict[str, Any],
        policy_ids_or_slugs: List[str]
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """Evaluate a list of compliance policies against an object.
        
        Looks up policies by ID, slug, or name and evaluates their rules against
        the provided object using the compliance DSL.
        
        Args:
            db: Database session
            obj: Object dictionary to evaluate
            policy_ids_or_slugs: List of policy identifiers (ID, slug, or name)
            
        Returns:
            Tuple of (all_passed: bool, results: List[Dict]) where results contains
            evaluation details for each policy
        """
        from src.common.compliance_dsl import evaluate_rule_on_object
        
        results: List[Dict[str, Any]] = []
        all_passed = True

        # Map input identifiers to policies (try id first, then slug, then name)
        for pid in policy_ids_or_slugs:
            policy: Optional[CompliancePolicyDb] = None
            if not pid:
                continue
                
            # Try by primary key id
            policy = db.get(CompliancePolicyDb, pid)
            if policy is None:
                # Try by slug or name
                try:
                    q = db.query(CompliancePolicyDb).filter(
                        (CompliancePolicyDb.slug == pid) | (CompliancePolicyDb.name == pid)
                    )
                    policy = q.first()
                except Exception as e:
                    logger.warning(f"Error querying policy {pid}: {e}")
                    policy = None
                    
            if policy is None:
                results.append({
                    "policy": pid,
                    "passed": False,
                    "message": "Policy not found"
                })
                all_passed = False
                continue

            passed, message = evaluate_rule_on_object(policy.rule, obj)
            results.append({
                "policy": policy.slug or policy.id,
                "name": policy.name,
                "passed": bool(passed),
                "message": message
            })
            all_passed = all_passed and bool(passed)

        return all_passed, results


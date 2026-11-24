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


# The object types of the compliance mapping (compliance_mapping.yaml), whose
# ``policies`` self-service creation evaluates
MAPPING_OBJECT_TYPES = ('catalog', 'schema', 'table')


class MappingPolicyUsesLlmCheckError(CodedValueError):
    """A compliance mapping that names a policy with LLM_CHECK (refused on save)."""

    code = 'compliance_mapping_policy_uses_llm_check'


def load_compliance_mapping() -> Dict[str, Any]:
    """The compliance mapping (compliance_mapping.yaml), or {} when there is none."""
    try:
        from src.common.config import get_config_manager

        return get_config_manager().load_yaml('compliance_mapping.yaml') or {}
    except Exception:
        return {}


def mapping_policy_refs(mapping: Any) -> Dict[str, List[str]]:
    """The policy ids, slugs or names the mapping lists, per object type."""
    refs: Dict[str, List[str]] = {}
    if not isinstance(mapping, dict):
        return refs
    for obj_type in MAPPING_OBJECT_TYPES:
        section = mapping.get(obj_type)
        policies = section.get('policies') if isinstance(section, dict) else None
        if isinstance(policies, list):
            refs[obj_type] = [str(p) for p in policies if p]
    return refs


def find_mapped_policy(db: Session, ref: str) -> Optional[CompliancePolicyDb]:
    """The policy a mapping entry names: by id, then by slug or name."""
    policy = db.get(CompliancePolicyDb, ref)
    if policy is not None:
        return policy
    try:
        return db.query(CompliancePolicyDb).filter(
            (CompliancePolicyDb.slug == ref) | (CompliancePolicyDb.name == ref)
        ).first()
    except Exception as e:
        logger.warning(f"Error querying policy {ref}: {e}")
        return None


def refuse_llm_check_in_mapping(db: Session, mapping: Any) -> None:
    """Raise ``MappingPolicyUsesLlmCheckError`` when the mapping names a policy with
    LLM_CHECK: self-service evaluates it without a model, so it would fail, and
    block, every object of that type."""
    from src.controller.compliance_manager import rule_uses_llm_check

    for obj_type, refs in mapping_policy_refs(mapping).items():
        for ref in refs:
            policy = find_mapped_policy(db, ref)
            if policy is not None and rule_uses_llm_check(policy.rule):
                raise MappingPolicyUsesLlmCheckError(
                    f"The {obj_type} policies name '{ref}', which uses LLM_CHECK: it is only "
                    "evaluated in compliance runs, so self-service would refuse every "
                    f"{obj_type}",
                    objectType=obj_type, policy=ref,
                )


def mapping_object_types_of(mapping: Any, policy: CompliancePolicyDb) -> List[str]:
    """The mapping's object types whose policies name ``policy`` (id, slug or name)."""
    names = {str(v) for v in (policy.id, policy.slug, policy.name) if v}
    return [
        obj_type for obj_type, refs in mapping_policy_refs(mapping).items()
        if names.intersection(refs)
    ]


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
                
            policy = find_mapped_policy(db, pid)

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


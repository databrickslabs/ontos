import re
from typing import List, Optional
from src.models.users import UserInfo
from src.models.settings import DeploymentPolicy
from src.controller.authorization_manager import normalize_email, role_matches
from src.controller.settings_manager import SettingsManager
from src.common.logging import get_logger

logger = get_logger(__name__)


class DeploymentPolicyManager:
    """Manages deployment policies for catalog/schema restrictions.
    
    The app service principal has full UC CREATE permissions.
    This manager enforces which catalogs/schemas users can deploy to.
    """
    
    def __init__(self, settings_manager: SettingsManager):
        self.settings_manager = settings_manager
    
    def get_effective_policy(self, user: UserInfo) -> DeploymentPolicy:
        """Get user's effective deployment policy by merging all applicable role policies.
        
        Resolution order:
        1. Check for explicit role override applied to user
        2. Union policies from all roles the user holds (by group or by user)
        3. Resolve template variables ({username}, {email}, etc.)
        4. Return merged policy (most permissive wins)
        """
        
        # 1. Check for explicit role override
        override_role_id = self.settings_manager.get_applied_role_override_for_user(user.email)
        if override_role_id:
            role = self.settings_manager.get_app_role(override_role_id)
            if role and role.deployment_policy:
                logger.debug(f"Using role override deployment policy for {user.email}")
                return self._resolve_policy_templates(role.deployment_policy, user)
        
        # 2. Collect policies from all user's group roles
        policies = []
        # Normalize to lowercase for case-insensitive matching
        user_groups = set(g.lower() for g in (user.groups or []))
        user_email_norm = normalize_email(user.email)
        
        all_roles = self.settings_manager.list_app_roles()
        for role in all_roles:
            # By group or by user assignment (case-insensitive)
            if role_matches(role, user_groups, user_email_norm):
                if role.deployment_policy:
                    policies.append(role.deployment_policy)
                    logger.debug(f"Found deployment policy from role '{role.name}' for user {user.email}")
        
        # 3. Merge policies (union - most permissive wins)
        if not policies:
            logger.warning(f"No deployment policies found for user {user.email}, returning restrictive default")
            # Return restrictive default - no catalogs allowed, requires approval
            return DeploymentPolicy(
                allowed_catalogs=[],
                allowed_schemas=[],
                require_approval=True,
                can_approve_deployments=False
            )
        
        merged = self._merge_policies(policies)
        
        # 4. Resolve template variables
        resolved = self._resolve_policy_templates(merged, user)
        
        logger.info(f"Effective deployment policy for {user.email}: {len(resolved.allowed_catalogs)} allowed catalogs, require_approval={resolved.require_approval}")
        return resolved
    
    def _merge_policies(self, policies: List[DeploymentPolicy]) -> DeploymentPolicy:
        """Merge multiple policies into one (union approach - most permissive wins)."""
        
        if len(policies) == 1:
            return policies[0]
        
        # Union all allowed catalogs and schemas
        all_catalogs = []
        all_schemas = []
        default_catalog = None
        default_schema = None
        
        # Start with most restrictive for booleans
        require_approval = True
        can_approve = False
        
        for policy in policies:
            all_catalogs.extend(policy.allowed_catalogs)
            all_schemas.extend(policy.allowed_schemas)
            
            # Use first non-None default
            if policy.default_catalog and not default_catalog:
                default_catalog = policy.default_catalog
            if policy.default_schema and not default_schema:
                default_schema = policy.default_schema
            
            # Most permissive wins for booleans
            if not policy.require_approval:
                require_approval = False
            if policy.can_approve_deployments:
                can_approve = True
        
        # Remove duplicates
        unique_catalogs = list(set(all_catalogs))
        unique_schemas = list(set(all_schemas)) if all_schemas else []
        
        return DeploymentPolicy(
            allowed_catalogs=unique_catalogs,
            allowed_schemas=unique_schemas,
            default_catalog=default_catalog,
            default_schema=default_schema,
            require_approval=require_approval,
            can_approve_deployments=can_approve
        )
    
    def _resolve_policy_templates(self, policy: DeploymentPolicy, user: UserInfo) -> DeploymentPolicy:
        """Resolve template variables in policy strings.
        
        Supported variables:
        - {username}: Email prefix (jdoe@company.com -> jdoe)
        - {email}: Full email address
        - {team}: Primary team name (future enhancement)
        - {domain}: User's domain (future enhancement)
        """
        
        # Extract username from email
        username = user.email.split('@')[0] if '@' in user.email else user.email
        
        # Build replacement map
        replacements = {
            '{username}': username,
            '{email}': user.email,
            '{team}': 'default_team',  # TODO: Get from user's primary team
            '{domain}': 'default_domain',  # TODO: Get from user's assigned domain
        }
        
        # Resolve catalogs
        resolved_catalogs = [
            self._apply_replacements(cat, replacements)
            for cat in policy.allowed_catalogs
        ]
        
        # Resolve schemas
        resolved_schemas = [
            self._apply_replacements(schema, replacements)
            for schema in policy.allowed_schemas
        ]
        
        # Resolve defaults
        resolved_default_catalog = (
            self._apply_replacements(policy.default_catalog, replacements)
            if policy.default_catalog else None
        )
        resolved_default_schema = (
            self._apply_replacements(policy.default_schema, replacements)
            if policy.default_schema else None
        )
        
        return DeploymentPolicy(
            allowed_catalogs=resolved_catalogs,
            allowed_schemas=resolved_schemas,
            default_catalog=resolved_default_catalog,
            default_schema=resolved_default_schema,
            require_approval=policy.require_approval,
            can_approve_deployments=policy.can_approve_deployments
        )
    
    def _apply_replacements(self, text: str, replacements: dict) -> str:
        """Apply template variable replacements to a string."""
        result = text
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)
        return result
    
    def validate_deployment_target(
        self, 
        policy: DeploymentPolicy, 
        catalog: str, 
        schema: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """Validate if deployment target is allowed by policy.
        
        Returns:
            (is_valid, error_message): Tuple of validation result and error message if invalid
        """
        
        # Empty policy means no access
        if not policy.allowed_catalogs:
            return False, "No deployment catalogs allowed for your role"
        
        # Check catalog access
        catalog_allowed = any(
            self._matches_pattern(catalog, pattern)
            for pattern in policy.allowed_catalogs
        )
        
        if not catalog_allowed:
            allowed_list = ', '.join(policy.allowed_catalogs)
            return False, f"Catalog '{catalog}' not allowed. Allowed catalogs: {allowed_list}"
        
        # Check schema if specified and policy has schema restrictions
        if schema and policy.allowed_schemas:
            schema_allowed = any(
                self._matches_pattern(schema, pattern)
                for pattern in policy.allowed_schemas
            )
            
            if not schema_allowed:
                allowed_list = ', '.join(policy.allowed_schemas)
                return False, f"Schema '{schema}' not allowed. Allowed schemas: {allowed_list}"
        
        return True, None
    
    def _matches_pattern(self, value: str, pattern: str) -> bool:
        """Check if value matches pattern.
        
        Supports:
        - '*' wildcard: matches everything
        - '*' within pattern: 'user_*' matches 'user_jdoe'
        - Regex: '^pattern$' for advanced matching
        - Exact match: 'catalog_name'
        """
        
        if not value or not pattern:
            return False
        
        # Wildcard matches everything
        if pattern == "*":
            return True
        
        # Regex pattern (starts with ^)
        if pattern.startswith("^"):
            try:
                return bool(re.match(pattern, value))
            except re.error as e:
                logger.error(f"Invalid regex pattern '{pattern}': {e}")
                return False
        
        # Wildcard pattern (contains *)
        if "*" in pattern:
            # Convert wildcard to regex
            regex_pattern = pattern.replace(".", r"\.").replace("*", ".*")
            regex_pattern = f"^{regex_pattern}$"
            try:
                return bool(re.match(regex_pattern, value))
            except re.error as e:
                logger.error(f"Error converting wildcard pattern '{pattern}' to regex: {e}")
                return False
        
        # Exact match
        return value == pattern
    
    def can_approve_deployment_to(
        self, 
        approver_policy: DeploymentPolicy, 
        catalog: str, 
        schema: Optional[str] = None
    ) -> bool:
        """Check if approver with given policy can approve deployment to target.
        
        Approver must:
        1. Have can_approve_deployments = True
        2. Have access to the target catalog/schema themselves
        """
        
        if not approver_policy.can_approve_deployments:
            return False
        
        # Approver must have access to the target
        is_valid, _ = self.validate_deployment_target(approver_policy, catalog, schema)
        return is_valid


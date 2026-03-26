from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import json
import uuid
import yaml

from databricks.sdk import WorkspaceClient
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func

from src.common.config import Settings
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.controller.notifications_manager import NotificationsManager
from src.models.notifications import NotificationType, Notification
from src.models.settings import JobCluster, AppRole, AppRoleCreate, AppRoleUpdate, HomeSection, ApprovalEntity
from src.models.workflow_installations import WorkflowInstallation
from src.common.features import get_feature_config, FeatureAccessLevel, get_all_access_levels, APP_FEATURES, ACCESS_LEVEL_ORDER
from src.common.logging import get_logger
from src.repositories.settings_repository import app_role_repo, role_hierarchy_repo
from src.repositories.workflow_installations_repository import workflow_installation_repo
from src.repositories.app_settings_repository import app_settings_repo
from src.db_models.settings import AppRoleDb, NO_ROLE_SENTINEL
from src.repositories.teams_repository import team_repo
from src.repositories.projects_repository import project_repo
from src.db_models.teams import TeamDb, TeamMemberDb
from src.db_models.projects import ProjectDb

logger = get_logger(__name__)

# Define the path for storing roles configuration
# ROLES_YAML_PATH = Path("api/data/app_roles.yaml")
ROLES_YAML_PATH = Path(__file__).parent.parent / 'data' / 'settings.yaml'

# --- Default Role Definitions --- 

# Define default roles structure
DEFAULT_ROLES = [
    {"name": "Admin", "description": "Default role: Admin"},
    {"name": "Data Governance Officer", "description": "Default role: Data Governance Officer"},
    {"name": "Data Steward", "description": "Default role: Data Steward"},
    {"name": "Data Consumer", "description": "Default role: Data Consumer"},
    {"name": "Data Producer", "description": "Default role: Data Producer"},
    {"name": "Security Officer", "description": "Default role: Security Officer"},
]

# Define desired default permissions for non-Admin roles
# These should be validated against allowed_levels in ensure_default_roles_exist
DEFAULT_ROLE_PERMISSIONS = {
    "Data Governance Officer": {
        'data-domains': FeatureAccessLevel.ADMIN,
        'data-products': FeatureAccessLevel.ADMIN,
        'data-contracts': FeatureAccessLevel.ADMIN,
        'data-catalog': FeatureAccessLevel.ADMIN,
        'teams': FeatureAccessLevel.READ_ONLY,
        'projects': FeatureAccessLevel.READ_ONLY,
        'business-glossary': FeatureAccessLevel.ADMIN,
        'compliance': FeatureAccessLevel.ADMIN,
        'process-workflows': FeatureAccessLevel.READ_ONLY,  # View workflows, Admin manages
        'estate-manager': FeatureAccessLevel.ADMIN,
        'master-data': FeatureAccessLevel.ADMIN,
        'security-features': FeatureAccessLevel.ADMIN,
        'entitlements': FeatureAccessLevel.ADMIN,
        'entitlements-sync': FeatureAccessLevel.ADMIN,
        'data-asset-reviews': FeatureAccessLevel.ADMIN,
        'catalog-commander': FeatureAccessLevel.FULL,
        'comments': FeatureAccessLevel.READ_WRITE,  # All users can comment
    },
    "Data Steward": {
        'data-domains': FeatureAccessLevel.READ_WRITE,
        'data-products': FeatureAccessLevel.READ_WRITE,
        'data-contracts': FeatureAccessLevel.READ_WRITE,
        'data-catalog': FeatureAccessLevel.READ_WRITE,
        'teams': FeatureAccessLevel.READ_ONLY,
        'projects': FeatureAccessLevel.READ_ONLY,
        'business-glossary': FeatureAccessLevel.READ_WRITE,
        'compliance': FeatureAccessLevel.READ_ONLY,
        'process-workflows': FeatureAccessLevel.READ_ONLY,  # View workflows, Admin manages
        'data-asset-reviews': FeatureAccessLevel.READ_WRITE,
        'catalog-commander': FeatureAccessLevel.READ_ONLY,
        'comments': FeatureAccessLevel.READ_WRITE,  # All users can comment
    },
    "Data Consumer": {
        'data-domains': FeatureAccessLevel.READ_ONLY,
        'data-products': FeatureAccessLevel.READ_ONLY,
        'data-contracts': FeatureAccessLevel.READ_ONLY,
        'data-catalog': FeatureAccessLevel.READ_ONLY,
        'teams': FeatureAccessLevel.READ_ONLY,
        'projects': FeatureAccessLevel.READ_ONLY,
        'business-glossary': FeatureAccessLevel.READ_ONLY,
        'process-workflows': FeatureAccessLevel.READ_ONLY,  # View workflows, Admin manages
        'catalog-commander': FeatureAccessLevel.READ_ONLY,
        'comments': FeatureAccessLevel.READ_WRITE,  # All users can comment
    },
    "Data Producer": {
        'data-domains': FeatureAccessLevel.READ_ONLY,
        'data-products': FeatureAccessLevel.READ_WRITE,
        'data-contracts': FeatureAccessLevel.READ_WRITE,
        'data-catalog': FeatureAccessLevel.READ_ONLY,
        'teams': FeatureAccessLevel.READ_WRITE,
        'projects': FeatureAccessLevel.READ_WRITE,
        'business-glossary': FeatureAccessLevel.READ_ONLY,
        'process-workflows': FeatureAccessLevel.READ_ONLY,  # View workflows, Admin manages
        'catalog-commander': FeatureAccessLevel.READ_ONLY,
        'comments': FeatureAccessLevel.READ_WRITE,  # All users can comment
    },
    "Security Officer": {
        'security-features': FeatureAccessLevel.ADMIN,
        'entitlements': FeatureAccessLevel.ADMIN,
        'entitlements-sync': FeatureAccessLevel.ADMIN,
        'compliance': FeatureAccessLevel.READ_WRITE,
        'process-workflows': FeatureAccessLevel.READ_ONLY,  # View workflows, Admin manages
        'data-asset-reviews': FeatureAccessLevel.READ_ONLY,
        'comments': FeatureAccessLevel.READ_WRITE,  # All users can comment
    },
}

class SettingsManager:
    def __init__(self, db: Session, settings: Settings, workspace_client: Optional[WorkspaceClient] = None):
        """Inject database session, settings, and optional workspace client."""
        self._db = db
        self._settings = settings # Store settings
        self._client = workspace_client
        # Available jobs derive from workflows on disk
        self._available_jobs: List[str] = []
        self._installations: Dict[str, WorkflowInstallation] = {}
        self.app_role_repo = app_role_repo
        self._notifications_manager: Optional['NotificationsManager'] = None
        # In-memory role overrides: user_email -> role_id
        self._applied_role_overrides: Dict[str, str] = {}
        # Initialize available jobs from workflow directory
        try:
            from src.controller.jobs_manager import JobsManager
            from src.utils.workspace_deployer import WorkspaceDeployer

            # Initialize WorkspaceDeployer if deployment path is configured
            workspace_deployer = None
            if self._client and self._settings.WORKSPACE_DEPLOYMENT_PATH:
                try:
                    workspace_deployer = WorkspaceDeployer(
                        ws_client=self._client,
                        deployment_path=self._settings.WORKSPACE_DEPLOYMENT_PATH
                    )
                    logger.info(f"WorkspaceDeployer initialized with deployment path: {self._settings.WORKSPACE_DEPLOYMENT_PATH}")
                except Exception as e:
                    logger.warning(f"Failed to initialize WorkspaceDeployer: {e}")

            self._jobs = JobsManager(
                db=self._db,
                ws_client=self._client,
                notifications_manager=self._notifications_manager,
                settings=self._settings,
                workspace_deployer=workspace_deployer
            )
            self._available_jobs = [w["id"] for w in self._jobs.list_available_workflows()]

            # Load installations from database
            self._load_installations_from_db()
        except Exception as e:
            logger.error(f"Error initializing JobsManager: {e}")
            self._jobs = None
            self._available_jobs = []
        
        # Load persisted settings from database (overrides env vars)
        self._load_persisted_settings()
        # Reinitialize deployer in case WORKSPACE_DEPLOYMENT_PATH was loaded from DB
        # after the initial JobsManager creation above
        self._reinitialize_workspace_deployer()

    def _load_persisted_settings(self) -> None:
        """Load persisted settings from database and apply to in-memory Settings."""
        try:
            # Load all persisted settings from database
            all_settings = app_settings_repo.get_all(self._db)
            
            # WORKSPACE_DEPLOYMENT_PATH
            if 'WORKSPACE_DEPLOYMENT_PATH' in all_settings and all_settings['WORKSPACE_DEPLOYMENT_PATH'] is not None:
                self._settings.WORKSPACE_DEPLOYMENT_PATH = all_settings['WORKSPACE_DEPLOYMENT_PATH']
                logger.info(f"Loaded WORKSPACE_DEPLOYMENT_PATH from database: {all_settings['WORKSPACE_DEPLOYMENT_PATH']}")
            
            # Databricks Unity Catalog settings
            if 'DATABRICKS_CATALOG' in all_settings and all_settings['DATABRICKS_CATALOG']:
                self._settings.DATABRICKS_CATALOG = all_settings['DATABRICKS_CATALOG']
                logger.info(f"Loaded DATABRICKS_CATALOG from database: {all_settings['DATABRICKS_CATALOG']}")
            
            if 'DATABRICKS_SCHEMA' in all_settings and all_settings['DATABRICKS_SCHEMA']:
                self._settings.DATABRICKS_SCHEMA = all_settings['DATABRICKS_SCHEMA']
                logger.info(f"Loaded DATABRICKS_SCHEMA from database: {all_settings['DATABRICKS_SCHEMA']}")
            
            if 'DATABRICKS_VOLUME' in all_settings and all_settings['DATABRICKS_VOLUME']:
                self._settings.DATABRICKS_VOLUME = all_settings['DATABRICKS_VOLUME']
                logger.info(f"Loaded DATABRICKS_VOLUME from database: {all_settings['DATABRICKS_VOLUME']}")
            
            # Audit log directory
            if 'APP_AUDIT_LOG_DIR' in all_settings and all_settings['APP_AUDIT_LOG_DIR']:
                self._settings.APP_AUDIT_LOG_DIR = all_settings['APP_AUDIT_LOG_DIR']
                logger.info(f"Loaded APP_AUDIT_LOG_DIR from database: {all_settings['APP_AUDIT_LOG_DIR']}")
            
            # LLM settings
            if 'LLM_ENABLED' in all_settings and all_settings['LLM_ENABLED'] is not None:
                self._settings.LLM_ENABLED = all_settings['LLM_ENABLED'].lower() == 'true'
                logger.info(f"Loaded LLM_ENABLED from database: {self._settings.LLM_ENABLED}")
            
            if 'LLM_ENDPOINT' in all_settings and all_settings['LLM_ENDPOINT'] is not None:
                self._settings.LLM_ENDPOINT = all_settings['LLM_ENDPOINT']
                logger.info(f"Loaded LLM_ENDPOINT from database: {all_settings['LLM_ENDPOINT']}")
            
            if 'LLM_SYSTEM_PROMPT' in all_settings and all_settings['LLM_SYSTEM_PROMPT'] is not None:
                self._settings.LLM_SYSTEM_PROMPT = all_settings['LLM_SYSTEM_PROMPT']
                logger.info("Loaded LLM_SYSTEM_PROMPT from database")
            
            if 'LLM_DISCLAIMER_TEXT' in all_settings and all_settings['LLM_DISCLAIMER_TEXT'] is not None:
                self._settings.LLM_DISCLAIMER_TEXT = all_settings['LLM_DISCLAIMER_TEXT']
                logger.info("Loaded LLM_DISCLAIMER_TEXT from database")
            
            # Tag display format setting (stored in DB only, not in Settings model)
            # Valid values: 'short' (default), 'long'
            if 'TAG_DISPLAY_FORMAT' in all_settings and all_settings['TAG_DISPLAY_FORMAT'] is not None:
                logger.info(f"Loaded TAG_DISPLAY_FORMAT from database: {all_settings['TAG_DISPLAY_FORMAT']}")
            
            # Delivery mode settings
            if 'DELIVERY_MODE_DIRECT' in all_settings and all_settings['DELIVERY_MODE_DIRECT'] is not None:
                self._settings.DELIVERY_MODE_DIRECT = all_settings['DELIVERY_MODE_DIRECT'].lower() == 'true'
                logger.info(f"Loaded DELIVERY_MODE_DIRECT from database: {self._settings.DELIVERY_MODE_DIRECT}")
            
            if 'DELIVERY_MODE_INDIRECT' in all_settings and all_settings['DELIVERY_MODE_INDIRECT'] is not None:
                self._settings.DELIVERY_MODE_INDIRECT = all_settings['DELIVERY_MODE_INDIRECT'].lower() == 'true'
                logger.info(f"Loaded DELIVERY_MODE_INDIRECT from database: {self._settings.DELIVERY_MODE_INDIRECT}")
            
            if 'DELIVERY_MODE_MANUAL' in all_settings and all_settings['DELIVERY_MODE_MANUAL'] is not None:
                self._settings.DELIVERY_MODE_MANUAL = all_settings['DELIVERY_MODE_MANUAL'].lower() == 'true'
                logger.info(f"Loaded DELIVERY_MODE_MANUAL from database: {self._settings.DELIVERY_MODE_MANUAL}")
            
            if 'DELIVERY_DIRECT_DRY_RUN' in all_settings and all_settings['DELIVERY_DIRECT_DRY_RUN'] is not None:
                self._settings.DELIVERY_DIRECT_DRY_RUN = all_settings['DELIVERY_DIRECT_DRY_RUN'].lower() == 'true'
                logger.info(f"Loaded DELIVERY_DIRECT_DRY_RUN from database: {self._settings.DELIVERY_DIRECT_DRY_RUN}")
            
            # Git settings for indirect mode
            if 'GIT_REPO_URL' in all_settings and all_settings['GIT_REPO_URL'] is not None:
                self._settings.GIT_REPO_URL = all_settings['GIT_REPO_URL']
                logger.info("Loaded GIT_REPO_URL from database")
            
            if 'GIT_BRANCH' in all_settings and all_settings['GIT_BRANCH'] is not None:
                self._settings.GIT_BRANCH = all_settings['GIT_BRANCH']
                logger.info(f"Loaded GIT_BRANCH from database: {all_settings['GIT_BRANCH']}")
            
            if 'GIT_USERNAME' in all_settings and all_settings['GIT_USERNAME'] is not None:
                self._settings.GIT_USERNAME = all_settings['GIT_USERNAME']
                logger.info("Loaded GIT_USERNAME from database")
            
            if 'GIT_PASSWORD' in all_settings and all_settings['GIT_PASSWORD'] is not None:
                self._settings.GIT_PASSWORD = all_settings['GIT_PASSWORD']
                logger.info("Loaded GIT_PASSWORD from database (masked)")
            
            # UI Customization settings
            if 'UI_I18N_ENABLED' in all_settings and all_settings['UI_I18N_ENABLED'] is not None:
                self._settings.UI_I18N_ENABLED = all_settings['UI_I18N_ENABLED'].lower() == 'true'
                logger.info(f"Loaded UI_I18N_ENABLED from database: {self._settings.UI_I18N_ENABLED}")
            
            if 'UI_CUSTOM_LOGO_URL' in all_settings and all_settings['UI_CUSTOM_LOGO_URL'] is not None:
                self._settings.UI_CUSTOM_LOGO_URL = all_settings['UI_CUSTOM_LOGO_URL']
                logger.info("Loaded UI_CUSTOM_LOGO_URL from database")
            
            if 'UI_ABOUT_CONTENT' in all_settings and all_settings['UI_ABOUT_CONTENT'] is not None:
                self._settings.UI_ABOUT_CONTENT = all_settings['UI_ABOUT_CONTENT']
                logger.info("Loaded UI_ABOUT_CONTENT from database")
            
            if 'UI_CUSTOM_CSS' in all_settings and all_settings['UI_CUSTOM_CSS'] is not None:
                self._settings.UI_CUSTOM_CSS = all_settings['UI_CUSTOM_CSS']
                logger.info("Loaded UI_CUSTOM_CSS from database")

            # Connector configurations are now managed via the `connections`
            # table and loaded by ConnectionsManager at startup.

        except Exception as e:
            logger.warning(f"Failed to load persisted settings from database: {e}")

    # --- Role override helpers (in-memory persistence) ---
    def set_applied_role_override_for_user(self, user_email: Optional[str], role_id: Optional[str]) -> None:
        """Sets or clears the applied role override for a user.

        When role_id is None, the override is cleared and the user's actual group-based
        permissions are used. This stores state in-memory for the backend process lifetime.
        """
        if not user_email:
            raise ValueError("User email is required to set role override")
        if role_id is None:
            self._applied_role_overrides.pop(user_email, None)
            return
        role = self.get_app_role(role_id)
        if not role:
            raise ValueError(f"Role with id '{role_id}' not found")
        self._applied_role_overrides[user_email] = role_id

    def get_applied_role_override_for_user(self, user_email: Optional[str]) -> Optional[str]:
        if not user_email:
            return None
        return self._applied_role_overrides.get(user_email)

    def get_role_override_name_for_user(self, user_email: Optional[str]) -> Optional[str]:
        """Get the role name for a user's applied role override (impersonation).
        
        This combines getting the applied override ID and resolving it to a role name,
        which is needed for authorization checks that expect role names.
        
        Args:
            user_email: User's email address
            
        Returns:
            Role name if user has an active override, None otherwise
        """
        try:
            applied_override_id = self.get_applied_role_override_for_user(user_email)
            if not applied_override_id:
                return None
                
            role = self.get_app_role(applied_override_id)
            return role.name if role else None
        except Exception as e:
            logger.warning(f"Error resolving role override for user {user_email}: {e}")
            return None

    def get_feature_permissions_for_role_id(self, role_id: str) -> Dict[str, FeatureAccessLevel]:
        role = self.get_app_role(role_id)
        if not role:
            raise ValueError(f"Role with id '{role_id}' not found")
        return role.feature_permissions or {}

    def get_canonical_role_for_groups(self, user_groups: Optional[List[str]]) -> Optional[AppRole]:
        """Map a user's groups to the closest configured AppRole.

        Algorithm:
        1) Try direct match via assigned_groups intersection (pick highest-weight role).
        2) If no matches, compute effective permissions from groups and choose the role
           whose permissions are closest (minimum sum of absolute level differences per feature).
        3) Heuristic: if any group contains 'admin' (case-insensitive), prefer Admin role by name.
        """
        if not user_groups:
            return None

        roles = self.list_app_roles()
        user_group_set = set(user_groups)

        # 3) Admin heuristic first for better UX in local dev
        try:
            if any('admin' in g.lower() for g in user_group_set):
                admin = next((r for r in roles if (r.name or '').strip().lower() == 'admin'), None)
                if admin:
                    return admin
        except Exception:
            pass

        # 1) Direct group match
        best_role: Optional[AppRole] = None
        best_weight = -1
        for role in roles:
            try:
                role_groups = set(role.assigned_groups or [])
                if not role_groups.intersection(user_group_set):
                    continue
                weight = sum(ACCESS_LEVEL_ORDER.get(level, 0) for level in (role.feature_permissions or {}).values())
                if weight > best_weight:
                    best_weight = weight
                    best_role = role
            except Exception:
                continue
        if best_role:
            return best_role

        # 2) Distance-based fallback using effective permissions
        try:
            from src.controller.authorization_manager import AuthorizationManager
            auth = AuthorizationManager(self)
            effective = auth.get_user_effective_permissions(list(user_group_set))
            # Normalize feature set
            feature_ids = set(get_feature_config().keys())
            def level_of(perms: Dict[str, FeatureAccessLevel], fid: str) -> int:
                return ACCESS_LEVEL_ORDER.get(perms.get(fid, FeatureAccessLevel.NONE), 0)

            best_role = None
            best_distance = 10**9
            for role in roles:
                role_perms = role.feature_permissions or {}
                # Compute Manhattan distance across features
                distance = 0
                for fid in feature_ids:
                    distance += abs(level_of(role_perms, fid) - level_of(effective, fid))
                if distance < best_distance:
                    best_distance = distance
                    best_role = role
            return best_role
        except Exception:
            return None

    def set_notifications_manager(self, notifications_manager: 'NotificationsManager') -> None:
        self._notifications_manager = notifications_manager

    def _load_installations_from_db(self):
        """Load workflow installations from database into memory."""
        try:
            db_installations = workflow_installation_repo.get_all(self._db)
            for db_inst in db_installations:
                # Deserialize last_job_state from JSON if present
                last_job_state = None
                if db_inst.last_job_state:
                    try:
                        last_job_state = json.loads(db_inst.last_job_state)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in last_job_state for workflow {db_inst.workflow_id}")

                installation = WorkflowInstallation(
                    id=db_inst.id,
                    workflow_id=db_inst.workflow_id,
                    name=db_inst.name,
                    job_id=db_inst.job_id,
                    workspace_id=db_inst.workspace_id,
                    status=db_inst.status,
                    installed_at=db_inst.installed_at,
                    updated_at=db_inst.updated_at
                )
                self._installations[db_inst.workflow_id] = installation

            logger.info(f"Loaded {len(self._installations)} workflow installations from database")
        except Exception as e:
            logger.error(f"Error loading installations from database: {e}")

    def ensure_default_roles_exist(self):
        """Checks if default roles exist and creates them if necessary."""
        try:
            existing_roles_count = self.get_app_roles_count()
            if existing_roles_count > 0:
                logger.info(f"Found {existing_roles_count} existing roles. Skipping default role creation.")
                return

            logger.info("No existing roles found. Creating default roles...")
            
            # Try to load role defaults from YAML; generate file from in-code defaults if missing
            roles_from_yaml: List[Dict[str, Any]] = []
            try:
                if ROLES_YAML_PATH.exists():
                    with open(ROLES_YAML_PATH, 'r') as f:
                        raw = yaml.safe_load(f) or {}
                        if isinstance(raw, dict) and 'roles' in raw and isinstance(raw['roles'], list):
                            roles_from_yaml = raw['roles']
                        elif isinstance(raw, list):
                            roles_from_yaml = raw
                        else:
                            logger.warning(f"Unsupported YAML structure in {ROLES_YAML_PATH}. Expected list or {'roles': [...]}.")
                else:
                    # Build YAML from current in-code defaults on first run
                    logger.info(f"Roles YAML not found at {ROLES_YAML_PATH}. Creating with default roles...")
                    try:
                        ROLES_YAML_PATH.parent.mkdir(parents=True, exist_ok=True)
                        # Start with names/descriptions
                        generated_roles: List[Dict[str, Any]] = []
                        for role_def in DEFAULT_ROLES:
                            name = role_def.get('name')
                            base: Dict[str, Any] = {
                                'name': name,
                                'description': role_def.get('description'),
                            }
                            # Only include non-admin explicit permissions; admin will be expanded at runtime
                            if name != 'Admin':
                                base['feature_permissions'] = {
                                    feat_id: DEFAULT_ROLE_PERMISSIONS.get(name, {}).get(feat_id, FeatureAccessLevel.NONE).value
                                    for feat_id in DEFAULT_ROLE_PERMISSIONS.get(name, {})
                                }
                                # Default home sections per role (mirrors in-code defaults)
                                if name == 'Data Consumer':
                                    base['home_sections'] = [HomeSection.DISCOVERY.value]
                                elif name == 'Data Producer':
                                    base['home_sections'] = [HomeSection.DATA_CURATION.value, HomeSection.DISCOVERY.value]
                                elif name in ("Data Steward", "Security Officer", "Data Governance Officer"):
                                    base['home_sections'] = [HomeSection.REQUIRED_ACTIONS.value, HomeSection.DISCOVERY.value]
                                else:
                                    base['home_sections'] = [HomeSection.DISCOVERY.value]
                                # Default approval privileges per role
                                if name == 'Data Governance Officer':
                                    base['approval_privileges'] = {
                                        'DOMAINS': True,
                                        'CONTRACTS': True,
                                        'PRODUCTS': True,
                                        'BUSINESS_TERMS': True,
                                        'ASSET_REVIEWS': True,
                                    }
                                elif name == 'Data Steward':
                                    base['approval_privileges'] = {
                                        'CONTRACTS': True,
                                        'PRODUCTS': True,
                                        'ASSET_REVIEWS': True,
                                    }
                            generated_roles.append(base)

                        with open(ROLES_YAML_PATH, 'w') as f:
                            yaml.safe_dump({'roles': generated_roles}, f, sort_keys=False)
                        roles_from_yaml = generated_roles
                        logger.info(f"Created default roles YAML at {ROLES_YAML_PATH}")
                    except Exception as gen_e:
                        logger.error(f"Failed creating roles YAML at {ROLES_YAML_PATH}: {gen_e}")
            except Exception as yaml_e:
                logger.error(f"Failed reading roles YAML at {ROLES_YAML_PATH}: {yaml_e}")

            # Parse Admin Groups
            admin_groups = []
            try:
                groups_json = self._settings.APP_ADMIN_DEFAULT_GROUPS # Use self._settings
                if groups_json:
                    admin_groups = json.loads(groups_json)
                    if not isinstance(admin_groups, list):
                        logger.warning(f"APP_ADMIN_DEFAULT_GROUPS ({groups_json}) is not a valid JSON list. Defaulting Admin role to no groups.")
                        admin_groups = []
                else:
                    logger.info("APP_ADMIN_DEFAULT_GROUPS is not set. Defaulting Admin role to no groups.")
            except json.JSONDecodeError:
                logger.warning(f"Could not parse APP_ADMIN_DEFAULT_GROUPS JSON: '{self._settings.APP_ADMIN_DEFAULT_GROUPS}'. Defaulting Admin role to no groups.")
                admin_groups = []
            
            logger.info(f"Using default admin groups for 'Admin' role: {admin_groups}")
            all_features_config = get_feature_config() # Get the full config
            logger.info(f"Found features: {list(all_features_config.keys())}")

            roles_to_apply: List[Dict[str, Any]] = roles_from_yaml if roles_from_yaml else DEFAULT_ROLES

            for role_def in roles_to_apply:
                role_data = role_def.copy()
                role_name = role_data["name"]
                
                if role_name == "Admin":
                    role_data["is_admin"] = True
                    role_data["assigned_groups"] = role_data.get("assigned_groups") or admin_groups
                    # If YAML provided explicit permissions, honor them; otherwise grant Admin to all features
                    provided_perms = role_data.get("feature_permissions") or {}
                    if provided_perms:
                        final_permissions: Dict[str, FeatureAccessLevel] = {}
                        for feat_id, lvl in provided_perms.items():
                            if feat_id not in all_features_config:
                                logger.warning(f"Unknown feature id '{feat_id}' in Admin permissions from YAML; skipping")
                                continue
                            try:
                                lvl_enum = FeatureAccessLevel(lvl)
                            except Exception:
                                logger.warning(f"Invalid access level '{lvl}' for feature '{feat_id}' in Admin YAML; using NONE")
                                lvl_enum = FeatureAccessLevel.NONE
                            allowed_levels = all_features_config[feat_id].get('allowed_levels', [])
                            final_permissions[feat_id] = lvl_enum if lvl_enum in allowed_levels else FeatureAccessLevel.NONE
                        role_data["feature_permissions"] = final_permissions
                    else:
                        role_data["feature_permissions"] = {
                            feat_id: FeatureAccessLevel.ADMIN
                            for feat_id in all_features_config
                        }
                    logger.info(f"Assigning default ADMIN permissions to Admin role for features: {list(all_features_config.keys())}")
                    # Default home sections for Admin
                    role_data["home_sections"] = [
                        HomeSection.REQUIRED_ACTIONS,
                        HomeSection.DATA_CURATION,
                        HomeSection.DISCOVERY,
                    ] if not role_data.get("home_sections") else [HomeSection(s) if not isinstance(s, HomeSection) else s for s in role_data.get("home_sections", [])]
                    # Default approval privileges: all true
                    role_data["approval_privileges"] = role_data.get("approval_privileges") or {
                        "DOMAINS": True,
                        "CONTRACTS": True,
                        "PRODUCTS": True,
                        "BUSINESS_TERMS": True,
                        "ASSET_REVIEWS": True,
                    }
                else:
                    role_data["assigned_groups"] = role_data.get("assigned_groups") or []
                    # Prefer permissions from YAML when provided; otherwise fall back to in-code defaults
                    provided_perms = role_data.get("feature_permissions") or {}
                    if provided_perms:
                        # Normalize provided perms to enums
                        desired_permissions = {}
                        for feat_id, lvl in provided_perms.items():
                            try:
                                desired_permissions[feat_id] = FeatureAccessLevel(lvl) if not isinstance(lvl, FeatureAccessLevel) else lvl
                            except Exception:
                                logger.warning(f"Invalid access level '{lvl}' for feature '{feat_id}' in role '{role_name}' from YAML; using NONE")
                                desired_permissions[feat_id] = FeatureAccessLevel.NONE
                    else:
                        desired_permissions = DEFAULT_ROLE_PERMISSIONS.get(role_name, {})
                    final_permissions = {}
                    for feat_id, feature_config in all_features_config.items():
                        desired_level = desired_permissions.get(feat_id, FeatureAccessLevel.NONE)
                        allowed_levels = feature_config.get('allowed_levels', [])
                        
                        if desired_level in allowed_levels:
                            final_permissions[feat_id] = desired_level
                        else:
                            final_permissions[feat_id] = FeatureAccessLevel.NONE
                            if desired_level != FeatureAccessLevel.NONE:
                                allowed_str = [lvl.value for lvl in allowed_levels]
                                logger.warning(
                                    f"Desired default permission '{desired_level.value}' for role '{role_name}' "
                                    f"on feature '{feat_id}' is not allowed (Allowed: {allowed_str}). Setting to NONE."
                                )
                                
                    role_data["feature_permissions"] = final_permissions
                    logger.info(f"Assigning default permissions for role '{role_name}': { {k: v.value for k,v in final_permissions.items()} }")

                    # Default home sections per role
                    if role_data.get("home_sections"):
                        role_data["home_sections"] = [HomeSection(s) if not isinstance(s, HomeSection) else s for s in role_data.get("home_sections", [])]
                    else:
                        if role_name == "Data Consumer":
                            role_data["home_sections"] = [HomeSection.DISCOVERY]
                        elif role_name == "Data Producer":
                            role_data["home_sections"] = [HomeSection.DATA_CURATION, HomeSection.DISCOVERY]
                        elif role_name in ("Data Steward", "Security Officer", "Data Governance Officer"):
                            role_data["home_sections"] = [HomeSection.REQUIRED_ACTIONS, HomeSection.DISCOVERY]
                        else:
                            role_data["home_sections"] = [HomeSection.DISCOVERY]

                    # Default approval privileges per role
                    if role_data.get("approval_privileges") is not None:
                        # Keep as provided (Pydantic can coerce keys to enums)
                        role_data["approval_privileges"] = role_data.get("approval_privileges")
                    else:
                        if role_name == "Data Governance Officer":
                            role_data["approval_privileges"] = {
                                "DOMAINS": True,
                                "CONTRACTS": True,
                                "PRODUCTS": True,
                                "BUSINESS_TERMS": True,
                                "ASSET_REVIEWS": True,
                            }
                        elif role_name == "Data Steward":
                            role_data["approval_privileges"] = {
                                "CONTRACTS": True,
                                "PRODUCTS": True,
                                "ASSET_REVIEWS": True,
                            }
                        else:
                            role_data["approval_privileges"] = {}

                logger.debug(f"Final permissions data for role '{role_name}': {role_data['feature_permissions']}")

                try:
                    role_create_model = AppRoleCreate(**role_data)
                    self.create_app_role(role=role_create_model) # Use self.create_app_role
                    logger.info(f"Successfully created default role: {role_name}")
                except Exception as e:
                    # Log the specific role data that failed validation/creation
                    logger.error(f"Failed to create default role {role_name} with data {role_data}: {e}", exc_info=True)
                    # Should we raise here to prevent startup? Probably yes.
                    raise RuntimeError(f"Failed to create default role {role_name}. Halting startup.") from e
            
            # Set up default role hierarchy after all roles are created
            self._setup_default_role_hierarchy()
            logger.info("Default role hierarchy configured.")

        except SQLAlchemyError as e:
            logger.error(f"Database error during default role check/creation: {e}", exc_info=True)
            self._db.rollback() # Rollback on DB error
            raise RuntimeError("Failed during default role creation due to database error.")
        except Exception as e:
            logger.error(f"Unexpected error during default role check/creation: {e}", exc_info=True)
            raise # Re-raise other unexpected errors

    def _setup_default_role_hierarchy(self):
        """Sets up the default role request/approval hierarchy.
        
        Default hierarchy:
        - Data Consumer: Requestable by users with no role (__NO_ROLE__), approved by Admin, Data Steward
        - Data Producer: Requestable by Data Consumer, approved by Admin, Data Governance Officer
        - Data Steward: Requestable by Data Producer, approved by Admin, Data Governance Officer
        - Data Governance Officer: Requestable by Data Steward, approved by Admin
        - Security Officer: Requestable by Data Steward, approved by Admin
        - Admin: Requestable by Data Governance Officer, approved by Admin (self-approval for existing admins)
        """
        try:
            # Get all roles by name
            roles_by_name = {}
            for role in self.list_app_roles():
                roles_by_name[role.name] = str(role.id)
            
            if not roles_by_name:
                logger.warning("No roles found to set up hierarchy")
                return
            
            admin_id = roles_by_name.get("Admin")
            consumer_id = roles_by_name.get("Data Consumer")
            producer_id = roles_by_name.get("Data Producer")
            steward_id = roles_by_name.get("Data Steward")
            dgo_id = roles_by_name.get("Data Governance Officer")
            security_id = roles_by_name.get("Security Officer")
            
            # Define hierarchy: role_id -> (requestable_by_role_ids, approver_role_ids)
            # Use NO_ROLE_SENTINEL for "no role required"
            hierarchy = {}
            
            # Data Consumer: Requestable by users with no role, approved by Admin and Data Steward
            if consumer_id:
                requestable_by = [NO_ROLE_SENTINEL]
                approvers = [admin_id] if admin_id else []
                if steward_id:
                    approvers.append(steward_id)
                hierarchy[consumer_id] = (requestable_by, approvers)
            
            # Data Producer: Requestable by Data Consumer, approved by Admin and DGO
            if producer_id:
                requestable_by = [consumer_id] if consumer_id else []
                approvers = [admin_id] if admin_id else []
                if dgo_id:
                    approvers.append(dgo_id)
                hierarchy[producer_id] = (requestable_by, approvers)
            
            # Data Steward: Requestable by Data Producer, approved by Admin and DGO
            if steward_id:
                requestable_by = [producer_id] if producer_id else []
                approvers = [admin_id] if admin_id else []
                if dgo_id:
                    approvers.append(dgo_id)
                hierarchy[steward_id] = (requestable_by, approvers)
            
            # Data Governance Officer: Requestable by Data Steward, approved by Admin
            if dgo_id:
                requestable_by = [steward_id] if steward_id else []
                approvers = [admin_id] if admin_id else []
                hierarchy[dgo_id] = (requestable_by, approvers)
            
            # Security Officer: Requestable by Data Steward, approved by Admin
            if security_id:
                requestable_by = [steward_id] if steward_id else []
                approvers = [admin_id] if admin_id else []
                hierarchy[security_id] = (requestable_by, approvers)
            
            # Admin: Requestable by DGO, approved by Admin (existing admins can approve)
            if admin_id:
                requestable_by = [dgo_id] if dgo_id else []
                approvers = [admin_id]
                hierarchy[admin_id] = (requestable_by, approvers)
            
            # Apply hierarchy
            for role_id, (requestable_by, approvers) in hierarchy.items():
                # Filter out None values
                requestable_by = [r for r in requestable_by if r]
                approvers = [a for a in approvers if a]
                
                if requestable_by:
                    role_hierarchy_repo.set_requestable_by_roles(self._db, role_id, requestable_by)
                    logger.debug(f"Set requestable_by for role {role_id}: {requestable_by}")
                
                if approvers:
                    role_hierarchy_repo.set_approver_roles(self._db, role_id, approvers)
                    logger.debug(f"Set approvers for role {role_id}: {approvers}")
            
            logger.info(f"Default role hierarchy set up for {len(hierarchy)} roles")
            
        except Exception as e:
            logger.error(f"Error setting up default role hierarchy: {e}", exc_info=True)
            # Don't fail startup, just log the error

    def ensure_default_team_and_project(self):
        """Ensures default 'Admin Team' and 'Admin Project' exist for admin users."""
        try:
            # Check if Admin Team already exists
            admin_team = team_repo.get_by_name(self._db, name="Admin Team")
            
            if not admin_team:
                logger.info("No 'Admin Team' found. Creating default admin team...")
                
                # Parse admin groups from environment
                admin_groups = []
                try:
                    groups_json = self._settings.APP_ADMIN_DEFAULT_GROUPS
                    if groups_json:
                        admin_groups = json.loads(groups_json)
                        if not isinstance(admin_groups, list):
                            logger.warning(f"APP_ADMIN_DEFAULT_GROUPS is not a valid JSON list. Creating team without members.")
                            admin_groups = []
                except (json.JSONDecodeError, AttributeError):
                    logger.info("Could not parse APP_ADMIN_DEFAULT_GROUPS. Creating team without initial members.")
                    admin_groups = []
                
                # Create Admin Team directly as DB object (tags managed separately)
                admin_team = TeamDb(
                    name='Admin Team',
                    title='Default Administrator Team',
                    description='Auto-created team for system administrators',
                    domain_id=None,
                    extra_metadata='{}',
                    created_by='system@startup.ucapp',
                    updated_by='system@startup.ucapp'
                )
                self._db.add(admin_team)
                self._db.flush()
                logger.info(f"Created Admin Team with id: {admin_team.id}")
                
                # Add admin groups as team members
                for group_name in admin_groups:
                    try:
                        member = TeamMemberDb(
                            team_id=admin_team.id,
                            member_type='group',
                            member_identifier=group_name,
                            app_role_override='Admin',
                            added_by='system@startup.ucapp'
                        )
                        self._db.add(member)
                        logger.info(f"Added admin group '{group_name}' to Admin Team")
                    except Exception as e:
                        logger.warning(f"Failed to add group '{group_name}' to Admin Team: {e}")
                
                self._db.flush()
            else:
                logger.info(f"Admin Team already exists with id: {admin_team.id}")
            
            # Check if Admin Project already exists
            admin_project = project_repo.get_by_name(self._db, name="Admin Project")
            
            if not admin_project:
                logger.info("No 'Admin Project' found. Creating default admin project...")
                
                # Create Admin Project directly as DB object (tags managed separately)
                admin_project = ProjectDb(
                    name='Admin Project',
                    title='Default Administrator Project',
                    description='Auto-created project for system administrators',
                    owner_team_id=admin_team.id,
                    project_type='TEAM',
                    extra_metadata='{}',
                    created_by='system@startup.ucapp',
                    updated_by='system@startup.ucapp'
                )
                self._db.add(admin_project)
                self._db.flush()
                logger.info(f"Created Admin Project with id: {admin_project.id}")
                
                # Assign Admin Team to Admin Project
                try:
                    project_repo.assign_team(
                        db=self._db,
                        project_id=admin_project.id,
                        team_id=admin_team.id,
                        assigned_by='system@startup.ucapp'
                    )
                    logger.info(f"Assigned Admin Team to Admin Project")
                except Exception as e:
                    logger.warning(f"Failed to assign Admin Team to Admin Project: {e}")
                
                self._db.flush()
            else:
                logger.info(f"Admin Project already exists with id: {admin_project.id}")
            
            logger.info("Default team and project setup completed successfully")
            
        except SQLAlchemyError as e:
            logger.error(f"Database error during default team/project setup: {e}", exc_info=True)
            self._db.rollback()
            raise RuntimeError("Failed during default team/project creation due to database error.")
        except Exception as e:
            logger.error(f"Unexpected error during default team/project setup: {e}", exc_info=True)
            raise

    def get_job_clusters(self) -> List[JobCluster]:
        """Deprecated: listing clusters is slow; return empty list."""
        return []
        # TODO: This call is too slow and blocks the entire call to get_settings, need to fix this
        # clusters = self._client.clusters.list()
        # return [
        #     JobCluster(
        #         id=cluster.cluster_id,
        #         name=cluster.cluster_name,
        #         node_type_id=cluster.node_type_id,
        #         autoscale=bool(cluster.autoscale),
        #         min_workers=cluster.autoscale.min_workers if cluster.autoscale else cluster.num_workers,
        #         max_workers=cluster.autoscale.max_workers if cluster.autoscale else cluster.num_workers
        #     )
        #     for cluster in clusters
        # ]

    # --- Documentation Methods ---

    def _get_docs_directory(self) -> 'Path':
        """Get the path to the documentation directory."""
        from pathlib import Path
        # Navigate from settings_manager.py to docs/
        # __file__ = src/backend/src/controller/settings_manager.py
        # .parent.parent.parent.parent = src/
        return Path(__file__).parent.parent.parent.parent / "docs"

    def _load_docs_registry(self) -> Dict[str, Any]:
        """Load the documentation registry from docs.yaml."""
        import yaml

        docs_dir = self._get_docs_directory()
        registry_path = docs_dir / "docs.yaml"

        if not registry_path.exists():
            logger.error(f"Documentation registry not found at: {registry_path}")
            return {}

        try:
            with open(registry_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data.get('documents', {})
        except Exception as e:
            logger.error(f"Error loading documentation registry: {e}")
            return {}

    def get_available_docs(self) -> Dict[str, Dict[str, Any]]:
        """Get all available markdown documentation files from registry.

        Returns:
            Dict mapping doc keys to metadata (title, description, file, path)
        """
        docs_dir = self._get_docs_directory()

        # Load document definitions from YAML
        available_docs = self._load_docs_registry()

        # Validate that all files exist and add resolved paths
        result = {}
        for doc_key, doc_info in available_docs.items():
            doc_path = docs_dir / doc_info["file"]
            if doc_path.exists():
                result[doc_key] = {
                    **doc_info,
                    "path": str(doc_path.resolve())
                }
            else:
                logger.warning(f"Documentation file '{doc_info['file']}' not found at: {doc_path}")

        return result

    def get_documentation_content(self, doc_name: str) -> Dict[str, Any]:
        """Get specific documentation file content by name.

        Args:
            doc_name: Documentation key from registry

        Returns:
            Dict with name, title, description, content, and optional category

        Raises:
            ValueError: If doc_name not found in registry
            FileNotFoundError: If doc file doesn't exist
        """
        from pathlib import Path

        available_docs = self.get_available_docs()

        if doc_name not in available_docs:
            raise ValueError(
                f"Documentation '{doc_name}' not found. Available: {', '.join(available_docs.keys())}"
            )

        doc_info = available_docs[doc_name]
        doc_path = Path(doc_info["path"])

        logger.debug(f"Loading documentation '{doc_name}' from: {doc_path}")

        try:
            content = doc_path.read_text(encoding="utf-8")
            logger.info(f"Successfully loaded '{doc_name}' ({len(content)} chars)")

            result = {
                "name": doc_name,
                "title": doc_info["title"],
                "description": doc_info["description"],
                "content": content
            }
            # Include optional category field if present
            if "category" in doc_info:
                result["category"] = doc_info["category"]
            return result
        except Exception as e:
            logger.error(f"Error reading documentation '{doc_name}': {e}")
            raise

    def extract_database_schema(self) -> Dict[str, Any]:
        """Extract database schema from SQLAlchemy models for ERD visualization.

        Returns:
            Dict with 'tables' and 'relationships' keys for schema visualization.
            Each table may include a 'description' from the model's docstring or __erd_doc__.
        """
        from src.common.database import Base

        tables = []
        relationships = []

        # Build table name -> mapped class for docstrings (ORM models only; association tables have no mapper)
        table_name_to_class: Dict[str, type] = {}
        for mapper in Base.registry.mappers:
            for t in mapper.tables:
                if t.name not in table_name_to_class:
                    table_name_to_class[t.name] = mapper.class_

        def _table_description(table_name: str) -> Optional[str]:
            cls = table_name_to_class.get(table_name)
            if not cls:
                return None
            doc = getattr(cls, "__erd_doc__", None)
            if doc is not None and isinstance(doc, str):
                return doc.strip() or None
            if cls.__doc__:
                return cls.__doc__.strip() or None
            return None

        logger.info(f"Introspecting database schema. Found {len(Base.metadata.tables)} tables.")

        # Iterate through all tables in metadata
        for table_name, table in Base.metadata.tables.items():
            columns = []

            # Extract column information
            for column in table.columns:
                # Check if column has foreign keys
                fk_info = None
                if column.foreign_keys:
                    fk = list(column.foreign_keys)[0]  # Get first FK if multiple
                    fk_info = {
                        'target_table': fk.column.table.name,
                        'target_column': fk.column.name
                    }

                columns.append({
                    'name': column.name,
                    'type': str(column.type),
                    'primary_key': column.primary_key,
                    'nullable': column.nullable,
                    'foreign_key': fk_info
                })

            table_entry: Dict[str, Any] = {
                'id': table_name,
                'name': table_name,
                'columns': columns
            }
            description = _table_description(table_name)
            if description:
                table_entry['description'] = description
            tables.append(table_entry)

            # Extract foreign key relationships for edges
            for fk_constraint in table.foreign_key_constraints:
                # Get the referred table
                referred_table = fk_constraint.referred_table.name

                relationships.append({
                    'id': f"{table_name}_{referred_table}_{len(relationships)}",
                    'source': table_name,
                    'target': referred_table,
                    'columns': list(fk_constraint.column_keys)
                })

        logger.info(f"Schema introspection complete. Tables: {len(tables)}, Relationships: {len(relationships)}")

        return {
            'tables': tables,
            'relationships': relationships
        }

    def list_available_workflows(self) -> list:
        """Delegate to JobsManager to list available workflows."""
        if getattr(self, '_jobs', None):
            return self._jobs.list_available_workflows()
        return []

    def get_settings(self) -> dict:
        """Get current settings"""
        # Refresh available jobs from filesystem to reflect changes
        available = self._jobs.list_available_workflows() if getattr(self, '_jobs', None) else []
        self._available_jobs = [w["id"] if isinstance(w, dict) else w for w in available]

        # Get enabled jobs from WorkflowInstallationDb (source of truth)
        from src.repositories.workflow_installations_repository import workflow_installation_repo
        enabled_installations = workflow_installation_repo.get_all_installed(self._db)
        enabled_job_ids = [inst.workflow_id for inst in enabled_installations]
        
        # Get tag display format from database (default: 'short')
        tag_display_format = app_settings_repo.get_by_key(self._db, 'TAG_DISPLAY_FORMAT') or 'short'

        return {
            'job_cluster_id': self._settings.job_cluster_id,
            'enabled_jobs': enabled_job_ids,  # From database, not Settings model
            'available_workflows': available,
            'current_settings': self._settings.to_dict(),
            'workspace_deployment_path': self._settings.WORKSPACE_DEPLOYMENT_PATH,
            # Databricks Unity Catalog settings
            'databricks_catalog': self._settings.DATABRICKS_CATALOG,
            'databricks_schema': self._settings.DATABRICKS_SCHEMA,
            'databricks_volume': self._settings.DATABRICKS_VOLUME,
            # Audit log settings
            'app_audit_log_dir': self._settings.APP_AUDIT_LOG_DIR,
            # LLM settings
            'llm_enabled': self._settings.LLM_ENABLED,
            'llm_endpoint': self._settings.LLM_ENDPOINT,
            'llm_system_prompt': self._settings.LLM_SYSTEM_PROMPT,
            'llm_disclaimer_text': self._settings.LLM_DISCLAIMER_TEXT,
            # Tag display settings
            'tag_display_format': tag_display_format,
            # Delivery mode settings
            'delivery_mode_direct': self._settings.DELIVERY_MODE_DIRECT,
            'delivery_mode_indirect': self._settings.DELIVERY_MODE_INDIRECT,
            'delivery_mode_manual': self._settings.DELIVERY_MODE_MANUAL,
            'delivery_direct_dry_run': self._settings.DELIVERY_DIRECT_DRY_RUN,
            # Git settings for indirect mode
            'git_repo_url': self._settings.GIT_REPO_URL,
            'git_branch': self._settings.GIT_BRANCH,
            'git_username': self._settings.GIT_USERNAME,
            # UI Customization settings
            'ui_i18n_enabled': self._settings.UI_I18N_ENABLED,
            'ui_custom_logo_url': self._settings.UI_CUSTOM_LOGO_URL,
            'ui_about_content': self._settings.UI_ABOUT_CONTENT,
            'ui_custom_css': self._settings.UI_CUSTOM_CSS,
        }

    def update_settings(self, settings: dict) -> Settings:
        """Update settings"""
        # Persist configured cluster ID string; do not scan clusters
        desired_cluster_id: Optional[str] = settings.get('job_cluster_id')
        desired_enabled: List[str] = settings.get('enabled_jobs', []) or []
        
        logger.info(f"SettingsManager.update_settings received cluster_id: {desired_cluster_id}")
        logger.info(f"SettingsManager.update_settings current stored cluster_id: {self._settings.job_cluster_id}")

        # Handle workspace_deployment_path BEFORE workflow changes so the deployer
        # is initialized when install_workflow runs
        if 'workspace_deployment_path' in settings:
            new_path = settings.get('workspace_deployment_path')
            if new_path == '':
                new_path = None
            app_settings_repo.set(self._db, 'WORKSPACE_DEPLOYMENT_PATH', new_path)
            self._settings.WORKSPACE_DEPLOYMENT_PATH = new_path
            logger.info(f"Updated WORKSPACE_DEPLOYMENT_PATH to: {new_path}")
            self._reinitialize_workspace_deployer()

        # Compute job enable/disable delta against current state from DB (source of truth)
        try:
            enabled_installations = workflow_installation_repo.get_all_installed(self._db)
            current_enabled: List[str] = [inst.workflow_id for inst in enabled_installations]
        except Exception:
            current_enabled = self._settings.enabled_jobs or []
        self._available_jobs = [w["id"] for w in (self._jobs.list_available_workflows() if self._jobs else [])]

        to_install = sorted(list(set(desired_enabled) - set(current_enabled)))
        to_remove = sorted(list(set(current_enabled) - set(desired_enabled)))

        logger.info(f"Current enabled: {current_enabled}, Desired enabled: {desired_enabled}")
        logger.info(f"To install: {to_install}, To remove: {to_remove}")

        # Prevent disabling running workflows
        try:
            running_blockers: List[str] = []
            if getattr(self, '_jobs', None) and to_remove:
                statuses = self._jobs.get_workflow_statuses(to_remove)
                for wid, st in (statuses or {}).items():
                    try:
                        if st and st.get('is_running'):
                            running_blockers.append(wid)
                    except Exception:
                        continue
            if running_blockers:
                raise RuntimeError(f"Cannot disable running workflow(s): {', '.join(sorted(running_blockers))}")
        except Exception as e:
            # Surface the error to caller
            raise

        # Apply changes on Databricks and collect errors
        errors = []

        # Reconcile drift: desired job enabled but Databricks job missing; remove stale DB record and reinstall
        try:
            if self._client and self._jobs:
                for job_id in list(desired_enabled):
                    try:
                        installation = workflow_installation_repo.get_by_workflow_id(self._db, workflow_id=job_id)
                    except Exception:
                        installation = None
                    if not installation:
                        continue
                    try:
                        # Validate remote job existence; add to install if missing
                        self._client.jobs.get(job_id=installation.job_id)
                    except Exception:
                        try:
                            workflow_installation_repo.remove(self._db, id=installation.id)
                            self._db.commit()
                            logger.info(f"Removed stale installation for workflow '{job_id}' (missing in Databricks)")
                        except Exception as e:
                            logger.error(f"Failed to remove stale installation for '{job_id}': {e}")
                            self._db.rollback()
                        if job_id not in to_install:
                            to_install.append(job_id)
                to_install = sorted(list(set(to_install)))
        except Exception as e:
            logger.error(f"Error during drift reconciliation: {e}")

        # Log final plan after reconciliation
        logger.info(f"Final to_install after reconciliation: {to_install}; to_remove: {to_remove}")
        
        for job_id in to_install:
            # Only process jobs that exist in workflows
            if job_id in self._available_jobs:
                try:
                    if self._jobs:
                        # Use the new desired cluster ID value, or fall back to current setting
                        # If None or empty, workflow will use Databricks serverless compute
                        cluster_id_to_use = desired_cluster_id if desired_cluster_id is not None else self._settings.job_cluster_id
                        # Filter out placeholder values that indicate "not set"
                        if cluster_id_to_use in ['cluster-id', '']:
                            cluster_id_to_use = None

                        self._jobs.install_workflow(job_id, job_cluster_id=cluster_id_to_use)
                        logger.info(f"Successfully installed workflow '{job_id}' with cluster_id={cluster_id_to_use or 'serverless'}")
                except Exception as e:
                    error_msg = f"Failed to install workflow '{job_id}': {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg, exc_info=True)
            else:
                error_msg = f"Workflow '{job_id}' not found in available workflows"
                errors.append(error_msg)
                logger.warning(error_msg)

        for job_id in to_remove:
            logger.info(f"Processing removal of workflow '{job_id}'")

            if job_id in self._available_jobs:
                try:
                    if self._jobs:
                        # Look up from database instead of Databricks (much faster)
                        logger.info(f"Looking up installation record for workflow: '{job_id}'")
                        installation = workflow_installation_repo.get_by_workflow_id(self._db, workflow_id=job_id)

                        if installation:
                            # If remote job already missing, just remove DB record to avoid errors
                            remote_exists = True
                            try:
                                self._client.jobs.get(job_id=installation.job_id)
                            except Exception:
                                remote_exists = False

                            if remote_exists:
                                logger.info(f"Found installation record, calling remove_workflow with job_id: {installation.job_id}")
                                self._jobs.remove_workflow(installation.job_id)
                                logger.info(f"Successfully removed workflow '{job_id}'")
                            else:
                                try:
                                    workflow_installation_repo.remove(self._db, id=installation.id)
                                    self._db.commit()
                                    logger.info(f"Removed stale installation record for '{job_id}' (remote job already absent)")
                                except Exception as e:
                                    logger.error(f"Failed to remove stale installation for '{job_id}': {e}")
                                    self._db.rollback()
                        else:
                            logger.warning(f"Installation record for '{job_id}' not found in database, attempting Databricks lookup")
                            # Fallback to Databricks lookup if not in database
                            job = self._jobs.find_job_by_name(job_id)
                            if job:
                                self._jobs.remove_workflow(job.job_id)
                                logger.info(f"Successfully removed workflow '{job_id}' (via Databricks lookup)")
                            else:
                                logger.warning(f"Job '{job_id}' not found in Databricks either, may have been already deleted")
                except Exception as e:
                    error_msg = f"Failed to remove workflow '{job_id}': {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg, exc_info=True)
            else:
                error_msg = f"Workflow '{job_id}' not found in available workflows"
                errors.append(error_msg)
                logger.warning(error_msg)
        
        # If there were errors, raise an exception with all error details
        if errors:
            error_summary = f"Failed to update {len(errors)} workflow(s): " + "; ".join(errors)
            raise RuntimeError(error_summary)

        # Update stored settings after applying infra changes
        self._settings.job_cluster_id = desired_cluster_id
        self._settings.enabled_jobs = sorted(list(set(desired_enabled)))
        self._settings.sync_enabled = settings.get('sync_enabled', False)
        self._settings.sync_repository = settings.get('sync_repository')
        self._settings.updated_at = datetime.utcnow()
        
        # Handle Databricks Unity Catalog settings
        if 'databricks_catalog' in settings:
            value = settings.get('databricks_catalog') or None
            app_settings_repo.set(self._db, 'DATABRICKS_CATALOG', value)
            self._settings.DATABRICKS_CATALOG = value or self._settings.DATABRICKS_CATALOG
            logger.info(f"Updated DATABRICKS_CATALOG to: {value}")
        
        if 'databricks_schema' in settings:
            value = settings.get('databricks_schema') or None
            app_settings_repo.set(self._db, 'DATABRICKS_SCHEMA', value)
            self._settings.DATABRICKS_SCHEMA = value or self._settings.DATABRICKS_SCHEMA
            logger.info(f"Updated DATABRICKS_SCHEMA to: {value}")
        
        if 'databricks_volume' in settings:
            value = settings.get('databricks_volume') or None
            app_settings_repo.set(self._db, 'DATABRICKS_VOLUME', value)
            self._settings.DATABRICKS_VOLUME = value or self._settings.DATABRICKS_VOLUME
            logger.info(f"Updated DATABRICKS_VOLUME to: {value}")
        
        # Handle audit log directory
        if 'app_audit_log_dir' in settings:
            value = settings.get('app_audit_log_dir') or None
            app_settings_repo.set(self._db, 'APP_AUDIT_LOG_DIR', value)
            self._settings.APP_AUDIT_LOG_DIR = value or self._settings.APP_AUDIT_LOG_DIR
            logger.info(f"Updated APP_AUDIT_LOG_DIR to: {value}")
        
        # Handle LLM settings
        if 'llm_enabled' in settings:
            value = settings.get('llm_enabled')
            # Convert to string for storage, then back to bool
            app_settings_repo.set(self._db, 'LLM_ENABLED', str(value).lower() if value is not None else None)
            self._settings.LLM_ENABLED = bool(value) if value is not None else self._settings.LLM_ENABLED
            logger.info(f"Updated LLM_ENABLED to: {value}")
        
        if 'llm_endpoint' in settings:
            value = settings.get('llm_endpoint') or None
            app_settings_repo.set(self._db, 'LLM_ENDPOINT', value)
            self._settings.LLM_ENDPOINT = value
            logger.info(f"Updated LLM_ENDPOINT to: {value}")
        
        if 'llm_system_prompt' in settings:
            value = settings.get('llm_system_prompt') or None
            app_settings_repo.set(self._db, 'LLM_SYSTEM_PROMPT', value)
            self._settings.LLM_SYSTEM_PROMPT = value
            logger.info(f"Updated LLM_SYSTEM_PROMPT")
        
        if 'llm_disclaimer_text' in settings:
            value = settings.get('llm_disclaimer_text') or None
            app_settings_repo.set(self._db, 'LLM_DISCLAIMER_TEXT', value)
            self._settings.LLM_DISCLAIMER_TEXT = value
            logger.info(f"Updated LLM_DISCLAIMER_TEXT")
        
        # Handle tag display format setting
        if 'tag_display_format' in settings:
            value = settings.get('tag_display_format')
            # Validate value - only 'short' or 'long' are valid
            if value in ('short', 'long'):
                app_settings_repo.set(self._db, 'TAG_DISPLAY_FORMAT', value)
                logger.info(f"Updated TAG_DISPLAY_FORMAT to: {value}")
            else:
                logger.warning(f"Invalid tag_display_format value: {value}. Must be 'short' or 'long'.")
        
        # Handle delivery mode settings
        if 'delivery_mode_direct' in settings:
            value = settings.get('delivery_mode_direct')
            app_settings_repo.set(self._db, 'DELIVERY_MODE_DIRECT', str(value).lower() if value is not None else None)
            self._settings.DELIVERY_MODE_DIRECT = bool(value) if value is not None else self._settings.DELIVERY_MODE_DIRECT
            logger.info(f"Updated DELIVERY_MODE_DIRECT to: {value}")
        
        if 'delivery_mode_indirect' in settings:
            value = settings.get('delivery_mode_indirect')
            app_settings_repo.set(self._db, 'DELIVERY_MODE_INDIRECT', str(value).lower() if value is not None else None)
            self._settings.DELIVERY_MODE_INDIRECT = bool(value) if value is not None else self._settings.DELIVERY_MODE_INDIRECT
            logger.info(f"Updated DELIVERY_MODE_INDIRECT to: {value}")
        
        if 'delivery_mode_manual' in settings:
            value = settings.get('delivery_mode_manual')
            app_settings_repo.set(self._db, 'DELIVERY_MODE_MANUAL', str(value).lower() if value is not None else None)
            self._settings.DELIVERY_MODE_MANUAL = bool(value) if value is not None else self._settings.DELIVERY_MODE_MANUAL
            logger.info(f"Updated DELIVERY_MODE_MANUAL to: {value}")
        
        if 'delivery_direct_dry_run' in settings:
            value = settings.get('delivery_direct_dry_run')
            app_settings_repo.set(self._db, 'DELIVERY_DIRECT_DRY_RUN', str(value).lower() if value is not None else None)
            self._settings.DELIVERY_DIRECT_DRY_RUN = bool(value) if value is not None else self._settings.DELIVERY_DIRECT_DRY_RUN
            logger.info(f"Updated DELIVERY_DIRECT_DRY_RUN to: {value}")
        
        # Handle Git settings for indirect mode
        if 'git_repo_url' in settings:
            value = settings.get('git_repo_url') or None
            app_settings_repo.set(self._db, 'GIT_REPO_URL', value)
            self._settings.GIT_REPO_URL = value
            logger.info(f"Updated GIT_REPO_URL")
        
        if 'git_branch' in settings:
            value = settings.get('git_branch') or 'main'
            app_settings_repo.set(self._db, 'GIT_BRANCH', value)
            self._settings.GIT_BRANCH = value
            logger.info(f"Updated GIT_BRANCH to: {value}")
        
        if 'git_username' in settings:
            value = settings.get('git_username') or None
            app_settings_repo.set(self._db, 'GIT_USERNAME', value)
            self._settings.GIT_USERNAME = value
            logger.info(f"Updated GIT_USERNAME")
        
        if 'git_password' in settings:
            value = settings.get('git_password') or None
            app_settings_repo.set(self._db, 'GIT_PASSWORD', value)
            self._settings.GIT_PASSWORD = value
            logger.info(f"Updated GIT_PASSWORD")
        
        # UI Customization settings
        if 'ui_i18n_enabled' in settings:
            value = settings.get('ui_i18n_enabled')
            app_settings_repo.set(self._db, 'UI_I18N_ENABLED', str(value).lower() if value is not None else None)
            self._settings.UI_I18N_ENABLED = bool(value) if value is not None else self._settings.UI_I18N_ENABLED
            logger.info(f"Updated UI_I18N_ENABLED to: {value}")
        
        if 'ui_custom_logo_url' in settings:
            value = settings.get('ui_custom_logo_url') or None
            app_settings_repo.set(self._db, 'UI_CUSTOM_LOGO_URL', value)
            self._settings.UI_CUSTOM_LOGO_URL = value
            logger.info(f"Updated UI_CUSTOM_LOGO_URL")
        
        if 'ui_about_content' in settings:
            value = settings.get('ui_about_content') or None
            app_settings_repo.set(self._db, 'UI_ABOUT_CONTENT', value)
            self._settings.UI_ABOUT_CONTENT = value
            logger.info(f"Updated UI_ABOUT_CONTENT")
        
        if 'ui_custom_css' in settings:
            value = settings.get('ui_custom_css') or None
            app_settings_repo.set(self._db, 'UI_CUSTOM_CSS', value)
            self._settings.UI_CUSTOM_CSS = value
            logger.info(f"Updated UI_CUSTOM_CSS")
        
        # Reinitialize Git service if any Git settings were changed
        git_settings_changed = any(key in settings for key in ['git_repo_url', 'git_branch', 'git_username', 'git_password'])
        if git_settings_changed:
            try:
                from src.common.git import reinitialize_git_service
                reinitialize_git_service(self._settings)
                logger.info("Git service reinitialized after settings update")
            except RuntimeError as e:
                logger.warning(f"Could not reinitialize Git service: {e}")
            except Exception as e:
                logger.error(f"Error reinitializing Git service: {e}", exc_info=True)
        
        return self._settings

    # --- RBAC Methods --- 

    def get_app_roles_count(self) -> int:
        """Returns the total number of application roles."""
        try:
            count = self.app_role_repo.get_roles_count(db=self._db)
            logger.debug(f"Found {count} application roles in the database.")
            return count
        except SQLAlchemyError as e:
            logger.error(f"Database error while counting roles: {e}", exc_info=True)
            self._db.rollback()
            raise RuntimeError("Failed to count application roles due to database error.")

    def set_notifications_manager(self, notifications_manager: 'NotificationsManager'):
        """Set the notifications manager and reinitialize jobs manager if needed."""
        self._notifications_manager = notifications_manager
        
        # Reinitialize jobs manager with notifications support
        if self._client:
            try:
                from src.controller.jobs_manager import JobsManager
                from src.utils.workspace_deployer import WorkspaceDeployer

                # Initialize WorkspaceDeployer if deployment path is configured
                workspace_deployer = None
                if self._settings.WORKSPACE_DEPLOYMENT_PATH:
                    try:
                        workspace_deployer = WorkspaceDeployer(
                            ws_client=self._client,
                            deployment_path=self._settings.WORKSPACE_DEPLOYMENT_PATH
                        )
                    except Exception as e:
                        logger.warning(f"Failed to initialize WorkspaceDeployer: {e}")

                self._jobs = JobsManager(
                    db=self._db,
                    ws_client=self._client,
                    notifications_manager=self._notifications_manager,
                    settings=self._settings,
                    workspace_deployer=workspace_deployer
                )
                self._available_jobs = [w["id"] for w in self._jobs.list_available_workflows()]
            except Exception as e:
                logger.error(f"Failed to reinitialize jobs manager with notifications: {e}")

    def _reinitialize_workspace_deployer(self) -> None:
        """Recreate the WorkspaceDeployer on the existing JobsManager after
        WORKSPACE_DEPLOYMENT_PATH has been updated."""
        if not self._jobs or not self._client:
            return
        try:
            from src.utils.workspace_deployer import WorkspaceDeployer

            if self._settings.WORKSPACE_DEPLOYMENT_PATH:
                deployer = WorkspaceDeployer(
                    ws_client=self._client,
                    deployment_path=self._settings.WORKSPACE_DEPLOYMENT_PATH
                )
                self._jobs._workspace_deployer = deployer
                logger.info(f"Reinitialized WorkspaceDeployer with path: {self._settings.WORKSPACE_DEPLOYMENT_PATH}")
            else:
                self._jobs._workspace_deployer = None
                logger.info("Cleared WorkspaceDeployer (WORKSPACE_DEPLOYMENT_PATH is empty)")
        except Exception as e:
            logger.warning(f"Failed to reinitialize WorkspaceDeployer: {e}")

    def _map_db_to_api(self, role_db: AppRoleDb) -> AppRole:
        """Converts an AppRoleDb model to an AppRole API model."""
        # Deserialize JSON fields safely
        try:
            assigned_groups = json.loads(role_db.assigned_groups or '[]') # Handle None
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Could not parse assigned_groups JSON for role ID {role_db.id}: {role_db.assigned_groups}")
            assigned_groups = []

        # Feature ID migrations (renamed features)
        FEATURE_ID_MIGRATIONS = {
            'security': 'security-features',
        }

        try:
            feature_permissions_raw = json.loads(role_db.feature_permissions or '{}') # Handle None
            # Apply feature ID migrations for renamed features
            feature_permissions_raw = {
                FEATURE_ID_MIGRATIONS.get(k, k): v 
                for k, v in feature_permissions_raw.items()
            }
            feature_permissions = {
                k: FeatureAccessLevel(v) 
                for k, v in feature_permissions_raw.items() 
                if isinstance(v, str) # Ensure value is string before enum conversion
            }
            
            # For Admin role: ensure ADMIN permission for any NEW features not yet in DB
            # This handles the case when new features are added after the Admin role was created
            if role_db.name == "Admin":
                all_features = get_feature_config()
                for feat_id in all_features:
                    if feat_id not in feature_permissions:
                        feature_permissions[feat_id] = FeatureAccessLevel.ADMIN
                        logger.debug(f"Auto-granting ADMIN permission for new feature '{feat_id}' to Admin role")
                        
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(f"Could not parse or convert feature_permissions JSON for role ID {role_db.id}: {role_db.feature_permissions}. Error: {e}")
            feature_permissions = {}

        try:
            home_sections_raw = json.loads(getattr(role_db, 'home_sections', '[]') or '[]')
            home_sections = [HomeSection(s) for s in home_sections_raw if isinstance(s, str)]
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(f"Could not parse or convert home_sections JSON for role ID {role_db.id}: {getattr(role_db, 'home_sections', None)}. Error: {e}")
            home_sections = []

        # Parse approval privileges
        try:
            approval_privs_raw = json.loads(getattr(role_db, 'approval_privileges', '{}') or '{}')
            approval_privileges = { ApprovalEntity(k): bool(v) for k, v in approval_privs_raw.items() if isinstance(k, str) }
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(f"Could not parse or convert approval_privileges JSON for role ID {role_db.id}: {getattr(role_db, 'approval_privileges', None)}. Error: {e}")
            approval_privileges = {}

        # Parse deployment policy
        deployment_policy = None
        try:
            deployment_policy_raw = getattr(role_db, 'deployment_policy', None)
            if deployment_policy_raw:
                deployment_policy_dict = json.loads(deployment_policy_raw) if isinstance(deployment_policy_raw, str) else deployment_policy_raw
                from src.models.settings import DeploymentPolicy
                deployment_policy = DeploymentPolicy(**deployment_policy_dict)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(f"Could not parse or convert deployment_policy JSON for role ID {role_db.id}: {getattr(role_db, 'deployment_policy', None)}. Error: {e}")
            deployment_policy = None

        # Get role hierarchy data from the hierarchy tables
        try:
            requestable_by_roles = role_hierarchy_repo.get_requestable_by_roles(self._db, str(role_db.id))
        except Exception as e:
            logger.warning(f"Could not get requestable_by_roles for role ID {role_db.id}: {e}")
            requestable_by_roles = []

        try:
            approver_roles = role_hierarchy_repo.get_approver_roles(self._db, str(role_db.id))
        except Exception as e:
            logger.warning(f"Could not get approver_roles for role ID {role_db.id}: {e}")
            approver_roles = []

        return AppRole(
            id=role_db.id,
            name=role_db.name,
            description=role_db.description,
            assigned_groups=assigned_groups,
            feature_permissions=feature_permissions,
            home_sections=home_sections,
            approval_privileges=approval_privileges,
            deployment_policy=deployment_policy,
            is_admin=getattr(role_db, 'is_admin', False),
            requestable_by_roles=requestable_by_roles,
            approver_roles=approver_roles,
            # created_at=role_db.created_at, # Uncomment if needed
            # updated_at=role_db.updated_at  # Uncomment if needed
        )

    def get_features_with_access_levels(self) -> Dict[str, Dict[str, str | List[str]]]:
        """Returns a dictionary of features and their allowed access levels."""
        features_config = get_feature_config()
        all_levels = get_all_access_levels()
        # Convert enum members to their string values for API response
        return {
            feature_id: {
                'name': config['name'],
                'allowed_levels': [level.value for level in config['allowed_levels']]
            }
            for feature_id, config in features_config.items()
        }

    def list_app_roles(self) -> List[AppRole]:
        """Lists all configured application roles from the database."""
        try:
            roles_db = self.app_role_repo.get_all_roles(db=self._db)

            # Backfill default home_sections for roles missing configuration
            updated_any = False
            for role_db in roles_db:
                try:
                    hs_raw = json.loads(getattr(role_db, 'home_sections', '[]') or '[]')
                except Exception:
                    hs_raw = []
                if not hs_raw:
                    default_sections: List[HomeSection]
                    name = (role_db.name or '').strip()
                    if name == 'Admin':
                        default_sections = [HomeSection.REQUIRED_ACTIONS, HomeSection.DATA_CURATION, HomeSection.DISCOVERY]
                    elif name in ('Data Steward', 'Security Officer', 'Data Governance Officer'):
                        default_sections = [HomeSection.REQUIRED_ACTIONS, HomeSection.DISCOVERY]
                    elif name == 'Data Producer':
                        default_sections = [HomeSection.DATA_CURATION, HomeSection.DISCOVERY]
                    else:  # Data Consumer or others
                        default_sections = [HomeSection.DISCOVERY]
                    # Persist backfill
                    self.app_role_repo.update(db=self._db, db_obj=role_db, obj_in={'home_sections': default_sections})
                    updated_any = True

                # Backfill approval_privileges defaults if missing
                try:
                    ap_raw = json.loads(getattr(role_db, 'approval_privileges', '{}') or '{}')
                except Exception:
                    ap_raw = {}
                if not ap_raw:
                    name = (role_db.name or '').strip()
                    defaults: dict[str, bool] = {}
                    if name in ("Admin", "Data Governance Officer"):
                        defaults = { e.value: True for e in ApprovalEntity }
                    elif name == "Data Steward":
                        defaults = {
                            ApprovalEntity.CONTRACTS.value: True,
                            ApprovalEntity.PRODUCTS.value: True,
                            ApprovalEntity.ASSET_REVIEWS.value: True,
                        }
                    else:
                        defaults = {}
                    if defaults:
                        self.app_role_repo.update(db=self._db, db_obj=role_db, obj_in={'approval_privileges': defaults})
                        updated_any = True

            if updated_any:
                # Flush once after backfill
                try:
                    self._db.flush()
                except Exception:
                    pass

            return [self._map_db_to_api(role_db) for role_db in roles_db]
        except SQLAlchemyError as e:
            logger.error(f"Database error listing roles: {e}", exc_info=True)
            self._db.rollback()
            return [] # Return empty list on error

    def get_app_role(self, role_id: str) -> Optional[AppRole]:
        """Retrieves a specific application role by ID."""
        try:
            role_db = self.app_role_repo.get(db=self._db, id=role_id)
            if role_db:
                return self._map_db_to_api(role_db)
            return None
        except SQLAlchemyError as e:
            logger.error(f"Database error getting role {role_id}: {e}", exc_info=True)
            self._db.rollback()
            return None

    def get_app_role_by_name(self, role_name: str) -> Optional[AppRole]:
        """Retrieves a specific application role by name."""
        try:
            role_db = self.app_role_repo.get_by_name(db=self._db, name=role_name)
            if role_db:
                return self._map_db_to_api(role_db)
            return None
        except SQLAlchemyError as e:
            logger.error(f"Database error getting role by name '{role_name}': {e}", exc_info=True)
            self._db.rollback()
            return None

    def create_app_role(
        self,
        role: AppRoleCreate,
        user: Optional[str] = None,
        background_tasks: Optional[Any] = None,
    ) -> AppRole:
        """Creates a new application role.
        
        Args:
            role: Role creation data
            user: Username of creator (for delivery tracking)
            background_tasks: Optional FastAPI BackgroundTasks for async delivery
        """
        # Validate name uniqueness
        existing_role = self.get_app_role_by_name(role_name=role.name)
        if existing_role:
            logger.warning(f"Attempted to create role with duplicate name: {role.name}")
            raise ValueError(f"Role with name '{role.name}' already exists.")

        # Validate permissions against allowed levels
        self._validate_permissions(role.feature_permissions)

        try:
            # Pass the Pydantic model directly to the repository
            role_db = self.app_role_repo.create(db=self._db, obj_in=role)
            
            # Handle role hierarchy (requestable_by_roles and approver_roles)
            if hasattr(role, 'requestable_by_roles') and role.requestable_by_roles:
                role_hierarchy_repo.set_requestable_by_roles(
                    self._db, str(role_db.id), role.requestable_by_roles
                )
            if hasattr(role, 'approver_roles') and role.approver_roles:
                role_hierarchy_repo.set_approver_roles(
                    self._db, str(role_db.id), role.approver_roles
                )
            
            # Commit is handled by the request lifecycle or calling function
            # self._db.commit() # Remove commit from manager method
            # self._db.refresh(role_db) # Refresh is handled in repo
            logger.info(f"Successfully created role '{role.name}' with ID {role_db.id}")
            result = self._map_db_to_api(role_db)
            
            # Queue delivery for active modes
            self._queue_role_delivery(
                entity=role_db,
                change_type_name="ROLE_CREATE",
                user=user,
                background_tasks=background_tasks,
            )
            
            return result
        except SQLAlchemyError as e:
            logger.error(f"Database error creating role '{role.name}': {e}", exc_info=True)
            self._db.rollback()
            raise RuntimeError("Failed to create application role due to database error.")
        except Exception as e:
            logger.error(f"Unexpected error creating role '{role.name}': {e}", exc_info=True)
            self._db.rollback()
            raise

    def _validate_permissions(self, permissions: Dict[str, FeatureAccessLevel]):
        """Validates that assigned permission levels are allowed for each feature."""
        feature_config = get_feature_config()
        for feature_id, level in permissions.items():
            if feature_id not in feature_config:
                raise ValueError(f"Invalid feature ID provided in permissions: '{feature_id}'")
            allowed_levels = feature_config[feature_id].get('allowed_levels', [])
            if level not in allowed_levels:
                allowed_str = [lvl.value for lvl in allowed_levels]
                raise ValueError(
                    f"Invalid access level '{level.value}' for feature '{feature_id}'. "
                    f"Allowed levels are: {allowed_str}"
                )

    def _queue_role_delivery(
        self,
        entity: Any,
        change_type_name: str,
        user: Optional[str] = None,
        background_tasks: Optional[Any] = None,
    ) -> bool:
        """Queue delivery for role changes.
        
        Args:
            entity: The role DB object
            change_type_name: Name of change type (ROLE_CREATE, ROLE_UPDATE, ROLE_DELETE)
            user: User who made the change
            background_tasks: FastAPI BackgroundTasks for async execution
            
        Returns:
            True if delivery was queued, False otherwise
        """
        try:
            from src.controller.delivery_service import (
                get_delivery_service,
                DeliveryPayload,
                DeliveryChangeType,
            )
            
            delivery_service = get_delivery_service()
            
            if not delivery_service or not delivery_service.get_active_modes():
                logger.debug("No active delivery modes, skipping delivery for AppRole")
                return False
            
            # Map change type name to enum
            change_type_map = {
                "ROLE_CREATE": DeliveryChangeType.ROLE_CREATE,
                "ROLE_UPDATE": DeliveryChangeType.ROLE_UPDATE,
                "ROLE_DELETE": DeliveryChangeType.ROLE_DELETE,
            }
            change_type = change_type_map.get(change_type_name)
            if not change_type:
                logger.warning(f"Unknown change type: {change_type_name}")
                return False
            
            entity_id = str(entity.id) if hasattr(entity, 'id') else str(hash(entity))
            
            payload = DeliveryPayload(
                change_type=change_type,
                entity_type="AppRole",
                entity_id=entity_id,
                data={"entity": entity},
                user=user,
            )
            
            if background_tasks:
                background_tasks.add_task(delivery_service.deliver, payload)
                logger.info(f"Queued delivery for AppRole {entity_id}")
            else:
                result = delivery_service.deliver(payload)
                logger.info(f"Delivered AppRole {entity_id}: {result.all_success}")
                
            return True
            
        except Exception as e:
            logger.warning(f"Failed to queue delivery for AppRole: {e}")
            return False

    def update_app_role(
        self,
        role_id: str,
        role_update: AppRoleUpdate,
        user: Optional[str] = None,
        background_tasks: Optional[Any] = None,
    ) -> Optional[AppRole]:
        """Updates an existing application role.
        
        Args:
            role_id: Role ID to update
            role_update: Update data
            user: Username of updater (for delivery tracking)
            background_tasks: Optional FastAPI BackgroundTasks for async delivery
        """
        try:
            role_db = self.app_role_repo.get(db=self._db, id=role_id)
            if not role_db:
                return None

            # Validate name uniqueness if name is being changed
            if role_update.name is not None and role_update.name != role_db.name:
                existing_role = self.get_app_role_by_name(role_name=role_update.name)
                if existing_role and str(existing_role.id) != role_id:
                    logger.warning(f"Attempted to update role {role_id} with duplicate name: {role_update.name}")
                    raise ValueError(f"Role with name '{role_update.name}' already exists.")

            # Validate permissions if provided
            if role_update.feature_permissions is not None:
                self._validate_permissions(role_update.feature_permissions)

            # Pass the Pydantic model (AppRoleUpdate) directly to the repository update method
            updated_role_db = self.app_role_repo.update(db=self._db, db_obj=role_db, obj_in=role_update)
            
            # Handle role hierarchy updates (requestable_by_roles and approver_roles)
            if hasattr(role_update, 'requestable_by_roles') and role_update.requestable_by_roles is not None:
                role_hierarchy_repo.set_requestable_by_roles(
                    self._db, role_id, role_update.requestable_by_roles
                )
            if hasattr(role_update, 'approver_roles') and role_update.approver_roles is not None:
                role_hierarchy_repo.set_approver_roles(
                    self._db, role_id, role_update.approver_roles
                )
            
            # Commit handled by request lifecycle
            logger.info(f"Successfully updated role (ID: {role_id})")
            result = self._map_db_to_api(updated_role_db)
            
            # Queue delivery for active modes
            self._queue_role_delivery(
                entity=updated_role_db,
                change_type_name="ROLE_UPDATE",
                user=user,
                background_tasks=background_tasks,
            )
            
            return result
        except SQLAlchemyError as e:
            logger.error(f"Database error updating role {role_id}: {e}", exc_info=True)
            self._db.rollback()
            raise RuntimeError(f"Failed to update role {role_id} due to database error.")
        except ValueError as e: # Catch validation errors
             logger.warning(f"Validation error updating role {role_id}: {e}")
             self._db.rollback()
             raise # Re-raise validation errors
        except Exception as e:
            logger.error(f"Unexpected error updating role {role_id}: {e}", exc_info=True)
            self._db.rollback()
            raise

    def delete_app_role(self, role_id: str) -> bool:
        """Deletes an application role by ID."""
        try:
            role_db = self.app_role_repo.get(db=self._db, id=role_id)
            if not role_db:
                logger.warning(f"Attempted to delete non-existent role with ID: {role_id}")
                return False
            
            # Prevent deletion of the default Admin role? (Consider adding logic if needed)
            # if role_db.name == "Admin":
            #    logger.warning("Attempted to delete the default Admin role.")
            #    raise ValueError("Cannot delete the default Admin role.")

            self.app_role_repo.remove(db=self._db, id=role_id)
            # Commit handled by request lifecycle
            # self._db.commit()
            logger.info(f"Successfully deleted role with ID: {role_id}")
            return True
        except SQLAlchemyError as e:
            logger.error(f"Database error deleting role {role_id}: {e}", exc_info=True)
            self._db.rollback()
            raise RuntimeError(f"Failed to delete role {role_id} due to database error.")
        except Exception as e:
            logger.error(f"Unexpected error deleting role {role_id}: {e}", exc_info=True)
            self._db.rollback()
            raise

    def get_requestable_roles_for_user(self, user_groups: Optional[List[str]] = None) -> List[AppRole]:
        """Get list of roles that the user can request based on their current role(s).
        
        Args:
            user_groups: List of groups the user belongs to. If None or empty, returns 
                        roles requestable by users with no role.
        
        Returns:
            List of AppRole objects that the user can request.
        """
        try:
            # First, determine what role(s) the user currently has
            user_role_ids: List[str] = []
            if user_groups:
                all_roles = self.list_app_roles()
                for role in all_roles:
                    if role.assigned_groups:
                        # Check if any of the user's groups match the role's assigned groups
                        if any(group in role.assigned_groups for group in user_groups):
                            user_role_ids.append(str(role.id))
            
            # Get roles requestable based on user's current roles
            requestable_role_ids: set = set()
            
            if not user_role_ids:
                # User has no roles - get roles requestable by __NO_ROLE__
                no_role_requestable = role_hierarchy_repo.get_roles_requestable_by_no_role(self._db)
                requestable_role_ids.update(no_role_requestable)
            else:
                # User has roles - get roles requestable by each of their roles
                for role_id in user_role_ids:
                    roles = role_hierarchy_repo.get_roles_requestable_by_role(self._db, role_id)
                    requestable_role_ids.update(roles)
            
            # Filter out roles the user already has
            requestable_role_ids = requestable_role_ids - set(user_role_ids)
            
            # Get full role objects
            result = []
            for role_id in requestable_role_ids:
                role = self.get_app_role(role_id)
                if role:
                    result.append(role)
            
            logger.debug(f"User with groups {user_groups} can request {len(result)} roles")
            return result
            
        except Exception as e:
            logger.error(f"Error getting requestable roles for user: {e}", exc_info=True)
            return []

    def get_approver_role_names(self, role_id: str) -> List[str]:
        """Get list of role names that can approve access to the given role.
        
        Args:
            role_id: ID of the role being requested
            
        Returns:
            List of role names that can approve access requests for this role.
        """
        try:
            approver_role_ids = role_hierarchy_repo.get_approver_roles(self._db, role_id)
            approver_names = []
            for approver_id in approver_role_ids:
                role = self.get_app_role(approver_id)
                if role:
                    approver_names.append(role.name)
            return approver_names
        except Exception as e:
            logger.error(f"Error getting approver role names for role {role_id}: {e}", exc_info=True)
            return []

    def can_user_request_role(self, role_id: str, user_groups: Optional[List[str]] = None) -> bool:
        """Check if a user can request a specific role.
        
        Args:
            role_id: ID of the role the user wants to request
            user_groups: List of groups the user belongs to
            
        Returns:
            True if the user can request the role, False otherwise.
        """
        try:
            requestable_roles = self.get_requestable_roles_for_user(user_groups)
            return any(str(role.id) == role_id for role in requestable_roles)
        except Exception as e:
            logger.error(f"Error checking if user can request role {role_id}: {e}", exc_info=True)
            return False

    def handle_role_request_decision(
        self,
        db: Session,
        request_data: 'HandleRoleRequest',
        notifications_manager: 'NotificationsManager',
        change_log_manager: 'ChangeLogManager'
    ) -> Dict[str, str]:
        """Handle admin decision (approve/deny) for a role access request.

        Manages the complete workflow:
        - Validates role exists
        - Logs approval/denial to change log
        - Creates notification for requester
        - Marks original admin notification as handled

        Args:
            db: Database session
            request_data: Request data with requester email, role_id, approved flag, optional message
            notifications_manager: NotificationsManager instance for creating notifications
            change_log_manager: ChangeLogManager instance for logging decisions

        Returns:
            Dict with success message

        Raises:
            ValueError: If role not found
            Exception: For notification/database errors
        """
        from uuid import uuid4
        from datetime import datetime
        from ..models.notifications import Notification, NotificationType

        # 1. Get Role Name (for notification)
        role = self.get_app_role(request_data.role_id)
        if not role:
            raise ValueError(f"Role with ID '{request_data.role_id}' not found")

        role_name = role.name
        logger.info(
            f"Handling role request decision for user '{request_data.requester_email}' "
            f"and role '{role_name}'. Approved: {request_data.approved}"
        )

        # 2. Log decision to change log
        try:
            decision_action = "approved" if request_data.approved else "denied"
            change_log_details = {
                "requester_email": request_data.requester_email,
                "role_name": role_name,
                "role_id": request_data.role_id,
                "decision": decision_action,
                "admin_message": request_data.message
            }

            change_log_manager.log_change_with_details(
                db=db,
                entity_type="role_access_request",
                entity_id=f"{request_data.requester_email}:{request_data.role_id}",
                action=f"request_{decision_action}",
                username="admin",  # Could be enhanced to get actual admin username
                details=change_log_details
            )
            logger.info(f"Logged role request decision to change log: {decision_action}")
        except Exception as e:
            logger.error(f"Failed to log role request decision to change log: {e}", exc_info=True)
            # Don't fail the request if logging fails

        # 3. Log decision (admin feedback only, no actual group assignment)
        if request_data.approved:
            logger.info(
                f"Role request APPROVED for {request_data.requester_email} (Role: {role_name}). "
                f"(Actual group assignment should be handled via external ITSM process)."
            )
        else:
            logger.info(f"Role request DENIED for {request_data.requester_email} (Role: {role_name}).")

        try:
            # 4. Create notification for the requester
            decision_title = f"Role Request {'Approved' if request_data.approved else 'Denied'}"
            decision_subtitle = f"Role: {role_name}"
            decision_description = (
                f"Your request for the role '{role_name}' has been "
                f"{'approved' if request_data.approved else 'denied'}."
                + (f"\n\nAdmin Message: {request_data.message}" if request_data.message else "")
            )
            notification_type = NotificationType.SUCCESS if request_data.approved else NotificationType.WARNING

            # Provide placeholder ID and created_at for Pydantic validation
            placeholder_id = str(uuid4())
            now = datetime.utcnow()

            requester_notification = Notification(
                id=placeholder_id,
                created_at=now,
                type=notification_type,
                title=decision_title,
                subtitle=decision_subtitle,
                description=decision_description,
                recipient=request_data.requester_email,
                can_delete=True
            )

            notifications_manager.create_notification(db=db, notification=requester_notification)
            logger.info(f"Sent decision notification to requester '{request_data.requester_email}'")

            # 5. Mark the original admin notification as handled (read)
            handled_payload = {
                "requester_email": request_data.requester_email,
                "role_id": request_data.role_id
            }

            handled = notifications_manager.handle_actionable_notification(
                db=db,
                action_type="handle_role_request",
                action_payload=handled_payload
            )

            if handled:
                logger.info("Marked original admin notification for role request as handled.")
            else:
                logger.warning("Could not find the original admin notification to mark as handled.")

            return {"message": f"Role request decision processed successfully for {request_data.requester_email}."}

        except Exception as e:
            logger.error(
                f"Error during notification handling for role request "
                f"(Role: {request_data.role_id}, User: {request_data.requester_email}): {e}",
                exc_info=True
            )
            db.rollback()
            raise

    # --- Methods related to workflows and jobs remain unchanged --- 
    # list_installed_workflows, install_workflow, update_workflow, remove_workflow
    # install_job, update_job, remove_job
    # _get_workflow_definition, _find_job_by_name

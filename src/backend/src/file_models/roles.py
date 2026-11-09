"""File model for App Roles YAML serialization."""

import json
from typing import Any, Dict

from .base import FileModel, register_file_model
from src.db_models.settings import AppRoleDb


@register_file_model
class RoleFileModel(FileModel[AppRoleDb]):
    """File model for Application Roles.
    
    All roles are stored in a single YAML file.
    """
    
    ENTITY_TYPE = "AppRole"
    SUBDIRECTORY = "config"
    ONE_FILE_PER_RECORD = False  # All roles in one file
    
    @classmethod
    def get_filename(cls, entity: AppRoleDb = None) -> str:
        """Get the filename for roles."""
        return "roles.yaml"
    
    @classmethod
    def to_yaml_dict(cls, entity: AppRoleDb) -> Dict[str, Any]:
        """Convert AppRole to YAML-serializable dictionary."""
        result: Dict[str, Any] = {
            'name': entity.name,
        }
        
        if entity.description:
            result['description'] = entity.description
        
        # Serialize permissions
        if entity.permissions:
            result['permissions'] = entity.permissions
        
        # Assigned groups
        if entity.assigned_groups:
            result['assignedGroups'] = entity.assigned_groups

        # Features hidden from the role's navigation (#1325); omitted when none
        try:
            hidden = json.loads(getattr(entity, 'hidden_nav_features', None) or '[]')
        except (TypeError, ValueError):
            hidden = []
        if hidden:
            result['hiddenNavFeatures'] = hidden

        return result


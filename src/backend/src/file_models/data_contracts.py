"""File model for Data Contracts YAML serialization."""

from typing import Any, Dict, List, Optional

from .base import FileModel, register_file_model
from src.db_models.data_contracts import DataContractDb


@register_file_model
class DataContractFileModel(FileModel[DataContractDb]):
    """File model for Data Contracts.
    
    Each contract is stored in its own YAML file.
    Filename format: {base_name}-{version}.yaml
    """
    
    ENTITY_TYPE = "DataContract"
    SUBDIRECTORY = "contracts"
    ONE_FILE_PER_RECORD = True
    
    @classmethod
    def get_filename(cls, entity: DataContractDb) -> str:
        """Generate filename for a data contract."""
        # Use base_name if available, otherwise use name
        base = entity.base_name or entity.name or "contract"
        # Sanitize for filesystem
        safe_base = base.lower().replace(' ', '-').replace('/', '-')
        version = entity.version or "draft"
        safe_version = version.replace('.', '-')
        return f"{safe_base}-v{safe_version}.yaml"
    
    @classmethod
    def to_yaml_dict(cls, entity: DataContractDb) -> Dict[str, Any]:
        """Convert DataContract to YAML-serializable dictionary.
        
        Only includes fields needed for CI/CD processing, not full database copy.
        """
        result: Dict[str, Any] = {}
        
        # Core identity
        result['name'] = entity.name
        result['version'] = entity.version
        result['status'] = entity.status
        
        # Domain assignment is polymorphic (entity_domain_associations) and is emitted by the
        # ODCS export path (DomainExportAdapter); it is not available on this session-less
        # YAML serializer.
        if entity.owner_team_id:
            result['ownerTeamId'] = entity.owner_team_id
        if entity.data_product:
            result['dataProduct'] = entity.data_product
        
        # Description
        description = {}
        if entity.description_purpose:
            description['purpose'] = entity.description_purpose
        if entity.description_usage:
            description['usage'] = entity.description_usage
        if entity.description_limitations:
            description['limitations'] = entity.description_limitations
        if description:
            result['description'] = description
        
        # Schema objects (tables/views definitions)
        if entity.schema_objects:
            result['schema'] = cls._serialize_schema_objects(entity.schema_objects)
        
        # Servers (connection info)
        if entity.servers:
            result['servers'] = cls._serialize_servers(entity.servers)
        
        # Roles (access control)
        if entity.roles:
            result['roles'] = cls._serialize_roles(entity.roles)
        
        # SLA properties
        if entity.sla_properties:
            result['sla'] = cls._serialize_sla_properties(entity.sla_properties)
        
        # Custom properties
        if entity.custom_properties:
            result['customProperties'] = cls._serialize_custom_properties(entity.custom_properties)
        
        # Tags
        if entity.tags:
            result['tags'] = [tag.name for tag in entity.tags]
        
        return result
    
    @classmethod
    def _serialize_schema_objects(cls, schema_objects: List) -> List[Dict[str, Any]]:
        """Serialize schema objects (tables/views)."""
        result = []
        for obj in schema_objects:
            schema_obj: Dict[str, Any] = {
                'name': obj.name,
                'type': obj.type or 'table',
            }
            if obj.description:
                schema_obj['description'] = obj.description
            if obj.physical_name:
                schema_obj['physicalName'] = obj.physical_name
            
            # Serialize properties (columns)
            if hasattr(obj, 'properties') and obj.properties:
                schema_obj['columns'] = cls._serialize_properties(obj.properties)
            
            result.append(schema_obj)
        return result
    
    @classmethod
    def _serialize_properties(cls, properties: List) -> List[Dict[str, Any]]:
        """Serialize schema properties (columns)."""
        result = []
        for prop in properties:
            col: Dict[str, Any] = {
                'name': prop.name,
                'type': prop.type,
            }
            if prop.description:
                col['description'] = prop.description
            if prop.primary_key:
                col['primaryKey'] = True
            if prop.is_nullable is not None:
                col['nullable'] = prop.is_nullable
            if prop.classification:
                col['classification'] = prop.classification
            
            # Quality rules
            if hasattr(prop, 'quality_rules') and prop.quality_rules:
                col['qualityRules'] = [
                    {'type': rule.type, 'expression': rule.expression}
                    for rule in prop.quality_rules
                ]
            
            result.append(col)
        return result
    
    @classmethod
    def _serialize_servers(cls, servers: List) -> List[Dict[str, Any]]:
        """Serialize server configurations."""
        result = []
        for server in servers:
            srv: Dict[str, Any] = {
                'type': server.type,
            }
            if server.server:
                srv['server'] = server.server
            if server.environment:
                srv['environment'] = server.environment
            if server.description:
                srv['description'] = server.description
            
            # Serialize server properties
            if hasattr(server, 'properties') and server.properties:
                properties = {}
                for prop in server.properties:
                    properties[prop.key] = prop.value
                if properties:
                    srv['properties'] = properties
            
            result.append(srv)
        return result
    
    @classmethod
    def _serialize_roles(cls, roles: List) -> List[Dict[str, Any]]:
        """Serialize role definitions (access control)."""
        result = []
        for role in roles:
            r: Dict[str, Any] = {
                'role': role.role,
            }
            if role.access:
                r['access'] = role.access
            if role.description:
                r['description'] = role.description
            
            # Serialize principals if available
            if hasattr(role, 'principals') and role.principals:
                r['principals'] = [
                    {'name': p.name, 'type': p.type if hasattr(p, 'type') else 'group'}
                    for p in role.principals
                ]
            
            result.append(r)
        return result
    
    @classmethod
    def _serialize_sla_properties(cls, sla_props: List) -> Dict[str, Any]:
        """Serialize SLA properties."""
        sla = {}
        for prop in sla_props:
            sla[prop.property_name] = prop.property_value
        return sla
    
    @classmethod
    def _serialize_custom_properties(cls, custom_props: List) -> Dict[str, Any]:
        """Serialize custom properties."""
        result = {}
        for prop in custom_props:
            result[prop.property_name] = prop.property_value
        return result


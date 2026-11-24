"""File model for Data Products YAML serialization."""

from typing import Any, Dict, List

from sqlalchemy.orm import object_session

from .base import FileModel, register_file_model
from src.db_models.data_products import DataProductDb


@register_file_model
class DataProductFileModel(FileModel[DataProductDb]):
    """File model for Data Products.
    
    Each product is stored in its own YAML file.
    Filename format: {name}-{version}.yaml
    """
    
    ENTITY_TYPE = "DataProduct"
    SUBDIRECTORY = "products"
    ONE_FILE_PER_RECORD = True
    
    @classmethod
    def get_filename(cls, entity: DataProductDb) -> str:
        """Generate filename for a data product."""
        name = entity.name or "product"
        safe_name = name.lower().replace(' ', '-').replace('/', '-')
        version = entity.version or "draft"
        safe_version = version.replace('.', '-')
        return f"{safe_name}-v{safe_version}.yaml"
    
    @classmethod
    def to_yaml_dict(cls, entity: DataProductDb) -> Dict[str, Any]:
        """Convert DataProduct to YAML-serializable dictionary."""
        result: Dict[str, Any] = {}
        
        # Core identity
        result['name'] = entity.name
        result['version'] = entity.version
        result['status'] = entity.status
        
        # Domain assignment is polymorphic (entity_domain_associations) and is emitted by the
        # ODPS export path (DomainExportAdapter); it is not available on this session-less
        # YAML serializer. (Previously this referenced entity.domain_id, which never existed.)
        if entity.owner_team_id:
            result['ownerTeamId'] = entity.owner_team_id
        
        # Description (ODPS structured description: one row per product)
        description = entity.description
        if description:
            parts = {
                'purpose': description.purpose,
                'limitations': description.limitations,
                'usage': description.usage,
            }
            parts = {key: value for key, value in parts.items() if value}
            if parts:
                result['description'] = parts
        
        # Output ports (data contracts exposed)
        if entity.output_ports:
            result['outputPorts'] = cls._serialize_output_ports(entity.output_ports)
        
        # Input ports (dependencies)
        if entity.input_ports:
            result['inputPorts'] = cls._serialize_input_ports(entity.input_ports)
        
        # Tags: assigned through entity_tag_associations, read as the tags manager does
        tags = cls._assigned_tag_names(entity)
        if tags:
            result['tags'] = tags
        
        # Support channels
        if entity.support_channels:
            result['supportChannels'] = [
                {key: value for key, value in {
                    'channel': sc.channel, 'url': sc.url, 'description': sc.description,
                    'tool': sc.tool, 'scope': sc.scope,
                }.items() if value}
                for sc in entity.support_channels
            ]
        
        return result
    
    @staticmethod
    def _assigned_tag_names(entity: DataProductDb) -> List[str]:
        """Fully qualified names of the tags assigned to the product (none when it
        isn't attached to a session)."""
        session = object_session(entity)
        if session is None:
            return []
        from src.repositories.tags_repository import entity_tag_repo
        assigned = entity_tag_repo.get_assigned_tags_for_entity(
            session, entity_id=str(entity.id), entity_type='data_product',
        )
        return sorted(tag.fully_qualified_name for tag in assigned)
    
    @classmethod
    def _serialize_output_ports(cls, ports: List) -> List[Dict[str, Any]]:
        """Serialize output port definitions."""
        result = []
        for port in ports:
            p: Dict[str, Any] = {'name': port.name, 'version': port.version}
            for key, value in (
                ('description', port.description), ('type', port.port_type),
                ('contractId', port.contract_id), ('status', port.status),
                ('assetType', port.asset_type), ('assetIdentifier', port.asset_identifier),
            ):
                if value:
                    p[key] = value
            result.append(p)
        return result
    
    @classmethod
    def _serialize_input_ports(cls, ports: List) -> List[Dict[str, Any]]:
        """Serialize input port definitions."""
        result = []
        for port in ports:
            p: Dict[str, Any] = {
                'name': port.name, 'version': port.version, 'contractId': port.contract_id,
            }
            for key, value in (
                ('assetType', port.asset_type), ('assetIdentifier', port.asset_identifier),
            ):
                if value:
                    p[key] = value
            result.append(p)
        return result

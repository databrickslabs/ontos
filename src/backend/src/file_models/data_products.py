"""File model for Data Products YAML serialization."""

from typing import Any, Dict, List

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
        result['type'] = entity.type
        
        # Domain assignment is polymorphic (entity_domain_associations) and is emitted by the
        # ODPS export path (DomainExportAdapter); it is not available on this session-less
        # YAML serializer. (Previously this referenced entity.domain_id, which never existed.)
        if entity.owner_team_id:
            result['ownerTeamId'] = entity.owner_team_id
        
        # Description
        if entity.descriptions:
            descriptions = {}
            for desc in entity.descriptions:
                if desc.lang and desc.text:
                    descriptions[desc.lang] = desc.text
            if descriptions:
                result['descriptions'] = descriptions
        
        # Output ports (data contracts exposed)
        if entity.output_ports:
            result['outputPorts'] = cls._serialize_output_ports(entity.output_ports)
        
        # Input ports (dependencies)
        if entity.input_ports:
            result['inputPorts'] = cls._serialize_input_ports(entity.input_ports)
        
        # Tags
        if entity.tags:
            result['tags'] = [tag.name for tag in entity.tags]
        
        # Support channels
        if entity.support_channels:
            result['supportChannels'] = [
                {'type': sc.type, 'contact': sc.contact}
                for sc in entity.support_channels
            ]
        
        return result
    
    @classmethod
    def _serialize_output_ports(cls, ports: List) -> List[Dict[str, Any]]:
        """Serialize output port definitions."""
        result = []
        for port in ports:
            p: Dict[str, Any] = {
                'name': port.name,
            }
            if port.description:
                p['description'] = port.description
            if port.contract_id:
                p['contractId'] = port.contract_id
            if port.visibility:
                p['visibility'] = port.visibility
            if port.format:
                p['format'] = port.format
            result.append(p)
        return result
    
    @classmethod
    def _serialize_input_ports(cls, ports: List) -> List[Dict[str, Any]]:
        """Serialize input port definitions."""
        result = []
        for port in ports:
            p: Dict[str, Any] = {
                'name': port.name,
            }
            if port.description:
                p['description'] = port.description
            if port.source_product_id:
                p['sourceProductId'] = port.source_product_id
            if port.source_output_port_id:
                p['sourceOutputPortId'] = port.source_output_port_id
            result.append(p)
        return result


"""
Contract Cloner for Semantic Versioning
Clones data contracts to create new versions while maintaining lineage.
"""

from uuid import uuid4
from typing import Dict, Optional, List
from datetime import datetime
from copy import deepcopy


class ContractCloner:
    """
    Clones data contracts for versioning.

    Features:
    - Clones contract with new ID and version
    - Maintains parent-child relationship
    - Regenerates IDs for all nested entities
    - Preserves structure and content
    - Sets version metadata (version_family_id, parent_contract_id, change_summary)
    """

    def __init__(self):
        pass

    def clone_for_new_version(
        self,
        source_contract_db,
        new_version: str,
        change_summary: Optional[str] = None,
        created_by: Optional[str] = None
    ) -> Dict:
        """
        Clone a contract for a new version.

        Args:
            source_contract_db: Source contract database model
            new_version: New semantic version (e.g., "2.0.0")
            change_summary: Optional summary of changes
            created_by: User creating the new version

        Returns:
            Dict with cloned contract data ready for database insertion
        """
        # Generate new ID for cloned contract
        new_contract_id = str(uuid4())

        # Keep the legacy base_name populated for back-compat (it's not the
        # primary grouping key anymore — version_family_id is — but other
        # readers may still inspect it).
        base_name = self._extract_base_name(source_contract_db.name, source_contract_db.version)

        # The clone inherits the source's family id. Roots (which lacked
        # the column historically) were backfilled in migration j1 to
        # self.id, so source_contract_db.version_family_id is always set.
        family_id = getattr(source_contract_db, 'version_family_id', None) or source_contract_db.id

        # Build cloned contract data. Note: we no longer rewrite `name` to
        # "<base>_v<version>" — the version is its own column, and the
        # human-readable name should stay stable across the family.
        cloned_data = {
            'id': new_contract_id,
            'name': source_contract_db.name,
            'version': new_version,
            'status': 'draft',  # New versions start as draft
            'publication_scope': 'none',

            # Semantic versioning fields
            'parent_contract_id': source_contract_db.id,
            'version_family_id': family_id,
            'base_name': base_name,
            'change_summary': change_summary,

            # Copy metadata
            'kind': source_contract_db.kind,
            'api_version': source_contract_db.api_version,
            'owner_team_id': source_contract_db.owner_team_id,
            'tenant': source_contract_db.tenant,
            'data_product': source_contract_db.data_product,
            'domain_id': source_contract_db.domain_id,
            'project_id': source_contract_db.project_id,

            # Copy descriptions
            'description_usage': source_contract_db.description_usage,
            'description_purpose': source_contract_db.description_purpose,
            'description_limitations': source_contract_db.description_limitations,

            # Copy ODCS fields
            'sla_default_element': source_contract_db.sla_default_element,
            'contract_created_ts': source_contract_db.contract_created_ts,

            # Set timestamps
            'created_by': created_by,
            'updated_by': created_by,
        }

        return cloned_data

    def clone_schema_objects(self, source_schemas: List, new_contract_id: str) -> List[Dict]:
        """
        Clone schema objects for new contract version.

        Args:
            source_schemas: List of source schema objects
            new_contract_id: ID of the new contract

        Returns:
            List of cloned schema dictionaries
        """
        cloned_schemas = []

        for schema in source_schemas:
            new_schema_id = str(uuid4())

            cloned_schema = {
                'id': new_schema_id,
                'contract_id': new_contract_id,
                'name': schema.name,
                'logical_type': schema.logical_type,
                'physical_name': schema.physical_name,
                'data_granularity_description': schema.data_granularity_description,
                'business_name': getattr(schema, 'business_name', None),
                'physical_type': getattr(schema, 'physical_type', None),
                'tags': getattr(schema, 'tags', None),
                'description': getattr(schema, 'description', None),
            }

            # Clone properties for this schema
            if hasattr(schema, 'properties') and schema.properties:
                cloned_schema['properties'] = self.clone_schema_properties(
                    schema.properties, new_schema_id
                )

            # Clone authoritative definitions for this schema
            if hasattr(schema, 'authoritative_defs') and schema.authoritative_defs:
                cloned_schema['authoritative_defs'] = self.clone_authoritative_defs(
                    schema.authoritative_defs, new_schema_id, 'schema'
                )

            cloned_schemas.append(cloned_schema)

        return cloned_schemas

    def clone_schema_properties(self, source_properties: List, new_schema_id: str) -> List[Dict]:
        """
        Clone schema properties.

        Args:
            source_properties: List of source properties
            new_schema_id: ID of the new schema

        Returns:
            List of cloned property dictionaries
        """
        cloned_properties = []

        for prop in source_properties:
            new_prop_id = str(uuid4())

            cloned_prop = {
                'id': new_prop_id,
                'object_id': new_schema_id,
                'name': prop.name,
                'logical_type': prop.logical_type,
                'physical_type': prop.physical_type,
                'required': prop.required,
                'unique': prop.unique,
                'business_name': getattr(prop, 'business_name', None),
                'encrypted_name': getattr(prop, 'encrypted_name', None),
                'critical_data_element': getattr(prop, 'critical_data_element', None),
                'transform_logic': getattr(prop, 'transform_logic', None),
                'transform_source_objects': getattr(prop, 'transform_source_objects', None),
                'transform_description': getattr(prop, 'transform_description', None),
            }

            # Clone authoritative definitions for this property
            if hasattr(prop, 'authoritative_defs') and prop.authoritative_defs:
                cloned_prop['authoritative_defs'] = self.clone_authoritative_defs(
                    prop.authoritative_defs, new_prop_id, 'property'
                )

            cloned_properties.append(cloned_prop)

        return cloned_properties

    def clone_tags(self, source_tags: List, new_contract_id: str) -> List[Dict]:
        """Clone contract tags"""
        return [
            {
                'id': str(uuid4()),
                'contract_id': new_contract_id,
                'name': tag.name
            }
            for tag in source_tags
        ]

    def clone_servers(self, source_servers: List, new_contract_id: str) -> List[Dict]:
        """Clone server configurations"""
        cloned_servers = []

        for server in source_servers:
            new_server_id = str(uuid4())

            cloned_server = {
                'id': new_server_id,
                'contract_id': new_contract_id,
                'server': server.server,
                'type': server.type,
                'description': server.description,
                'environment': server.environment,
            }

            # Clone server properties
            if hasattr(server, 'properties') and server.properties:
                cloned_server['properties'] = [
                    {
                        'id': str(uuid4()),
                        'server_id': new_server_id,
                        'key': prop.key,
                        'value': prop.value
                    }
                    for prop in server.properties
                ]

            cloned_servers.append(cloned_server)

        return cloned_servers

    def clone_roles(self, source_roles: List, new_contract_id: str) -> List[Dict]:
        """Clone contract roles"""
        cloned_roles = []

        for role in source_roles:
            new_role_id = str(uuid4())

            cloned_role = {
                'id': new_role_id,
                'contract_id': new_contract_id,
                'name': role.name,
                'description': role.description,
                'access_type': role.access_type,
                'directory_group': role.directory_group,
                'email': role.email,
            }

            # Clone role properties
            if hasattr(role, 'properties') and role.properties:
                cloned_role['properties'] = [
                    {
                        'id': str(uuid4()),
                        'role_id': new_role_id,
                        'property': prop.property,
                        'value': prop.value
                    }
                    for prop in role.properties
                ]

            cloned_roles.append(cloned_role)

        return cloned_roles

    def clone_team_members(self, source_team: List, new_contract_id: str) -> List[Dict]:
        """Clone team members"""
        return [
            {
                'id': str(uuid4()),
                'contract_id': new_contract_id,
                'email': member.email,
                'role': member.role,
                'user_name': member.user_name,
                'uc_id': member.uc_id
            }
            for member in source_team
        ]

    def clone_support_channels(self, source_support: List, new_contract_id: str) -> List[Dict]:
        """Clone support channels"""
        return [
            {
                'id': str(uuid4()),
                'contract_id': new_contract_id,
                'channel': channel.channel,
                'url': channel.url
            }
            for channel in source_support
        ]

    def clone_pricing(self, source_pricing, new_contract_id: str) -> Optional[Dict]:
        """Clone pricing information"""
        if not source_pricing:
            return None

        return {
            'id': str(uuid4()),
            'contract_id': new_contract_id,
            'price_amount': source_pricing.price_amount,
            'price_currency': source_pricing.price_currency,
            'price_unit': source_pricing.price_unit
        }

    def clone_custom_properties(self, source_props: List, new_contract_id: str) -> List[Dict]:
        """Clone custom properties"""
        return [
            {
                'id': str(uuid4()),
                'contract_id': new_contract_id,
                'property': prop.property,
                'value': prop.value
            }
            for prop in source_props
        ]

    def clone_authoritative_defs(
        self,
        source_defs: List,
        parent_id: str,
        level: str  # 'contract', 'schema', or 'property'
    ) -> List[Dict]:
        """Clone authoritative definitions"""
        cloned_defs = []

        for auth_def in source_defs:
            cloned_def = {
                'id': str(uuid4()),
                'url': auth_def.url,
                'type': auth_def.type
            }

            # Set appropriate parent ID based on level
            if level == 'contract':
                cloned_def['contract_id'] = parent_id
            elif level == 'schema':
                cloned_def['schema_object_id'] = parent_id
            elif level == 'property':
                cloned_def['property_id'] = parent_id

            cloned_defs.append(cloned_def)

        return cloned_defs

    def clone_sla_properties(self, source_sla_props: List, new_contract_id: str) -> List[Dict]:
        """Clone SLA properties"""
        return [
            {
                'id': str(uuid4()),
                'contract_id': new_contract_id,
                'property': prop.property,
                'value': prop.value,
                'value_ext': prop.value_ext,
                'unit': prop.unit,
                'element': prop.element,
                'driver': prop.driver
            }
            for prop in source_sla_props
        ]

    def _extract_base_name(self, name: str, version: str) -> str:
        """
        Extract base name from contract name (remove version suffix).

        Examples:
            "customer_data_v1.0.0", "1.0.0" → "customer_data"
            "sales_report_v2.1.0", "2.1.0" → "sales_report"
            "product_catalog", "1.0.0" → "product_catalog"
        """
        # Try to remove version suffix patterns
        version_patterns = [
            f"_v{version}",
            f"_{version}",
            f"-v{version}",
            f"-{version}",
        ]

        base = name
        for pattern in version_patterns:
            if base.endswith(pattern):
                base = base[:-len(pattern)]
                break

        return base

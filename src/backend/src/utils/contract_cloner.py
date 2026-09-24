"""
Contract Cloner for Semantic Versioning
Clones data contracts to create new versions while maintaining lineage.

The cloner produces plain dictionaries keyed exactly by ORM column names so the
caller (DataContractsManager.clone_contract_for_new_version) can insert them via
``SomeDb(**data)``. It is intentionally field-complete: a clone (used by the
"new version", "personal draft" and "upgrade ODCS version" flows) must not lose
any persisted ODCS data, otherwise round-tripping/upgrading would silently drop
fields (vector/map options, semanticType, context, quality checks, relationships,
etc.).
"""

from uuid import uuid4
from typing import Dict, Optional, List, Tuple


class ContractCloner:
    """
    Clones data contracts for versioning.

    Features:
    - Clones contract with new ID and version
    - Maintains parent-child relationship
    - Regenerates IDs for all nested entities
    - Preserves structure and content (field-complete against the ORM)
    - Sets version metadata (version_family_id, parent_contract_id, change_summary)
    """

    def clone_for_new_version(
        self,
        source_contract_db,
        new_version: str,
        change_summary: Optional[str] = None,
        created_by: Optional[str] = None
    ) -> Dict:
        """
        Clone a contract's top-level metadata for a new version.

        Returns a dict of DataContractDb column values ready for insertion.
        """
        new_contract_id = str(uuid4())

        # Keep the legacy base_name populated for back-compat (it's not the
        # primary grouping key anymore — version_family_id is — but other
        # readers may still inspect it).
        base_name = self._extract_base_name(source_contract_db.name, source_contract_db.version)

        # The clone inherits the source's family id. Roots (which lacked
        # the column historically) were backfilled to self.id, so
        # source_contract_db.version_family_id is always set.
        family_id = getattr(source_contract_db, 'version_family_id', None) or source_contract_db.id

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
            # domain assignment is copied separately via entity_domain_associations
            'project_id': source_contract_db.project_id,

            # Copy descriptions
            'description_usage': source_contract_db.description_usage,
            'description_purpose': source_contract_db.description_purpose,
            'description_limitations': source_contract_db.description_limitations,

            # Copy ODCS top-level fields
            'sla_default_element': source_contract_db.sla_default_element,
            'contract_created_ts': source_contract_db.contract_created_ts,

            # Set audit fields
            'created_by': created_by,
            'updated_by': created_by,
        }

        return cloned_data

    # ------------------------------------------------------------------
    # Schema objects, properties and their children
    # ------------------------------------------------------------------

    def clone_schema_objects(self, source_schemas: List, new_contract_id: str) -> List[Dict]:
        """Clone schema objects (with properties, auth defs, custom properties,
        relationships, quality checks and context) for a new contract version."""
        cloned_schemas = []

        for schema in source_schemas:
            new_schema_id = str(uuid4())

            cloned_schema = {
                'id': new_schema_id,
                'contract_id': new_contract_id,
                'stable_id': getattr(schema, 'stable_id', None),
                'name': schema.name,
                'logical_type': schema.logical_type,
                'physical_name': schema.physical_name,
                'data_granularity_description': schema.data_granularity_description,
                'business_name': getattr(schema, 'business_name', None),
                'physical_type': getattr(schema, 'physical_type', None),
                'tags': getattr(schema, 'tags', None),
                'description': getattr(schema, 'description', None),
            }

            # Properties (with parent hierarchy remap); returns (dicts, old->new id map)
            prop_dicts, prop_id_map = self._clone_properties_with_map(
                getattr(schema, 'properties', None) or [], new_schema_id
            )
            cloned_schema['properties'] = prop_dicts

            # Schema-level authoritative definitions (ORM attr: authoritative_definitions)
            cloned_schema['authoritative_defs'] = self._clone_auth_defs(
                getattr(schema, 'authoritative_definitions', None) or [], new_schema_id, 'schema'
            )

            # Schema-level custom properties
            cloned_schema['custom_properties'] = [
                {
                    'id': str(uuid4()),
                    'schema_object_id': new_schema_id,
                    'stable_id': getattr(cp, 'stable_id', None),
                    'property': cp.property,
                    'value': cp.value,
                }
                for cp in (getattr(schema, 'custom_properties', None) or [])
            ]

            # Schema-level relationships
            cloned_schema['relationships'] = [
                {
                    'id': str(uuid4()),
                    'schema_object_id': new_schema_id,
                    'relationship_type': getattr(rel, 'relationship_type', 'foreignKey'),
                    'from_value': rel.from_value,
                    'to_value': rel.to_value,
                    'custom_properties_json': getattr(rel, 'custom_properties_json', None),
                }
                for rel in (getattr(schema, 'relationships', None) or [])
            ]

            # Quality checks (object-level and property-level; remap property_id)
            cloned_schema['quality_checks'] = self._clone_quality_checks(
                getattr(schema, 'quality_checks', None) or [], new_schema_id, prop_id_map
            )

            # Schema-object-level context (ODCS v3.2.0)
            cloned_schema['context'] = self._clone_context(
                getattr(schema, 'context', None), owner_kind='schema_object', owner_id=new_schema_id
            )

            cloned_schemas.append(cloned_schema)

        return cloned_schemas

    def clone_schema_properties(self, source_properties: List, new_schema_id: str) -> List[Dict]:
        """Clone schema properties (flat list; parent hierarchy remapped).

        Retained as a public method for back-compat; delegates to the mapping
        helper and discards the id map.
        """
        prop_dicts, _ = self._clone_properties_with_map(source_properties, new_schema_id)
        return prop_dicts

    def _clone_properties_with_map(
        self, source_properties: List, new_schema_id: str
    ) -> Tuple[List[Dict], Dict[str, str]]:
        """Clone properties preserving all columns and remapping parent_property_id.

        Returns (list_of_property_dicts, old_property_id -> new_property_id).
        """
        id_map: Dict[str, str] = {}
        # First pass: allocate new ids so parent references can be remapped even
        # if a child appears before its parent in the list.
        for prop in source_properties:
            id_map[prop.id] = str(uuid4())

        cloned_properties: List[Dict] = []
        for prop in source_properties:
            new_prop_id = id_map[prop.id]
            old_parent = getattr(prop, 'parent_property_id', None)
            cloned_prop = {
                'id': new_prop_id,
                'object_id': new_schema_id,
                'stable_id': getattr(prop, 'stable_id', None),
                'parent_property_id': id_map.get(old_parent) if old_parent else None,
                'name': prop.name,
                'logical_type': prop.logical_type,
                'physical_type': prop.physical_type,
                'required': prop.required,
                'unique': prop.unique,
                'primary_key': getattr(prop, 'primary_key', False),
                'partitioned': getattr(prop, 'partitioned', False),
                'primary_key_position': getattr(prop, 'primary_key_position', -1),
                'partition_key_position': getattr(prop, 'partition_key_position', -1),
                'classification': getattr(prop, 'classification', None),
                'encrypted_name': getattr(prop, 'encrypted_name', None),
                'transform_source_objects': getattr(prop, 'transform_source_objects', None),
                'transform_logic': getattr(prop, 'transform_logic', None),
                'transform_description': getattr(prop, 'transform_description', None),
                'examples': getattr(prop, 'examples', None),
                'critical_data_element': getattr(prop, 'critical_data_element', False),
                'logical_type_options_json': getattr(prop, 'logical_type_options_json', None),
                'items_logical_type': getattr(prop, 'items_logical_type', None),
                'business_name': getattr(prop, 'business_name', None),
                'semantic_type': getattr(prop, 'semantic_type', None),
            }

            # Property-level authoritative definitions (ORM attr: authoritative_definitions)
            cloned_prop['authoritative_defs'] = self._clone_auth_defs(
                getattr(prop, 'authoritative_definitions', None) or [], new_prop_id, 'property'
            )

            # Property-level relationships
            cloned_prop['relationships'] = [
                {
                    'id': str(uuid4()),
                    'property_id': new_prop_id,
                    'relationship_type': getattr(rel, 'relationship_type', 'foreignKey'),
                    'to_value': rel.to_value,
                    'custom_properties_json': getattr(rel, 'custom_properties_json', None),
                }
                for rel in (getattr(prop, 'relationships', None) or [])
            ]

            cloned_properties.append(cloned_prop)

        return cloned_properties, id_map

    _QUALITY_SCALAR_FIELDS = (
        'stable_id', 'level', 'name', 'description', 'dimension', 'business_impact',
        'method', 'schedule', 'scheduler', 'severity', 'type', 'unit', 'tags',
        'rule', 'query', 'engine', 'implementation',
        'must_be', 'must_not_be', 'must_be_gt', 'must_be_ge', 'must_be_lt', 'must_be_le',
        'must_be_between_min', 'must_be_between_max', 'must_not_between_min', 'must_not_between_max',
    )

    def _clone_quality_checks(
        self, source_checks: List, new_schema_id: str, prop_id_map: Dict[str, str]
    ) -> List[Dict]:
        cloned = []
        for chk in source_checks:
            data = {
                'id': str(uuid4()),
                'object_id': new_schema_id,
                'property_id': prop_id_map.get(chk.property_id) if getattr(chk, 'property_id', None) else None,
            }
            for f in self._QUALITY_SCALAR_FIELDS:
                data[f] = getattr(chk, f, None)
            # `type` is NOT NULL with a default; guard against None from odd rows.
            if data.get('type') is None:
                data['type'] = 'library'
            cloned.append(data)
        return cloned

    def _clone_context(self, source_context, owner_kind: str, owner_id: str) -> Optional[Dict]:
        """Clone an ODCS v3.2.0 context block (contract- or schema-object-level).

        owner_kind is 'contract' or 'schema_object'; returns a dict with the
        matching owner FK plus nested verified_statements/constraints, or None.
        """
        if not source_context:
            return None
        new_ctx_id = str(uuid4())
        ctx: Dict = {
            'id': new_ctx_id,
            'instructions': getattr(source_context, 'instructions', None),
            'contract_id': owner_id if owner_kind == 'contract' else None,
            'schema_object_id': owner_id if owner_kind == 'schema_object' else None,
        }
        ctx['verified_statements'] = [
            {
                'id': str(uuid4()),
                'context_id': new_ctx_id,
                'stable_id': getattr(vs, 'stable_id', None),
                'question': vs.question,
                'answer': getattr(vs, 'answer', None),
                'position': getattr(vs, 'position', 0),
                'tags_json': getattr(vs, 'tags_json', None),
                'authoritative_definitions_json': getattr(vs, 'authoritative_definitions_json', None),
                'custom_properties_json': getattr(vs, 'custom_properties_json', None),
            }
            for vs in (getattr(source_context, 'verified_statements', None) or [])
        ]
        ctx['constraints'] = [
            {
                'id': str(uuid4()),
                'context_id': new_ctx_id,
                'stable_id': getattr(c, 'stable_id', None),
                'constraint': c.constraint,
                'position': getattr(c, 'position', 0),
                'tags_json': getattr(c, 'tags_json', None),
                'authoritative_definitions_json': getattr(c, 'authoritative_definitions_json', None),
                'custom_properties_json': getattr(c, 'custom_properties_json', None),
            }
            for c in (getattr(source_context, 'constraints', None) or [])
        ]
        return ctx

    def clone_contract_context(self, source_context, new_contract_id: str) -> Optional[Dict]:
        """Clone the contract-level context block for a new contract version."""
        return self._clone_context(source_context, owner_kind='contract', owner_id=new_contract_id)

    def clone_team_metadata(self, source_meta, new_contract_id: str) -> Optional[Dict]:
        """Clone the ODCS v3.1.0 Team object metadata (one row per contract)."""
        if not source_meta:
            return None
        return {
            'id': str(uuid4()),
            'contract_id': new_contract_id,
            'stable_id': getattr(source_meta, 'stable_id', None),
            'name': getattr(source_meta, 'name', None),
            'description': getattr(source_meta, 'description', None),
            'tags_json': getattr(source_meta, 'tags_json', None),
            'custom_properties_json': getattr(source_meta, 'custom_properties_json', None),
            'authoritative_definitions_json': getattr(source_meta, 'authoritative_definitions_json', None),
        }

    # ------------------------------------------------------------------
    # Contract-level child collections
    # ------------------------------------------------------------------

    def clone_tags(self, source_tags: List, new_contract_id: str) -> List[Dict]:
        """Clone contract tags"""
        return [
            {
                'id': str(uuid4()),
                'contract_id': new_contract_id,
                'name': tag.name,
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
                'stable_id': getattr(server, 'stable_id', None),
                'server': server.server,
                'type': server.type,
                'description': server.description,
                'environment': server.environment,
            }
            if getattr(server, 'properties', None):
                cloned_server['properties'] = [
                    {
                        'id': str(uuid4()),
                        'server_id': new_server_id,
                        'key': prop.key,
                        'value': prop.value,
                    }
                    for prop in server.properties
                ]
            cloned_servers.append(cloned_server)
        return cloned_servers

    def clone_roles(self, source_roles: List, new_contract_id: str) -> List[Dict]:
        """Clone contract roles (ORM: role, description, access, approvers)."""
        cloned_roles = []
        for role in source_roles:
            new_role_id = str(uuid4())
            cloned_role = {
                'id': new_role_id,
                'contract_id': new_contract_id,
                'stable_id': getattr(role, 'stable_id', None),
                'role': role.role,
                'description': role.description,
                'access': getattr(role, 'access', None),
                'first_level_approvers': getattr(role, 'first_level_approvers', None),
                'second_level_approvers': getattr(role, 'second_level_approvers', None),
            }
            # Role custom properties (ORM: DataContractRolePropertyDb.property/value)
            if getattr(role, 'custom_properties', None):
                cloned_role['properties'] = [
                    {
                        'id': str(uuid4()),
                        'role_id': new_role_id,
                        'property': prop.property,
                        'value': prop.value,
                    }
                    for prop in role.custom_properties
                ]
            cloned_roles.append(cloned_role)
        return cloned_roles

    def clone_team_members(self, source_team: List, new_contract_id: str) -> List[Dict]:
        """Clone team members (ORM: username, name, role, dates, replaced_by)."""
        return [
            {
                'id': str(uuid4()),
                'contract_id': new_contract_id,
                'stable_id': getattr(member, 'stable_id', None),
                'name': getattr(member, 'name', None),
                'username': member.username,
                'role': getattr(member, 'role', None),
                'description': getattr(member, 'description', None),
                'date_in': getattr(member, 'date_in', None),
                'date_out': getattr(member, 'date_out', None),
                'replaced_by_username': getattr(member, 'replaced_by_username', None),
            }
            for member in source_team
        ]

    def clone_support_channels(self, source_support: List, new_contract_id: str) -> List[Dict]:
        """Clone support channels (ORM: channel, url, description, tool, scope, invitation_url)."""
        return [
            {
                'id': str(uuid4()),
                'contract_id': new_contract_id,
                'stable_id': getattr(channel, 'stable_id', None),
                'channel': channel.channel,
                'url': channel.url,
                'description': getattr(channel, 'description', None),
                'tool': getattr(channel, 'tool', None),
                'scope': getattr(channel, 'scope', None),
                'invitation_url': getattr(channel, 'invitation_url', None),
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
            'price_unit': source_pricing.price_unit,
        }

    def clone_custom_properties(self, source_props: List, new_contract_id: str) -> List[Dict]:
        """Clone contract custom properties"""
        return [
            {
                'id': str(uuid4()),
                'contract_id': new_contract_id,
                'stable_id': getattr(prop, 'stable_id', None),
                'property': prop.property,
                'value': prop.value,
            }
            for prop in source_props
        ]

    def clone_authoritative_defs(
        self,
        source_defs: List,
        parent_id: str,
        level: str  # 'contract', 'schema', or 'property'
    ) -> List[Dict]:
        """Clone authoritative definitions (public wrapper)."""
        return self._clone_auth_defs(source_defs, parent_id, level)

    def _clone_auth_defs(self, source_defs: List, parent_id: str, level: str) -> List[Dict]:
        cloned_defs = []
        for auth_def in source_defs:
            cloned_def = {
                'id': str(uuid4()),
                'stable_id': getattr(auth_def, 'stable_id', None),
                'url': auth_def.url,
                'type': auth_def.type,
            }
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
                'stable_id': getattr(prop, 'stable_id', None),
                'property': prop.property,
                'value': prop.value,
                'value_ext': prop.value_ext,
                'unit': prop.unit,
                'element': prop.element,
                'driver': prop.driver,
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

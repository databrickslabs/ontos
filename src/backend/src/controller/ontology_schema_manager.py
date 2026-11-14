"""Manager that reads the ontos-ontology.ttl RDF graph and exposes
entity type definitions, field schemas, relationship rules, and
hierarchy information for the rest of the application.

Accesses the in-memory ConjunctiveGraph held by SemanticModelsManager
and uses rdflib graph traversal internally (trusted application queries).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING
from urllib.parse import urldefrag

from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL, XSD
from sqlalchemy.orm import Session

from src.models.ontology_schema import (
    AssetTypeSyncResult,
    EntityFieldDefinition,
    EntityHierarchyNode,
    EntityRelationships,
    EntityTypeDefinition,
    EntityTypeSchema,
    RelationshipDefinition,
)
from src.common.logging import get_logger

if TYPE_CHECKING:
    from src.controller.semantic_models_manager import SemanticModelsManager

logger = get_logger(__name__)

ONTOS = Namespace("http://ontos.app/ontology#")
ODCS = Namespace("http://odcs.bitol.io/ontology#")

XSD_TYPE_MAP: Dict[str, str] = {
    str(XSD.string): "string",
    str(XSD.boolean): "boolean",
    str(XSD.integer): "integer",
    str(XSD.int): "integer",
    str(XSD.float): "number",
    str(XSD.double): "number",
    str(XSD.decimal): "number",
    str(XSD.date): "date",
    str(XSD.dateTime): "datetime",
    str(XSD.anyURI): "uri",
}

JSON_SCHEMA_TYPE_MAP: Dict[str, str] = {
    "string": "string",
    "boolean": "boolean",
    "integer": "integer",
    "number": "number",
    "date": "string",
    "datetime": "string",
    "uri": "string",
}

# Built-in asset types the ontology does not define. Retired: hidden from pickers and
# create, still readable, never removed by the sync (#970).
RETIRED_ASSET_TYPES: Dict[str, str] = {
    "Legacy Business Term": "Business terms archived when BusinessTerm left the ontology (#970).",
}


def _local_name(iri: str) -> str:
    """Extract local name from an IRI (fragment or last path segment)."""
    _, frag = urldefrag(iri)
    if frag:
        return frag
    return iri.rsplit("/", 1)[-1] if "/" in iri else iri


def _str_or_none(val) -> Optional[str]:
    return str(val) if val is not None else None


class OntologySchemaManager:
    """Reads the ontology graph and provides structured type/schema/relationship data."""

    def __init__(self, semantic_models_manager: "SemanticModelsManager"):
        self._smm = semantic_models_manager
        logger.info("OntologySchemaManager initialized")

    @property
    def _graph(self) -> Graph:
        return self._smm._graph

    def _get_label(
        self, subject: URIRef, predicate: URIRef = None, lang: Optional[str] = None
    ) -> Optional[str]:
        """Return the best label for *subject* under *predicate*, respecting language.

        Selection order:
        1. A literal whose ``language`` matches *lang* exactly.
        2. An untagged (plain) literal.
        3. The first literal found (any language).
        4. ``None`` (caller should fall back to ``_local_name``).
        """
        if predicate is None:
            predicate = RDFS.label

        all_labels = list(self._graph.objects(subject, predicate))
        if not all_labels:
            return None

        lang_match: Optional[str] = None
        plain: Optional[str] = None
        any_val: Optional[str] = None

        for obj in all_labels:
            val = str(obj)
            if not any_val:
                any_val = val
            if isinstance(obj, Literal):
                if obj.language:
                    if lang and obj.language == lang:
                        lang_match = val
                else:
                    if plain is None:
                        plain = val
            else:
                if plain is None:
                    plain = val

        return lang_match or plain or any_val

    # ------------------------------------------------------------------
    # IRI resolution
    # ------------------------------------------------------------------

    def resolve_type_iri(self, type_iri: str) -> str:
        """Normalize a type IRI that may have been mangled by a reverse proxy.

        Databricks Apps' reverse proxy decodes percent-encoded slashes in
        URL paths and then collapses ``//`` to ``/``, turning
        ``http://`` into ``http:/``.  This helper detects and repairs that.
        It also accepts a bare local name (e.g. ``Table``) and expands it
        to the default ONTOS namespace.
        """
        if "://" in type_iri:
            return type_iri
        if ":/" in type_iri:
            return type_iri.replace(":/", "://", 1)
        return f"{str(ONTOS)}{type_iri}"

    # ------------------------------------------------------------------
    # Entity Types
    # ------------------------------------------------------------------

    BASE_ONTOLOGY_CONTEXT = "urn:taxonomy:ontos-ontology"

    def get_entity_types(
        self,
        tier: Optional[str] = None,
        category: Optional[str] = None,
        persona: Optional[str] = None,
        lang: Optional[str] = None,
    ) -> List[EntityTypeDefinition]:
        """Return all classes that have an ontos:modelTier annotation.

        Only classes defined in the base ontology context are considered,
        so user-uploaded ontologies cannot register new asset types.

        Optionally filter by tier ('dedicated'|'asset'), category, or persona.
        """
        results: List[EntityTypeDefinition] = []

        base_ctx = self._graph.get_context(self.BASE_ONTOLOGY_CONTEXT)
        for cls in base_ctx.subjects(ONTOS.modelTier, None):
            model_tier = _str_or_none(self._graph.value(cls, ONTOS.modelTier))
            if not model_tier:
                continue
            if tier and model_tier != tier:
                continue

            ui_category = _str_or_none(self._graph.value(cls, ONTOS.uiCategory))
            if category and ui_category != category:
                continue

            persona_str = _str_or_none(self._graph.value(cls, ONTOS.uiPersonaVisibility))
            persona_list = [p.strip() for p in persona_str.split(",")] if persona_str else None
            if persona and persona_list and persona not in persona_list:
                continue

            label = self._get_label(cls, RDFS.label, lang) or _local_name(str(cls))
            comment = self._get_label(cls, RDFS.comment, lang) or _str_or_none(self._graph.value(cls, RDFS.comment))

            display_order_val = self._graph.value(cls, ONTOS.uiDisplayOrder)
            display_order = int(str(display_order_val)) if display_order_val is not None else None

            parent_cls = self._graph.value(cls, RDFS.subClassOf)
            parent_label = None
            if parent_cls:
                parent_label = self._get_label(parent_cls, RDFS.label, lang) or _str_or_none(self._graph.value(parent_cls, RDFS.label))

            results.append(EntityTypeDefinition(
                iri=str(cls),
                local_name=_local_name(str(cls)),
                label=label,
                comment=comment,
                model_tier=model_tier,
                ui_icon=_str_or_none(self._graph.value(cls, ONTOS.uiIcon)),
                ui_category=ui_category,
                ui_display_order=display_order,
                persona_visibility=persona_list,
                parent_class=_str_or_none(parent_cls),
                parent_class_label=parent_label,
            ))

        results.sort(key=lambda t: (t.ui_category or "", t.ui_display_order or 999))
        return results

    def get_entity_type(self, type_iri: str) -> Optional[EntityTypeDefinition]:
        """Return a single entity type definition by IRI."""
        types = self.get_entity_types()
        for t in types:
            if t.iri == type_iri:
                return t
        return None

    # ------------------------------------------------------------------
    # Field Schema
    # ------------------------------------------------------------------

    def _get_fields_for_class(self, cls_iri: URIRef, lang: Optional[str] = None) -> List[EntityFieldDefinition]:
        """Collect all data properties whose rdfs:domain includes cls_iri or any ancestor."""
        ancestors = self._get_ancestor_classes(cls_iri)
        target_classes = {cls_iri} | ancestors

        fields: List[EntityFieldDefinition] = []
        seen_iris: set = set()

        for prop in self._graph.subjects(RDF.type, OWL.DatatypeProperty):
            prop_iri = str(prop)
            if prop_iri in seen_iris:
                continue

            domains = set(self._graph.objects(prop, RDFS.domain))
            if not domains & target_classes:
                continue
            seen_iris.add(prop_iri)

            range_val = self._graph.value(prop, RDFS.range)
            range_type = XSD_TYPE_MAP.get(str(range_val), "string") if range_val else "string"

            field_type = _str_or_none(self._graph.value(prop, ONTOS.uiFieldType)) or "text"
            order_val = self._graph.value(prop, ONTOS.uiFieldOrder)
            field_order = int(str(order_val)) if order_val is not None else 100

            required_val = self._graph.value(prop, ONTOS.isRequired)
            is_required = str(required_val).lower() in ("true", "1") if required_val is not None else False

            field_group = _str_or_none(self._graph.value(prop, ONTOS.uiFieldGroup)) or "basic"

            options_str = _str_or_none(self._graph.value(prop, ONTOS.uiSelectOptions))
            select_options = [o.strip() for o in options_str.split(",")] if options_str else None

            label = self._get_label(prop, RDFS.label, lang) or _local_name(prop_iri)
            comment = self._get_label(prop, RDFS.comment, lang) or _str_or_none(self._graph.value(prop, RDFS.comment))

            fields.append(EntityFieldDefinition(
                iri=prop_iri,
                name=_local_name(prop_iri),
                label=label,
                comment=comment,
                range_type=range_type,
                field_type=field_type,
                field_order=field_order,
                is_required=is_required,
                field_group=field_group,
                select_options=select_options,
            ))

        fields.sort(key=lambda f: f.field_order)
        return fields

    def get_entity_type_schema(self, type_iri: str, lang: Optional[str] = None) -> Optional[EntityTypeSchema]:
        """Build a complete field schema for an entity type.

        Returns field definitions and a JSON Schema for validation.
        """
        type_iri = self.resolve_type_iri(type_iri)
        cls = URIRef(type_iri)
        model_tier = _str_or_none(self._graph.value(cls, ONTOS.modelTier))
        if not model_tier:
            return None

        label = self._get_label(cls, RDFS.label, lang) or _local_name(type_iri)
        fields = self._get_fields_for_class(cls, lang=lang)

        json_schema = self._fields_to_json_schema(type_iri, label, fields)

        return EntityTypeSchema(
            type_iri=type_iri,
            type_label=label,
            model_tier=model_tier,
            fields=fields,
            json_schema=json_schema,
        )

    @staticmethod
    def _fields_to_json_schema(
        type_iri: str, label: str, fields: List[EntityFieldDefinition]
    ) -> Dict[str, Any]:
        """Convert field definitions to a JSON Schema object."""
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for f in fields:
            prop: Dict[str, Any] = {
                "type": JSON_SCHEMA_TYPE_MAP.get(f.range_type, "string"),
                "title": f.label,
            }
            if f.comment:
                prop["description"] = f.comment
            if f.select_options:
                prop["enum"] = f.select_options
            if f.range_type == "date":
                prop["format"] = "date"
            elif f.range_type == "datetime":
                prop["format"] = "date-time"
            elif f.range_type == "uri":
                prop["format"] = "uri"

            properties[f.name] = prop
            if f.is_required:
                required.append(f.name)

        safe_id = type_iri.replace("#", "/")
        schema: Dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": safe_id,
            "title": label,
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    def get_relationships(self, type_iri: str, lang: Optional[str] = None) -> EntityRelationships:
        """Return all outgoing and incoming relationships for an entity type."""
        type_iri = self.resolve_type_iri(type_iri)
        cls = URIRef(type_iri)
        ancestors = self._get_ancestor_classes(cls)
        target_classes = {cls} | ancestors

        outgoing: List[RelationshipDefinition] = []
        incoming: List[RelationshipDefinition] = []

        for prop in self._graph.subjects(RDF.type, OWL.ObjectProperty):
            domains = set(self._graph.objects(prop, RDFS.domain))
            ranges = set(self._graph.objects(prop, RDFS.range))

            ui_label = self._get_label(prop, ONTOS.uiLabel, lang) or _str_or_none(self._graph.value(prop, ONTOS.uiLabel))
            rdfs_label = self._get_label(prop, RDFS.label, lang) or _str_or_none(self._graph.value(prop, RDFS.label))
            label = ui_label or rdfs_label or _local_name(str(prop))
            inverse_label = _str_or_none(self._graph.value(prop, ONTOS.inverseLabel))
            cardinality = _str_or_none(self._graph.value(prop, ONTOS.cardinality)) or "0..*"
            display_ctx = _str_or_none(self._graph.value(prop, ONTOS.uiDisplayContext)) or "tab"

            if domains & target_classes:
                for rng in ranges:
                    rng_label = self._get_label(rng, RDFS.label, lang) or _str_or_none(self._graph.value(rng, RDFS.label))
                    outgoing.append(RelationshipDefinition(
                        property_iri=str(prop),
                        property_name=_local_name(str(prop)),
                        label=label,
                        inverse_label=inverse_label,
                        source_type_iri=type_iri,
                        source_type_label=self._get_label(cls, RDFS.label, lang),
                        target_type_iri=str(rng),
                        target_type_label=rng_label,
                        cardinality=cardinality,
                        display_context=display_ctx,
                        direction="outgoing",
                    ))

            if ranges & target_classes:
                for dom in domains:
                    dom_label = self._get_label(dom, RDFS.label, lang) or _str_or_none(self._graph.value(dom, RDFS.label))
                    incoming.append(RelationshipDefinition(
                        property_iri=str(prop),
                        property_name=_local_name(str(prop)),
                        label=inverse_label or label,
                        inverse_label=label,
                        source_type_iri=str(dom),
                        source_type_label=dom_label,
                        target_type_iri=type_iri,
                        target_type_label=self._get_label(cls, RDFS.label, lang),
                        cardinality=cardinality,
                        display_context=display_ctx,
                        direction="incoming",
                    ))

        return EntityRelationships(
            type_iri=type_iri,
            outgoing=outgoing,
            incoming=incoming,
        )

    # ------------------------------------------------------------------
    # Hierarchy Relationships (instance-level)
    # ------------------------------------------------------------------

    def get_hierarchy_relationships(self, type_iri: str, lang: Optional[str] = None) -> List[RelationshipDefinition]:
        """Return only outgoing relationships marked ontos:isHierarchical for a given type.

        These define which children an entity of this type can have in the hierarchy browser.
        """
        all_rels = self.get_relationships(type_iri, lang=lang)
        hierarchical: List[RelationshipDefinition] = []

        for rel in all_rels.outgoing:
            prop = URIRef(rel.property_iri)
            is_hier = self._graph.value(prop, ONTOS.isHierarchical)
            if is_hier is not None and str(is_hier).lower() in ("true", "1"):
                hierarchical.append(rel)

        return hierarchical

    def get_hierarchy_relationships_inverse(self, type_iri: str, lang: Optional[str] = None) -> List[RelationshipDefinition]:
        """Return incoming hierarchical relationships (where this type is a child).

        E.g. for System, returns belongsToSystem incoming relationships (Assets that belong to System).
        """
        all_rels = self.get_relationships(type_iri, lang=lang)
        hierarchical: List[RelationshipDefinition] = []

        for rel in all_rels.incoming:
            prop = URIRef(rel.property_iri)
            is_hier = self._graph.value(prop, ONTOS.isHierarchical)
            if is_hier is not None and str(is_hier).lower() in ("true", "1"):
                hierarchical.append(rel)

        return hierarchical

    def get_all_hierarchy_paths(self) -> Dict[str, List[Dict[str, str]]]:
        """Return all hierarchy paths keyed by source type local name.

        Result: {"DataProduct": [{"relationship": "hasDataset", "target_type": "Dataset", "label": "Datasets"}, ...]}
        """
        paths: Dict[str, List[Dict[str, str]]] = {}

        for prop in self._graph.subjects(RDF.type, OWL.ObjectProperty):
            is_hier = self._graph.value(prop, ONTOS.isHierarchical)
            if is_hier is None or str(is_hier).lower() not in ("true", "1"):
                continue

            domains = set(self._graph.objects(prop, RDFS.domain))
            ranges = set(self._graph.objects(prop, RDFS.range))
            label = _str_or_none(self._graph.value(prop, ONTOS.uiLabel)) or _local_name(str(prop))
            inverse_label = _str_or_none(self._graph.value(prop, ONTOS.inverseLabel))

            for dom in domains:
                dom_name = _local_name(str(dom))
                for rng in ranges:
                    rng_name = _local_name(str(rng))
                    entry = {
                        "relationship": _local_name(str(prop)),
                        "target_type": rng_name,
                        "label": label,
                        "inverse_label": inverse_label,
                    }
                    paths.setdefault(dom_name, []).append(entry)

        return paths

    # ------------------------------------------------------------------
    # Class Hierarchy (type-level)
    # ------------------------------------------------------------------

    def get_hierarchy(self, root_iri: Optional[str] = None, lang: Optional[str] = None) -> List[EntityHierarchyNode]:
        """Build the class hierarchy tree.

        If root_iri is given, returns the subtree rooted at that class.
        Otherwise returns the full tree from ontos:Entity.
        """
        if root_iri:
            root = URIRef(self.resolve_type_iri(root_iri))
        else:
            root = ONTOS.Entity

        return [self._build_hierarchy_node(root, lang=lang)]

    def _build_hierarchy_node(self, cls: URIRef, lang: Optional[str] = None) -> EntityHierarchyNode:
        label = self._get_label(cls, RDFS.label, lang) or _local_name(str(cls))
        model_tier = _str_or_none(self._graph.value(cls, ONTOS.modelTier))
        ui_icon = _str_or_none(self._graph.value(cls, ONTOS.uiIcon))

        children: List[EntityHierarchyNode] = []
        for child in self._graph.subjects(RDFS.subClassOf, cls):
            children.append(self._build_hierarchy_node(child, lang=lang))

        children.sort(key=lambda n: n.label)

        return EntityHierarchyNode(
            iri=str(cls),
            label=label,
            model_tier=model_tier,
            ui_icon=ui_icon,
            children=children,
        )

    def _get_ancestor_classes(self, cls: URIRef) -> set:
        """Walk rdfs:subClassOf chain upward, collecting all ancestor IRIs."""
        ancestors: set = set()
        visited: set = set()
        queue = [cls]
        while queue:
            current = queue.pop()
            if current in visited:
                continue
            visited.add(current)
            for parent in self._graph.objects(current, RDFS.subClassOf):
                if isinstance(parent, URIRef):
                    ancestors.add(parent)
                    queue.append(parent)
        return ancestors

    # ------------------------------------------------------------------
    # Asset Type Sync
    # ------------------------------------------------------------------

    def sync_asset_types(self, db: Session) -> AssetTypeSyncResult:
        """Create or update AssetTypeDb entries for every class with modelTier='asset'.

        Derives required_fields and optional_fields JSON Schema from the
        ontology data properties. Uses the existing AssetsManager/repo.
        """
        from src.repositories.assets_repository import asset_type_repo
        from src.models.assets import AssetTypeCreate, AssetTypeUpdate

        result = AssetTypeSyncResult()

        asset_types = self.get_entity_types(tier="asset")
        logger.info(f"Syncing {len(asset_types)} asset types from ontology to database")

        category_map = {
            "data": "data",
            "governance": "system",
            "analytics": "analytics",
            "integration": "integration",
            "system": "system",
        }

        for at in asset_types:
            schema = self.get_entity_type_schema(at.iri)
            fields = schema.fields if schema else []

            required_fields: Dict[str, Any] = {}
            optional_fields: Dict[str, Any] = {}

            for f in fields:
                field_spec = {
                    "type": JSON_SCHEMA_TYPE_MAP.get(f.range_type, "string"),
                    "title": f.label,
                    "field_type": f.field_type,
                    "field_order": f.field_order,
                    "field_group": f.field_group,
                }
                if f.comment:
                    field_spec["description"] = f.comment
                if f.select_options:
                    field_spec["enum"] = f.select_options

                if f.is_required:
                    required_fields[f.name] = field_spec
                else:
                    optional_fields[f.name] = field_spec

            try:
                display_name = at.label or at.local_name

                existing = asset_type_repo.get_by_name(db, name=display_name)

                db_category = category_map.get(at.ui_category or "", "custom")

                if existing:
                    update_data = AssetTypeUpdate(
                        description=at.comment,
                        category=db_category,
                        icon=at.ui_icon,
                        required_fields=required_fields or None,
                        optional_fields=optional_fields or None,
                        is_system=True,
                    )
                    update_fields = update_data.model_dump(exclude_unset=True)
                    if existing.status == "retired":
                        update_fields["status"] = "active"  # the ontology defines it again (#970)
                    asset_type_repo.update(db, db_obj=existing, obj_in=update_fields)
                    db.flush()
                    result.updated.append(display_name)
                    logger.debug(f"Updated asset type: {display_name}")
                else:
                    from src.db_models.assets import AssetTypeDb
                    new_type = AssetTypeDb(
                        name=display_name,
                        description=at.comment,
                        category=db_category,
                        icon=at.ui_icon,
                        required_fields=required_fields or None,
                        optional_fields=optional_fields or None,
                        is_system=True,
                        status="active",
                        created_by="system@ontology-sync",
                    )
                    db.add(new_type)
                    db.flush()
                    result.created.append(display_name)
                    logger.info(f"Created asset type from ontology: {display_name}")

            except Exception as e:
                logger.error(f"Error syncing asset type {at.label}: {e}", exc_info=True)
                result.errors.append(f"{at.label}: {str(e)}")
                db.rollback()

        from src.db_models.assets import AssetTypeDb  # local: the loop above imports it too
        for retired_name, retired_description in RETIRED_ASSET_TYPES.items():
            try:
                retired = asset_type_repo.get_by_name(db, name=retired_name)
                if retired is None:
                    db.add(AssetTypeDb(
                        name=retired_name,
                        description=retired_description,
                        category="system",
                        icon="Archive",
                        is_system=True,
                        status="retired",
                        created_by="system@ontology-sync",
                    ))
                    db.flush()
                    result.created.append(retired_name)
                elif retired.status != "retired":
                    retired.status = "retired"
                    db.flush()
            except Exception as e:
                logger.error(f"Error ensuring retired asset type {retired_name}: {e}", exc_info=True)
                result.errors.append(f"{retired_name}: {str(e)}")
                db.rollback()

        # Remove stale system asset types no longer in ontology. The delete cascades to
        # their assets, so a type that still has assets is kept and retired instead (#970).
        ontology_names = {at.label or at.local_name for at in asset_types} | set(RETIRED_ASSET_TYPES)
        try:
            from src.db_models.assets import AssetDb, AssetTypeDb
            # An empty ontology means the graph did not load: sweep nothing rather than retire every type.
            stale = [] if not asset_types else db.query(AssetTypeDb).filter(
                AssetTypeDb.is_system == True,
                AssetTypeDb.name.notin_(ontology_names),
            ).all()
            removed = 0
            for s in stale:
                in_use = db.query(AssetDb.id).filter(AssetDb.asset_type_id == s.id).first() is not None
                if in_use:
                    if s.status != "retired":
                        logger.warning(
                            f"Ontology no longer defines asset type '{s.name}' but it still has assets; "
                            "keeping it as retired"
                        )
                        s.status = "retired"
                    continue
                logger.info(f"Removing stale system asset type: {s.name}")
                db.delete(s)
                removed += 1
            if removed:
                result.updated.append(f"removed {removed} stale system types")
        except Exception as e:
            logger.warning(f"Error cleaning stale asset types: {e}")

        try:
            db.commit()
            logger.info(
                f"Asset type sync complete: {len(result.created)} created, "
                f"{len(result.updated)} updated, {len(result.errors)} errors"
            )
        except Exception as e:
            logger.error(f"Failed to commit asset type sync: {e}", exc_info=True)
            db.rollback()
            result.errors.append(f"commit failed: {str(e)}")

        return result

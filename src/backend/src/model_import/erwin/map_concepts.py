"""Logical layer of an erwin model → RDF concepts for a knowledge collection.

| erwin                         | RDF                                                     |
|-------------------------------|---------------------------------------------------------|
| Entity                        | owl:Class                                               |
| Attribute (own, not migrated) | owl:DatatypeProperty, rdfs:domain = class, XSD range    |
| Relationship                  | owl:ObjectProperty, domain = parent, range = child      |
| Subtype relationship          | rdfs:subClassOf                                         |
| Domain (not built-in)         | skos:Concept, linked from its properties (erwin:domain) |
| Subject area                  | skos:Collection with skos:member classes                |

Migrated (foreign key) attributes get no property of their own: the
relationship represents them, and contract columns that implement them link
to the parent attribute's property instead (see ``semantic_iri_for_attribute``).

Every resource carries ``ontos:sourceId "erwin:<model id>/<object id>"``.
IRIs are minted from names once; a re-import passes the IRIs already minted
(by source ID) so a rename keeps the IRI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Set

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from src.model_import.erwin.ir import ErwinAttribute, ErwinModel, RelationshipKind
from src.model_import.erwin.types import xsd_range

ONTOS = Namespace("http://ontos.app/ontology#")
ERWIN = Namespace("http://ontos.app/erwin#")


def source_id(model: ErwinModel, object_id: str) -> str:
    return f"erwin:{model.id}/{object_id}"


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s or "unnamed"


def semantic_iri_for_attribute(
    model: ErwinModel, attribute: ErwinAttribute, iri_by_id: Dict[str, str],
) -> Optional[str]:
    """The concept IRI a column implementing ``attribute`` links to.

    Follows the foreign key chain to the attribute that owns the meaning:
    ``ORDERS.CUSTOMER_ID`` means *Customer.customer id*.
    """
    seen: Set[str] = set()
    current = attribute
    while current.parent_attribute_id and current.parent_attribute_id not in seen:
        seen.add(current.id)
        parent = model.attribute(current.parent_attribute_id)
        if parent is None:
            break
        current = parent
    return iri_by_id.get(current.id)


@dataclass
class ConceptMapping:
    graph: Graph
    # erwin object id → IRI, for entities, attributes, relationships, domains
    iri_by_id: Dict[str, str] = field(default_factory=dict)
    counts: Dict[str, int] = field(default_factory=dict)


def map_concepts(
    model: ErwinModel,
    collection_iri: str,
    entity_ids: Optional[Iterable[str]] = None,
    existing_iris: Optional[Dict[str, str]] = None,
) -> ConceptMapping:
    """Build the RDF graph for the logical layer of ``model``.

    ``entity_ids`` restricts the output to those entities (a subject area
    selection); relationships are kept when both ends are selected.
    ``existing_iris`` maps ``ontos:sourceId`` → IRI from earlier imports.
    """
    existing = existing_iris or {}
    selected = set(entity_ids) if entity_ids is not None else {e.id for e in model.entities}
    g = Graph()
    g.bind("ontos", ONTOS)
    g.bind("erwin", ERWIN)
    g.bind("skos", SKOS)
    g.bind("owl", OWL)
    used: Set[str] = set(existing.values())
    iri_by_id: Dict[str, str] = {}
    counts = {"classes": 0, "datatype_properties": 0, "object_properties": 0, "domains": 0,
              "subclass_links": 0, "collections": 0}

    def mint(object_id: str, slug: str) -> URIRef:
        sid = source_id(model, object_id)
        if sid in existing:
            iri = existing[sid]
        else:
            base = f"{collection_iri}/{slug}"
            iri, n = base, 2
            while iri in used:
                iri, n = f"{base}-{n}", n + 1
            used.add(iri)
        iri_by_id[object_id] = iri
        return URIRef(iri)

    def describe(s: URIRef, object_id: str, label: str, definition: Optional[str]) -> None:
        # skos:prefLabel only: re-import versioning rewrites prefLabel, so an
        # rdfs:label copy would go stale and make every later import "modified".
        g.add((s, SKOS.prefLabel, Literal(label)))
        if definition:
            g.add((s, SKOS.definition, Literal(definition)))
        g.add((s, ONTOS.sourceId, Literal(source_id(model, object_id))))

    # Domains used by selected attributes
    used_domain_ids = {
        a.domain_id for e in model.entities if e.id in selected for a in e.attributes if a.domain_id
    }
    for d in model.domains:
        if d.is_builtin or d.id not in used_domain_ids:
            continue
        s = mint(d.id, "domain-" + slugify(d.name))
        g.add((s, RDF.type, SKOS.Concept))
        describe(s, d.id, d.name, d.definition)
        if d.logical_type or d.physical_type:
            g.add((s, ERWIN.baseType, Literal(d.logical_type or d.physical_type)))
        for v in d.valid_values:
            g.add((s, ERWIN.validValue, Literal(v)))
        counts["domains"] += 1

    # Entities and their own attributes
    for e in model.entities:
        if e.id not in selected or e.physical_only or e.is_view:
            continue
        cls = mint(e.id, slugify(e.name))
        g.add((cls, RDF.type, OWL.Class))
        describe(cls, e.id, e.name, e.definition)
        if e.note:
            g.add((cls, SKOS.note, Literal(e.note)))
        if e.physical_name and e.physical_name.lower() != e.name.lower():
            g.add((cls, SKOS.altLabel, Literal(e.physical_name)))
        counts["classes"] += 1

    for e in model.entities:
        if e.id not in iri_by_id:
            continue
        cls = URIRef(iri_by_id[e.id])
        for a in e.attributes:
            if a.physical_only or a.parent_attribute_id:
                continue
            p = mint(a.id, f"{slugify(e.name)}.{slugify(a.name)}")
            g.add((p, RDF.type, OWL.DatatypeProperty))
            describe(p, a.id, a.name, a.definition)
            g.add((p, RDFS.domain, cls))
            domain = model.domain(a.domain_id) if a.domain_id else None
            g.add((p, RDFS.range, xsd_range(
                a.logical_type or (domain.logical_type if domain else None),
                a.physical_type or (domain.physical_type if domain else None),
            )))
            if domain is not None and domain.id in iri_by_id:
                g.add((p, ERWIN.domain, URIRef(iri_by_id[domain.id])))
            if a.physical_name and a.physical_name.lower() != a.name.lower():
                g.add((p, SKOS.altLabel, Literal(a.physical_name)))
            for v in a.valid_values:
                g.add((p, ERWIN.validValue, Literal(v)))
            counts["datatype_properties"] += 1

    # Relationships
    entity_name = {e.id: e.name for e in model.entities}
    for r in model.relationships:
        if r.parent_id not in iri_by_id or r.child_id not in iri_by_id:
            continue
        parent, child = URIRef(iri_by_id[r.parent_id]), URIRef(iri_by_id[r.child_id])
        if r.kind == RelationshipKind.SUBTYPE:
            g.add((child, RDFS.subClassOf, parent))
            counts["subclass_links"] += 1
            continue
        phrase = (r.parent_to_child_phrase or "").strip()
        label = phrase or f"has {entity_name[r.child_id]}"
        p = mint(r.id, f"{slugify(entity_name[r.parent_id])}.{slugify(label)}.{slugify(entity_name[r.child_id])}")
        g.add((p, RDF.type, OWL.ObjectProperty))
        describe(p, r.id, label, r.definition)
        g.add((p, RDFS.domain, parent))
        g.add((p, RDFS.range, child))
        if r.child_to_parent_phrase:
            g.add((p, ERWIN.inverseLabel, Literal(r.child_to_parent_phrase)))
        if r.cardinality:
            g.add((p, ERWIN.cardinality, Literal(r.cardinality)))
        if r.optional is not None:
            g.add((p, ERWIN.optional, Literal(r.optional, datatype=XSD.boolean)))
        g.add((p, ERWIN.relationshipKind, Literal(r.kind.value)))
        counts["object_properties"] += 1

    # Subtype group semantics on the supertype
    for sg in model.subtype_groups:
        if sg.parent_id not in iri_by_id:
            continue
        sup = URIRef(iri_by_id[sg.parent_id])
        if sg.complete is not None:
            g.add((sup, ERWIN.subtypesComplete, Literal(sg.complete, datatype=XSD.boolean)))
        if sg.exclusive is not None:
            g.add((sup, ERWIN.subtypesExclusive, Literal(sg.exclusive, datatype=XSD.boolean)))

    # Subject areas as SKOS collections
    for sa in model.subject_areas:
        members = [iri_by_id[eid] for eid in sa.entity_ids if eid in iri_by_id]
        if not members:
            continue
        c = mint(sa.id, "subject-area-" + slugify(sa.name))
        g.add((c, RDF.type, SKOS.Collection))
        describe(c, sa.id, sa.name, sa.definition)
        for m in members:
            g.add((c, SKOS.member, URIRef(m)))
        counts["collections"] += 1

    return ConceptMapping(graph=g, iri_by_id=iri_by_id, counts=counts)

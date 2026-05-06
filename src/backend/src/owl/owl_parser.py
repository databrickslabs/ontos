"""OWL ontology parser.

Extracted from OntoBricks. Parses Turtle or RDF/XML content into Python
dicts (classes, properties, constraints, axioms, SWRL rules).  Handles
truncated LLM output gracefully.
"""

import json
import re
from typing import Dict, List

from rdflib import BNode, Graph, Namespace, OWL, RDF, RDFS

from src.common.logging import get_logger

logger = get_logger(__name__)

ONTOBRICKS_NS = Namespace("http://ontobricks.com/schema#")


def clean_truncated_turtle(content: str) -> str:
    """Defensively trim incomplete trailing statements from Turtle/N3 content.

    LLM-generated Turtle is often cut off mid-statement (token-limit truncation).
    Feeding such content to rdflib's notation3 parser produces obscure crashes
    (e.g. ``IndexError: string index out of range`` deep inside ``path()``).
    This helper trims trailing lines that do not end a statement (``.``/``]``)
    so the remainder parses cleanly. It is a no-op for content that already
    ends in ``.``, ``]``, or ``>`` (covering Turtle, blank-node-list, and
    RDF/XML closing tags), so it is safe to call on well-formed input.

    Args:
        content: Raw RDF text (typically Turtle).

    Returns:
        The original content if it looks complete, otherwise the longest prefix
        whose last non-blank, non-comment line ends a Turtle statement.
    """
    if not content:
        return content
    content_stripped = content.strip()
    if not content_stripped:
        return content
    if (
        content_stripped.endswith(".")
        or content_stripped.endswith("]")
        or content_stripped.endswith(">")
    ):
        return content

    lines = content_stripped.split("\n")
    while lines and not (
        lines[-1].strip().endswith(".")
        or lines[-1].strip().endswith("]")
        or lines[-1].strip() == ""
        or lines[-1].strip().startswith("#")
    ):
        lines.pop()

    if not lines:
        return content

    cleaned = "\n".join(lines)
    if cleaned != content:
        logger.warning("Content appeared truncated, removed incomplete statements")
    return cleaned


class OntologyParser:
    """Parse OWL ontologies to extract classes and properties."""

    def __init__(self, owl_content: str):
        """Initialize the parser with OWL content.

        Args:
            owl_content: OWL content (Turtle, RDF/XML, etc.)
        """
        self.graph = Graph()

        owl_content = clean_truncated_turtle(owl_content)

        # Try turtle first, then XML
        turtle_error = None
        try:
            self.graph.parse(data=owl_content, format="turtle")
            return
        except Exception as e:
            turtle_error = str(e)

        try:
            self.graph.parse(data=owl_content, format="xml")
            return
        except Exception as xml_error:
            if "@prefix" in owl_content or ":" in owl_content.split("\n")[0]:
                raise ValueError(f"Failed to parse Turtle content: {turtle_error}")
            else:
                raise ValueError(f"Failed to parse OWL content: {xml_error}")

    @staticmethod
    def _to_camel_case(name: str) -> str:
        """Convert a name with spaces/underscores/hyphens to camelCase or PascalCase.

        Preserves the case of the first character:
        - "Contract ID" -> "ContractId" (PascalCase if starts uppercase)
        - "street address" -> "streetAddress" (camelCase if starts lowercase)
        - "first_name" -> "firstName"
        """
        if not name:
            return name

        words = re.split(r"[\s_-]+", name.strip())
        words = [w for w in words if w]

        if not words:
            return name

        if len(words) == 1:
            return words[0]

        is_pascal = words[0][0].isupper()

        if is_pascal:
            return "".join(w.capitalize() for w in words)
        else:
            return words[0].lower() + "".join(w.capitalize() for w in words[1:])

    def _extract_local_name(self, uri: str) -> str:
        """Extract the local name from a URI and ensure camelCase/PascalCase."""
        if not uri:
            return ""
        raw_name = uri.split("#")[-1].split("/")[-1]
        return self._to_camel_case(raw_name)

    def get_classes(self) -> List[Dict[str, str]]:
        """Extract all OWL classes from the ontology.

        Returns:
            List of dicts with 'uri', 'name', 'label', 'comment', 'emoji',
            'parent', 'dashboard', 'dashboardParams', 'dataProperties'
        """
        classes = []

        # Collect DatatypeProperties grouped by domain class
        domain_to_dataprops: Dict[str, list] = {}
        for prop in self.graph.subjects(RDF.type, OWL.DatatypeProperty):
            if isinstance(prop, BNode):
                continue
            prop_uri = str(prop)

            for domain in self.graph.objects(prop, RDFS.domain):
                if isinstance(domain, BNode):
                    continue
                domain_uri = str(domain)

                prop_label = None
                for lbl in self.graph.objects(prop, RDFS.label):
                    prop_label = str(lbl)
                    break

                prop_local_name = self._extract_local_name(prop_uri)

                if domain_uri not in domain_to_dataprops:
                    domain_to_dataprops[domain_uri] = []
                domain_to_dataprops[domain_uri].append(
                    {
                        "name": prop_local_name,
                        "localName": prop_local_name,
                        "label": prop_label or prop_local_name,
                        "uri": prop_uri,
                    }
                )

        for cls in self.graph.subjects(RDF.type, OWL.Class):
            if isinstance(cls, BNode):
                continue

            uri = str(cls)
            name = self._extract_local_name(uri)

            label = None
            for lbl in self.graph.objects(cls, RDFS.label):
                label = str(lbl)
                break

            comment = None
            for cmt in self.graph.objects(cls, RDFS.comment):
                comment = str(cmt)
                break

            emoji = None
            for icon in self.graph.objects(cls, ONTOBRICKS_NS.icon):
                emoji = str(icon)
                break

            dashboard = None
            for dash in self.graph.objects(cls, ONTOBRICKS_NS.dashboard):
                dashboard = str(dash)
                break

            dashboard_params = {}
            for params in self.graph.objects(cls, ONTOBRICKS_NS.dashboardParams):
                try:
                    dashboard_params = json.loads(str(params))
                except (json.JSONDecodeError, ValueError):
                    pass
                break

            parent = None
            for parent_cls in self.graph.objects(cls, RDFS.subClassOf):
                parent_uri = str(parent_cls)
                if not isinstance(parent_cls, BNode) and not parent_uri.endswith("Thing"):
                    parent = self._extract_local_name(parent_uri)
                    break

            data_properties = domain_to_dataprops.get(uri, [])

            classes.append(
                {
                    "uri": uri,
                    "name": name,
                    "label": label or name,
                    "comment": comment or "",
                    "emoji": emoji or "",
                    "parent": parent or "",
                    "dashboard": dashboard or "",
                    "dashboardParams": dashboard_params,
                    "dataProperties": data_properties,
                }
            )

        return sorted(classes, key=lambda x: x["name"])

    def get_properties(self) -> List[Dict[str, str]]:
        """Extract all OWL properties from the ontology.

        Returns:
            List of dicts with 'uri', 'name', 'label', 'comment', 'type', 'domain', 'range'
        """
        properties = []

        prop_types = [
            (OWL.ObjectProperty, "ObjectProperty"),
            (OWL.DatatypeProperty, "DatatypeProperty"),
        ]

        for prop_class, prop_type in prop_types:
            for prop in self.graph.subjects(RDF.type, prop_class):
                if isinstance(prop, BNode):
                    continue

                uri = str(prop)
                name = self._extract_local_name(uri)

                label = None
                for lbl in self.graph.objects(prop, RDFS.label):
                    label = str(lbl)
                    break

                comment = None
                for cmt in self.graph.objects(prop, RDFS.comment):
                    comment = str(cmt)
                    break

                domain = None
                for dom in self.graph.objects(prop, RDFS.domain):
                    domain = self._extract_local_name(str(dom))
                    break

                range_val = None
                for rng in self.graph.objects(prop, RDFS.range):
                    range_val = self._extract_local_name(str(rng))
                    break

                properties.append(
                    {
                        "uri": uri,
                        "name": name,
                        "label": label or name,
                        "comment": comment or "",
                        "type": prop_type,
                        "domain": domain or "",
                        "range": range_val or "",
                    }
                )

        return sorted(properties, key=lambda x: x["name"])

    def get_ontology_info(self) -> Dict[str, str]:
        """Get basic ontology information.

        Returns:
            Dict with 'uri', 'label', 'comment', 'namespace'
        """
        for onto in self.graph.subjects(RDF.type, OWL.Ontology):
            uri = str(onto)

            label = None
            for lbl in self.graph.objects(onto, RDFS.label):
                label = str(lbl)
                break

            comment = None
            for cmt in self.graph.objects(onto, RDFS.comment):
                comment = str(cmt)
                break

            namespace = uri
            if not namespace.endswith("#") and not namespace.endswith("/"):
                namespace = namespace + "#"

            return {
                "uri": uri,
                "label": label or self._extract_local_name(uri) or "Ontology",
                "comment": comment or "",
                "namespace": namespace,
            }

        return {
            "uri": "Unknown",
            "label": "Unknown Ontology",
            "comment": "",
            "namespace": "http://ontos.example.org/ontology#",
        }

    def get_constraints(self) -> List[Dict]:
        """Extract property constraints from the ontology.

        Returns:
            List of constraint dicts with 'type', 'property', 'className', 'value', etc.
        """
        constraints = []

        property_characteristics = [
            (OWL.FunctionalProperty, "functional"),
            (OWL.InverseFunctionalProperty, "inverseFunctional"),
            (OWL.TransitiveProperty, "transitive"),
            (OWL.SymmetricProperty, "symmetric"),
            (OWL.AsymmetricProperty, "asymmetric"),
            (OWL.ReflexiveProperty, "reflexive"),
            (OWL.IrreflexiveProperty, "irreflexive"),
        ]

        for prop_class, constraint_type in property_characteristics:
            for prop in self.graph.subjects(RDF.type, prop_class):
                prop_uri = str(prop)
                if not prop_uri.startswith("_:"):
                    prop_name = self._extract_local_name(prop_uri)
                    constraints.append(
                        {
                            "type": constraint_type,
                            "property": prop_name,
                            "propertyUri": prop_uri,
                        }
                    )

        for cls in self.graph.subjects(RDF.type, OWL.Class):
            cls_uri = str(cls)
            if cls_uri.startswith("_:"):
                continue
            cls_name = self._extract_local_name(cls_uri)

            for restriction in self.graph.objects(cls, RDFS.subClassOf):
                if (restriction, RDF.type, OWL.Restriction) not in self.graph:
                    continue

                prop_uri = None
                for p in self.graph.objects(restriction, OWL.onProperty):
                    prop_uri = str(p)
                    break

                if not prop_uri:
                    continue

                prop_name = self._extract_local_name(prop_uri)

                for card_val in self.graph.objects(restriction, OWL.minCardinality):
                    constraints.append(
                        {
                            "type": "minCardinality",
                            "property": prop_name,
                            "propertyUri": prop_uri,
                            "className": cls_name,
                            "classUri": cls_uri,
                            "cardinalityValue": int(card_val),
                        }
                    )

                for card_val in self.graph.objects(restriction, OWL.maxCardinality):
                    constraints.append(
                        {
                            "type": "maxCardinality",
                            "property": prop_name,
                            "propertyUri": prop_uri,
                            "className": cls_name,
                            "classUri": cls_uri,
                            "cardinalityValue": int(card_val),
                        }
                    )

                for card_val in self.graph.objects(restriction, OWL.cardinality):
                    constraints.append(
                        {
                            "type": "exactCardinality",
                            "property": prop_name,
                            "propertyUri": prop_uri,
                            "className": cls_name,
                            "classUri": cls_uri,
                            "cardinalityValue": int(card_val),
                        }
                    )

                for val_class in self.graph.objects(restriction, OWL.allValuesFrom):
                    val_class_uri = str(val_class)
                    if not val_class_uri.startswith("_:"):
                        constraints.append(
                            {
                                "type": "allValuesFrom",
                                "property": prop_name,
                                "propertyUri": prop_uri,
                                "className": cls_name,
                                "classUri": cls_uri,
                                "valueClass": self._extract_local_name(val_class_uri),
                            }
                        )

                for val_class in self.graph.objects(restriction, OWL.someValuesFrom):
                    val_class_uri = str(val_class)
                    if not val_class_uri.startswith("_:"):
                        constraints.append(
                            {
                                "type": "someValuesFrom",
                                "property": prop_name,
                                "propertyUri": prop_uri,
                                "className": cls_name,
                                "classUri": cls_uri,
                                "valueClass": self._extract_local_name(val_class_uri),
                            }
                        )

                for val in self.graph.objects(restriction, OWL.hasValue):
                    constraints.append(
                        {
                            "type": "hasValue",
                            "property": prop_name,
                            "propertyUri": prop_uri,
                            "className": cls_name,
                            "classUri": cls_uri,
                            "hasValue": str(val),
                        }
                    )

        # OntoBricks value constraints
        for constraint_res in self.graph.subjects(RDF.type, ONTOBRICKS_NS.ValueConstraint):
            constraint_dict: Dict = {"type": "valueCheck"}

            for cls in self.graph.objects(constraint_res, ONTOBRICKS_NS.appliesTo):
                constraint_dict["className"] = self._extract_local_name(str(cls))

            for attr in self.graph.objects(constraint_res, ONTOBRICKS_NS.onAttribute):
                constraint_dict["attributeName"] = str(attr)

            for check_type in self.graph.objects(constraint_res, ONTOBRICKS_NS.checkType):
                constraint_dict["checkType"] = str(check_type)

            for check_val in self.graph.objects(constraint_res, ONTOBRICKS_NS.checkValue):
                constraint_dict["checkValue"] = str(check_val)

            for case_sens in self.graph.objects(constraint_res, ONTOBRICKS_NS.caseSensitive):
                constraint_dict["caseSensitive"] = str(case_sens).lower() == "true"

            if constraint_dict.get("className") and constraint_dict.get("checkType"):
                constraints.append(constraint_dict)

        # OntoBricks global rules
        for rule_res in self.graph.subjects(RDF.type, ONTOBRICKS_NS.GlobalRule):
            for rule_name in self.graph.objects(rule_res, ONTOBRICKS_NS.ruleName):
                constraints.append({"type": "globalRule", "ruleName": str(rule_name)})

        return constraints

    def get_swrl_rules(self) -> List[Dict]:
        """Extract SWRL rules from the ontology.

        Returns:
            List of rule dicts with 'name', 'description', 'antecedent', 'consequent'
        """
        rules = []

        for rule_res in self.graph.subjects(RDF.type, ONTOBRICKS_NS.SWRLRule):
            rule: Dict = {}

            for label in self.graph.objects(rule_res, RDFS.label):
                rule["name"] = str(label)

            for comment in self.graph.objects(rule_res, RDFS.comment):
                rule["description"] = str(comment)

            for ant in self.graph.objects(rule_res, ONTOBRICKS_NS.antecedent):
                rule["antecedent"] = str(ant)

            for cons in self.graph.objects(rule_res, ONTOBRICKS_NS.consequent):
                rule["consequent"] = str(cons)

            if rule.get("name") and rule.get("antecedent") and rule.get("consequent"):
                rules.append(rule)

        return rules

    def get_axioms(self) -> List[Dict]:
        """Extract OWL axioms from the ontology.

        Returns:
            List of axiom dicts with 'type', 'subject', 'objects', etc.
        """
        axioms = []

        # equivalentClass
        for subj in self.graph.subjects(OWL.equivalentClass, None):
            subj_uri = str(subj)
            if subj_uri.startswith("_:"):
                continue
            objects = []
            for obj in self.graph.objects(subj, OWL.equivalentClass):
                obj_uri = str(obj)
                if not obj_uri.startswith("_:"):
                    objects.append(self._extract_local_name(obj_uri))
            if objects:
                axioms.append(
                    {
                        "type": "equivalentClass",
                        "subject": self._extract_local_name(subj_uri),
                        "subjectUri": subj_uri,
                        "objects": objects,
                    }
                )

        # disjointWith
        for subj in self.graph.subjects(OWL.disjointWith, None):
            subj_uri = str(subj)
            if subj_uri.startswith("_:"):
                continue
            objects = []
            for obj in self.graph.objects(subj, OWL.disjointWith):
                obj_uri = str(obj)
                if not obj_uri.startswith("_:"):
                    objects.append(self._extract_local_name(obj_uri))
            if objects:
                axioms.append(
                    {
                        "type": "disjointWith",
                        "subject": self._extract_local_name(subj_uri),
                        "subjectUri": subj_uri,
                        "objects": objects,
                    }
                )

        # inverseOf
        for subj in self.graph.subjects(OWL.inverseOf, None):
            subj_uri = str(subj)
            if subj_uri.startswith("_:"):
                continue
            objects = []
            for obj in self.graph.objects(subj, OWL.inverseOf):
                obj_uri = str(obj)
                if not obj_uri.startswith("_:"):
                    objects.append(self._extract_local_name(obj_uri))
            if objects:
                axioms.append(
                    {
                        "type": "inverseOf",
                        "subject": self._extract_local_name(subj_uri),
                        "subjectUri": subj_uri,
                        "objects": objects,
                    }
                )

        # propertyDisjointWith
        for subj in self.graph.subjects(OWL.propertyDisjointWith, None):
            subj_uri = str(subj)
            if subj_uri.startswith("_:"):
                continue
            objects = []
            for obj in self.graph.objects(subj, OWL.propertyDisjointWith):
                obj_uri = str(obj)
                if not obj_uri.startswith("_:"):
                    objects.append(self._extract_local_name(obj_uri))
            if objects:
                axioms.append(
                    {
                        "type": "disjointProperties",
                        "subject": self._extract_local_name(subj_uri),
                        "subjectUri": subj_uri,
                        "objects": objects,
                    }
                )

        # propertyChainAxiom
        for subj in self.graph.subjects(OWL.propertyChainAxiom, None):
            subj_uri = str(subj)
            if subj_uri.startswith("_:"):
                continue
            for chain_node in self.graph.objects(subj, OWL.propertyChainAxiom):
                chain = self._parse_rdf_list(chain_node)
                if len(chain) >= 2:
                    axioms.append(
                        {
                            "type": "propertyChain",
                            "resultProperty": self._extract_local_name(subj_uri),
                            "resultPropertyUri": subj_uri,
                            "chain": [self._extract_local_name(p) for p in chain],
                        }
                    )

        # unionOf
        for subj in self.graph.subjects(OWL.unionOf, None):
            subj_uri = str(subj)
            if subj_uri.startswith("_:"):
                continue
            for list_node in self.graph.objects(subj, OWL.unionOf):
                members = self._parse_rdf_list(list_node)
                if members:
                    axioms.append(
                        {
                            "type": "unionOf",
                            "subject": self._extract_local_name(subj_uri),
                            "subjectUri": subj_uri,
                            "objects": [self._extract_local_name(m) for m in members],
                        }
                    )

        # intersectionOf
        for subj in self.graph.subjects(OWL.intersectionOf, None):
            subj_uri = str(subj)
            if subj_uri.startswith("_:"):
                continue
            for list_node in self.graph.objects(subj, OWL.intersectionOf):
                members = self._parse_rdf_list(list_node)
                if members:
                    axioms.append(
                        {
                            "type": "intersectionOf",
                            "subject": self._extract_local_name(subj_uri),
                            "subjectUri": subj_uri,
                            "objects": [self._extract_local_name(m) for m in members],
                        }
                    )

        # complementOf
        for subj in self.graph.subjects(OWL.complementOf, None):
            subj_uri = str(subj)
            if subj_uri.startswith("_:"):
                continue
            for obj in self.graph.objects(subj, OWL.complementOf):
                obj_uri = str(obj)
                if not obj_uri.startswith("_:"):
                    axioms.append(
                        {
                            "type": "complementOf",
                            "subject": self._extract_local_name(subj_uri),
                            "subjectUri": subj_uri,
                            "objects": [self._extract_local_name(obj_uri)],
                        }
                    )

        # oneOf (enumeration)
        for subj in self.graph.subjects(OWL.oneOf, None):
            subj_uri = str(subj)
            if subj_uri.startswith("_:"):
                continue
            for list_node in self.graph.objects(subj, OWL.oneOf):
                individuals = self._parse_rdf_list(list_node)
                if individuals:
                    axioms.append(
                        {
                            "type": "oneOf",
                            "subject": self._extract_local_name(subj_uri),
                            "subjectUri": subj_uri,
                            "individuals": [self._extract_local_name(i) for i in individuals],
                        }
                    )

        return axioms

    def _parse_rdf_list(self, node) -> List[str]:
        """Parse an RDF list (collection) and return its items as URIs."""
        from rdflib import RDF as RDF_NS

        items = []
        current = node
        nil_uri = str(RDF_NS.nil)

        while current and str(current) != nil_uri:
            for first in self.graph.objects(current, RDF_NS.first):
                item_uri = str(first)
                if not item_uri.startswith("_:"):
                    items.append(item_uri)

            rest = None
            for r in self.graph.objects(current, RDF_NS.rest):
                rest = r
                break

            current = rest

        return items


# Backward compatibility alias
TaxonomyParser = OntologyParser

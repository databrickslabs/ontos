"""SHACL shapes for Ontos Access Policies (ODRL 2.2 + the Ontos profile). Pure module.

Generated from the Python profile (:mod:`src.common.odrl`) so the shapes never drift from
what the app accepts; ``data/shapes/ontos-odrl-shapes.ttl`` is this output, checked in
(see ``test_odrl_shapes_ttl_in_sync``). The shapes validate policies as RDF — e.g. the
JSON-LD export (``/api/access-policies/policies/{id}/jsonld``) loaded with the ODRL context —
in any SHACL engine (pySHACL, TopBraid, Jena):

* a policy names the Ontos profile, uses a known conflict strategy and has at least one rule;
* every rule has exactly one known action (plain or refined) and, for permissions and
  prohibitions, a target; constraints (also inside logical constraints and collection
  refinements) use known left operands / operators and exactly one right operand;
* duties only on permissions, remedies only on prohibitions;
* Offer rules name the assigner, Agreement rules assigner and assignee (as the app requires).
"""
from functools import lru_cache
from typing import Iterable, List

from src.common import odrl

SHAPES_IRI = "http://ontos.app/odrl/shapes/v1"


def _term(key: str) -> str:
    """Profile key → Turtle name: ``read`` → ``odrl:read``, ``ontos:browse`` → ``ontos:browse``."""
    return key if key.startswith("ontos:") else f"odrl:{key}"


def _list(items: Iterable[str]) -> str:
    return "( " + " ".join(items) + " )"


def _str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@lru_cache(maxsize=1)
def shapes_turtle() -> str:
    """The shapes graph as Turtle (deterministic: sorted terms). Non-recursive shapes only —
    recursion is undefined in SHACL Core — so constraints nested two levels deep inside logical
    constraints are not checked here (the app's validator still checks them)."""
    actions = _list(_term(k) for k in sorted(odrl.ACTIONS))
    operands = _list(_term(k) for k in sorted(odrl.LEFT_OPERANDS))
    operators = _list(f"odrl:{k}" for k in sorted(odrl.OPERATORS))
    conflicts = _list(f"odrl:{k}" for k in odrl.CONFLICT_TERMS)
    types = ", ".join(f"odrl:{t}" for t in ("Policy",) + tuple(odrl.POLICY_TYPES))
    rules_or = " ".join(f"[ sh:path odrl:{k} ; sh:minCount 1 ]" for k in odrl.RULE_KINDS)

    def members(shape: str) -> List[str]:
        # Every member of each logical operand's rdf:List conforms to ``shape``.
        return [f"    sh:property [ sh:path ( odrl:{k} [ sh:zeroOrMorePath rdf:rest ] rdf:first ) ; sh:node {shape} ] ;"
                for k in odrl.LOGICAL_OPERANDS]

    def operand_lists() -> List[str]:
        # ODRL: exactly one logical operand, with at least one member (an empty @list is rdf:nil).
        out = ["    sh:xone ( " + "\n              ".join(
            f"[ sh:path odrl:{k} ; sh:minCount 1 ]" for k in odrl.LOGICAL_OPERANDS) + " ) ;"]
        out += [f"    sh:property [ sh:path odrl:{k} ; sh:maxCount 1 ; sh:not [ sh:hasValue rdf:nil ] ] ;"
                for k in odrl.LOGICAL_OPERANDS]
        return out

    def parties(shape: str, roles: Iterable[str], who: str) -> List[str]:
        lines = [f"{shape} a sh:NodeShape ;"]
        lines += [f"    sh:property [ sh:path odrl:{r} ; sh:minCount 1 ; sh:message {_str(f'{who} names its {r} on every rule')} ] ;"
                  for r in roles]
        lines[-1] = lines[-1][:-2] + " ."
        return lines

    def subrules(duty: str, remedy: str, consequence: str) -> List[str]:
        return [f"    sh:property [ sh:path odrl:duty ; {duty} ] ;",
                f"    sh:property [ sh:path odrl:remedy ; {remedy} ] ;",
                f"    sh:property [ sh:path odrl:consequence ; {consequence} ] ."]

    none = "sh:maxCount 0"
    out: List[str] = [
        "# Ontos Access Policies — SHACL shapes (v1). Generated from src/common/odrl_shacl.py; keep in sync",
        "# (see test_odrl_shapes_ttl_in_sync). Validates ODRL 2.2 policies against the Ontos profile.",
        "@prefix sh: <http://www.w3.org/ns/shacl#> .",
        f"@prefix odrl: <{odrl.ODRL_NS}> .",
        f"@prefix ontos: <{odrl.ONTOS_NS}> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "",
        f"<{SHAPES_IRI}> a owl:Ontology ;",
        '    rdfs:label "Ontos Access Policies SHACL shapes"@en ;',
        f"    owl:imports <{odrl.ONTOS_PROFILE}> .",
        "",
        "ontos:PolicyShape a sh:NodeShape ;",
        f"    sh:targetClass {types} ;",
        "    sh:nodeKind sh:IRI ;",
        "    sh:property [ sh:path odrl:profile ; sh:minCount 1 ;",
        f"        sh:hasValue <{odrl.ONTOS_PROFILE}> ;",
        f"        sh:message {_str('An Ontos access policy declares the Ontos ODRL profile')} ] ;",
        f"    sh:property [ sh:path odrl:conflict ; sh:maxCount 1 ; sh:in {conflicts} ] ;",
        "    sh:property [ sh:path odrl:inheritFrom ; sh:nodeKind sh:IRI ] ;",
        "    sh:property [ sh:path odrl:permission ; sh:node ontos:PermissionShape ] ;",
        "    sh:property [ sh:path odrl:prohibition ; sh:node ontos:ProhibitionShape ] ;",
        "    sh:property [ sh:path odrl:obligation ; sh:node ontos:ObligationShape ] ;",
        f"    sh:or ( {rules_or} ) .",
        "",
        "ontos:ActionShape a sh:NodeShape ;",
        '    rdfs:comment "A profile action, or a refined action whose rdf:value is one."@en ;',
        f"    sh:or ( [ sh:in {actions} ]",
        f"            [ sh:property [ sh:path rdf:value ; sh:minCount 1 ; sh:maxCount 1 ; sh:in {actions} ] ;",
        "              sh:property [ sh:path odrl:refinement ; sh:node ontos:ConstraintShape ] ] ) .",
        "",
        "ontos:CollectionRefShape a sh:NodeShape ;",
        '    rdfs:comment "A party / asset (collection); a refined collection points at its members with odrl:source."@en ;',
        "    sh:property [ sh:path odrl:refinement ; sh:node ontos:ConstraintShape ] ;",
        "    sh:or ( [ sh:path odrl:refinement ; sh:maxCount 0 ] [ sh:path odrl:source ; sh:minCount 1 ] ) .",
        "",
        "ontos:RuleCoreShape a sh:NodeShape ;",
        "    sh:property [ sh:path odrl:action ; sh:minCount 1 ; sh:maxCount 1 ; sh:node ontos:ActionShape ] ;",
        "    sh:property [ sh:path odrl:constraint ; sh:node ontos:ConstraintShape ] ;",
        "    sh:property [ sh:path odrl:target ; sh:node ontos:CollectionRefShape ] ;",
        "    sh:property [ sh:path odrl:assignee ; sh:node ontos:CollectionRefShape ] ;",
        "    sh:property [ sh:path odrl:assigner ; sh:node ontos:CollectionRefShape ] .",
        "",
        "ontos:PermissionShape a sh:NodeShape ;",
        "    sh:node ontos:RuleCoreShape ;",
        f"    sh:property [ sh:path odrl:target ; sh:minCount 1 ; sh:message {_str('A permission names its target asset')} ] ;",
        *subrules("sh:node ontos:DutyShape", none, none),
        "",
        "ontos:ProhibitionShape a sh:NodeShape ;",
        "    sh:node ontos:RuleCoreShape ;",
        f"    sh:property [ sh:path odrl:target ; sh:minCount 1 ; sh:message {_str('A prohibition names its target asset')} ] ;",
        *subrules(none, "sh:node ontos:DutyShape", none),
        "",
        "ontos:ObligationShape a sh:NodeShape ;",
        "    sh:node ontos:RuleCoreShape ;",
        *subrules(none, none, "sh:node ontos:ConsequenceShape"),
        "",
        "ontos:DutyShape a sh:NodeShape ;",
        "    sh:node ontos:RuleCoreShape ;",
        *subrules(none, none, "sh:node ontos:ConsequenceShape"),
        "",
        "ontos:ConsequenceShape a sh:NodeShape ;",
        "    sh:node ontos:RuleCoreShape ;",
        *subrules(none, none, none),
        "",
        "ontos:ConstraintShape a sh:NodeShape ;",
        "    sh:xone ( ontos:AtomicConstraintShape ontos:LogicalConstraintShape ) .",
        "",
        "ontos:AtomicConstraintShape a sh:NodeShape ;",
        f"    sh:property [ sh:path odrl:leftOperand ; sh:minCount 1 ; sh:maxCount 1 ; sh:in {operands} ] ;",
        f"    sh:property [ sh:path odrl:operator ; sh:minCount 1 ; sh:maxCount 1 ; sh:in {operators} ] ;",
        "    sh:xone ( [ sh:path odrl:rightOperand ; sh:minCount 1 ]",
        "              [ sh:path odrl:rightOperandReference ; sh:minCount 1 ] ) .",
        "",
        "ontos:LogicalConstraintShape a sh:NodeShape ;",
        *operand_lists(),
        *members("ontos:MemberConstraintShape"),
        "    sh:property [ sh:path odrl:leftOperand ; sh:maxCount 0 ] .",
        "",
        "ontos:MemberConstraintShape a sh:NodeShape ;",
        '    rdfs:comment "A member of a logical constraint: atomic, or itself logical (one level checked)."@en ;',
        "    sh:xone ( ontos:AtomicConstraintShape",
        "              [ sh:or ( " + " ".join(f"[ sh:path odrl:{k} ; sh:minCount 1 ]" for k in odrl.LOGICAL_OPERANDS) + " ) ] ) .",
        "",
        "ontos:OfferShape a sh:NodeShape ;",
        "    sh:targetClass odrl:Offer ;",
        *[f"    sh:property [ sh:path odrl:{k} ; sh:node ontos:OfferRuleShape ] ;" for k in odrl.RULE_KINDS[:-1]],
        f"    sh:property [ sh:path odrl:{odrl.RULE_KINDS[-1]} ; sh:node ontos:OfferRuleShape ] .",
        "",
        *parties("ontos:OfferRuleShape", ("assigner",), "An Offer"),
        "",
        "ontos:AgreementShape a sh:NodeShape ;",
        "    sh:targetClass odrl:Agreement ;",
        *[f"    sh:property [ sh:path odrl:{k} ; sh:node ontos:AgreementRuleShape ] ;" for k in odrl.RULE_KINDS[:-1]],
        f"    sh:property [ sh:path odrl:{odrl.RULE_KINDS[-1]} ; sh:node ontos:AgreementRuleShape ] .",
        "",
        *parties("ontos:AgreementRuleShape", ("assigner", "assignee"), "An Agreement"),
        "",
    ]
    return "\n".join(out)

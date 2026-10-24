"""Unit tests for the pure ODRL core (src.common.odrl).

Policies mirror examples from the ODRL Information Model 2.2 (W3C Rec), adapted
to the Ontos profile vocabulary.
"""
from datetime import datetime, timezone

from src.common import odrl
from src.common.odrl import AccessRequest, CollectionDef, Resolver


def _req(**kw):
    base = dict(principal="ana@example.com", action="read", asset="uc:main.sales.orders")
    base.update(kw)
    return AccessRequest(**base)


def _pol(doc):
    return odrl.normalize_policy(doc)


# ------------------------------------------------------------- normalization

def test_compact_policy_expands_to_atomic_rules():
    # §2.7.1 Example 28/29: policy-level shared properties are copied into every rule.
    doc = {
        "@type": "Policy", "uid": "p:8888",
        "target": "uc:main.music", "assigner": "org:sony", "action": "read",
        "permission": [{"assignee": "billie@example.com"}, {"assignee": "murphy@example.com"}],
    }
    norm = _pol(doc)
    assert norm["type"] == "Set"
    assert len(norm["permission"]) == 2
    assert all(r["target"] == "uc:main.music" and r["action"] == "read" for r in norm["permission"])


def test_multi_valued_rule_is_atomized():
    # §2.7 Example 26/27: 2 targets x 2 actions -> 4 atomic permissions.
    norm = _pol({"uid": "p", "permission": [{"target": ["uc:a.b", "uc:c.d"], "action": ["read", "modify"]}]})
    assert len(norm["permission"]) == 4


def test_action_refinement_and_typed_literals():
    norm = _pol({"uid": "p", "permission": [{
        "target": "uc:a", "action": [{"rdf:value": {"@id": "odrl:read"}, "refinement": [
            {"leftOperand": "purpose", "operator": "eq", "rightOperand": {"@value": "analytics", "@type": "xsd:string"}}]}],
        "constraint": [{"leftOperand": "dateTime", "operator": "lt",
                        "rightOperand": {"@value": "2030-01-01", "@type": "xsd:date"}}],
    }]})
    r = norm["permission"][0]
    assert r["action"] == "read"
    assert r["action_refinement"][0]["rightOperand"] == "analytics"


def test_term_keys():
    assert odrl.term_key("http://www.w3.org/ns/odrl/2/read") == "read"
    assert odrl.term_key("odrl:read") == "read"
    assert odrl.term_key({"@id": "http://ontos.app/ontology#manage"}) == "ontos:manage"


# --------------------------------------------------------------- validation

def test_validation_rejects_unknown_profile():
    issues = odrl.validate_policy({"uid": "p", "profile": "http://example.com/other",
                                   "permission": [{"target": "uc:a", "action": "read"}]})
    assert any("Unrecognised ODRL profile" in i.message for i in issues)


def test_validation_offer_requires_assigner_and_agreement_requires_assignee():
    offer = odrl.validate_policy({"@type": "Offer", "uid": "p", "permission": [{"target": "uc:a", "action": "read"}]})
    assert any(i.path.endswith("assigner") for i in offer)
    agr = odrl.validate_policy({"@type": "Agreement", "uid": "p",
                                "permission": [{"target": "uc:a", "action": "read", "assigner": "o"}]})
    assert any(i.path.endswith("assignee") for i in agr)


def test_validation_refined_collection_must_use_source():
    issues = odrl.validate_policy({"uid": "p", "permission": [{
        "action": "read",
        "target": {"@type": "AssetCollection", "uid": "c:1",
                   "refinement": [{"leftOperand": "ontos:domain", "operator": "eq", "rightOperand": "Sales"}]},
    }]})
    assert any("must use 'source'" in i.message for i in issues)


def test_validation_unknown_action_and_operand():
    issues = odrl.validate_policy({"uid": "p", "permission": [{
        "target": "uc:a", "action": "teleport",
        "constraint": [{"leftOperand": "moonPhase", "operator": "eq", "rightOperand": "full"}]}]})
    msgs = " ".join(i.message for i in issues)
    assert "Unknown action 'teleport'" in msgs and "Unknown leftOperand 'moonPhase'" in msgs


def test_valid_policy_has_no_errors():
    issues = odrl.validate_policy({"uid": "p", "profile": odrl.ONTOS_PROFILE, "conflict": "prohibit",
                                   "permission": [{"target": "uc:a", "action": "read"}]})
    assert [i for i in issues if i.severity == "error"] == []


# --------------------------------------------------------------- evaluation

def test_included_action_inherits_permission_and_uc_hierarchy():
    # Permission on `use` of a schema covers `read` of a table below it (§2.4 + UC inheritance).
    pol = _pol({"uid": "p", "conflict": "prohibit", "permission": [{"target": "uc:main.sales", "action": "use"}]})
    d = odrl.evaluate([pol], _req())
    assert d.verdict == "allow"
    assert odrl.evaluate([pol], _req(asset="uc:main.hr.people")).verdict == "not_applicable"


def test_conflict_strategies():
    # §2.10: perm / prohibit / invalid on a permission vs prohibition clash.
    base = {"uid": "p", "permission": [{"target": "uc:main.sales", "action": "use"}],
            "prohibition": [{"target": "uc:main.sales.orders", "action": "read"}]}
    assert odrl.evaluate([_pol({**base, "conflict": "perm"})], _req()).verdict == "allow"
    assert odrl.evaluate([_pol({**base, "conflict": "prohibit"})], _req()).verdict == "deny"
    d = odrl.evaluate([_pol(base)], _req())  # spec default: invalid -> void
    assert d.void_policies == ["p"] and d.verdict == "not_applicable"


def test_any_deny_wins_across_policies():
    allow = _pol({"uid": "a", "conflict": "prohibit", "permission": [{"target": "uc:main", "action": "read"}]})
    deny = _pol({"uid": "b", "conflict": "prohibit", "prohibition": [{"target": "uc:main.sales", "action": "read"}]})
    assert odrl.evaluate([allow, deny], _req()).verdict == "deny"


def test_audience_static_and_dynamic_membership():
    analysts = CollectionDef(uid="urn:ontos:audience:analysts", name="Analysts",
                             members=["group:sales-analysts"],
                             refinement=[{"leftOperand": "ontos:businessRole", "operator": "eq", "rightOperand": "Analyst"}])
    resolver = Resolver(audiences={analysts.uid: analysts})
    pol = _pol({"uid": "p", "conflict": "prohibit",
                "permission": [{"target": "uc:main.sales", "action": "read", "assignee": analysts.uid}]})
    ok = _req(principal_groups=["sales-analysts"], principal_attributes={"ontos:businessRole": ["Analyst"]})
    assert odrl.evaluate([pol], ok, resolver).verdict == "allow"
    wrong_role = _req(principal_groups=["sales-analysts"], principal_attributes={"ontos:businessRole": ["Engineer"]})
    assert odrl.evaluate([pol], wrong_role, resolver).verdict == "not_applicable"
    not_member = _req(principal_groups=["finance"], principal_attributes={"ontos:businessRole": ["Analyst"]})
    assert odrl.evaluate([pol], not_member, resolver).verdict == "not_applicable"


def test_asset_collection_refinement_by_domain_and_tag():
    pii = CollectionDef(uid="urn:ontos:asset-collection:pii", name="PII in Sales",
                        members=["uc:main"],
                        refinement=[{"and": None, "logical": "and", "constraints": [
                            {"leftOperand": "ontos:domain", "operator": "eq", "rightOperand": "Sales"},
                            {"leftOperand": "ontos:classification", "operator": "isAnyOf", "rightOperand": ["pii", "confidential"]},
                        ]}])
    resolver = Resolver(asset_collections={pii.uid: pii})
    pol = _pol({"uid": "p", "conflict": "prohibit", "prohibition": [{"target": pii.uid, "action": "use"}],
                "permission": [{"target": "uc:main", "action": "read"}]})
    sensitive = _req(asset_attributes={"ontos:domain": ["Sales"], "ontos:classification": "PII"})
    assert odrl.evaluate([pol], sensitive, resolver).verdict == "deny"
    public = _req(asset_attributes={"ontos:domain": ["Sales"], "ontos:classification": "public"})
    assert odrl.evaluate([pol], public, resolver).verdict == "allow"


def test_datetime_constraint_and_missing_context():
    pol = _pol({"uid": "p", "conflict": "prohibit", "permission": [{
        "target": "uc:main", "action": "read",
        "constraint": [{"leftOperand": "dateTime", "operator": "lteq", "rightOperand": {"@value": "2030-12-31", "@type": "xsd:date"}}]}]})
    early = datetime(2029, 1, 1, tzinfo=timezone.utc)
    late = datetime(2031, 1, 1, tzinfo=timezone.utc)
    assert odrl.evaluate([pol], _req(), now=early).verdict == "allow"
    assert odrl.evaluate([pol], _req(), now=late).verdict == "not_applicable"
    purpose = _pol({"uid": "q", "conflict": "prohibit", "permission": [{
        "target": "uc:main", "action": "read",
        "constraint": [{"leftOperand": "purpose", "operator": "eq", "rightOperand": "analytics"}]}]})
    d = odrl.evaluate([purpose], _req())
    assert d.verdict == "not_applicable"
    assert d.matches[0].effect == "constraint_unmet"
    assert d.matches[0].unenforceable == ["purpose (workflow)"]
    assert odrl.evaluate([purpose], _req(context={"purpose": "analytics"})).verdict == "allow"


def test_duties_make_permission_conditional():
    pol = _pol({"uid": "p", "conflict": "prohibit", "permission": [{
        "target": "uc:main", "action": "read", "duty": [{"action": "ontos:acknowledgeTerms"}]}]})
    d = odrl.evaluate([pol], _req())
    assert d.verdict == "conditional" and d.pending_duties == ["ontos:acknowledgeTerms"]
    assert odrl.evaluate([pol], _req(fulfilled_duties=["ontos:acknowledgeTerms"])).verdict == "allow"


def test_logical_xone():
    pol = _pol({"uid": "p", "conflict": "prohibit", "permission": [{
        "target": "uc:main", "action": "read",
        "constraint": [{"xone": {"@list": [
            {"leftOperand": "spatial", "operator": "eq", "rightOperand": "EU"},
            {"leftOperand": "purpose", "operator": "eq", "rightOperand": "research"}]}}]}]})
    assert odrl.evaluate([pol], _req(context={"spatial": "EU", "purpose": "sales"})).verdict == "allow"
    assert odrl.evaluate([pol], _req(context={"spatial": "EU", "purpose": "research"})).verdict == "not_applicable"


def test_inheritance_merges_rules_and_detects_cycles():
    parent = {"uid": "parent", "conflict": "prohibit",
              "prohibition": [{"target": "uc:main.sales.orders", "action": "read"}]}
    child = _pol({"uid": "child", "inheritFrom": "parent", "conflict": "prohibit",
                  "permission": [{"target": "uc:main", "action": "read"}]})
    merged, errors = odrl.resolve_inheritance(child, {"parent": parent}.get)
    assert errors == [] and len(merged["prohibition"]) == 1
    assert odrl.evaluate([merged], _req()).verdict == "deny"
    loop = _pol({"uid": "a", "inheritFrom": "a", "permission": [{"target": "uc:x", "action": "read"}]})
    _, errs = odrl.resolve_inheritance(loop, {"a": loop}.get)
    assert any("Circular" in e for e in errs)


def test_jsonld_round_trip():
    doc = {"@type": "Set", "uid": "urn:ontos:policy:1", "conflict": "prohibit", "permission": [{
        "target": "uc:main.sales", "action": "read", "assignee": "urn:ontos:audience:analysts",
        "constraint": [{"leftOperand": "purpose", "operator": "eq", "rightOperand": "analytics"}],
        "duty": [{"action": "ontos:acknowledgeTerms"}]}]}
    norm = _pol(doc)
    out = odrl.to_jsonld(uid=norm["uid"], policy_type=norm["type"], conflict=norm["conflict"], rules=norm)
    assert out["profile"] == odrl.ONTOS_PROFILE
    again = _pol(out)
    for k in odrl.RULE_KINDS:
        assert again[k] == norm[k]


def test_index_terms():
    norm = _pol({"uid": "p", "permission": [{"target": "uc:a", "action": "read", "assignee": "group:x"}]})
    assert ("permission", "assignee", "group:x") in odrl.index_terms(norm)


def test_odrl_profile_ttl_in_sync():
    """data/taxonomies/ontos-odrl-profile.ttl must declare every ontos: action/operand of the Python profile."""
    from pathlib import Path

    import rdflib
    from rdflib.namespace import RDF

    ttl = Path(__file__).resolve().parents[2] / "data" / "taxonomies" / "ontos-odrl-profile.ttl"
    g = rdflib.Graph()
    g.parse(ttl.as_posix(), format="turtle")
    ODRL = rdflib.Namespace(odrl.ODRL_NS)
    ONTOS = rdflib.Namespace(odrl.ONTOS_NS)
    actions = {"ontos:" + str(s)[len(odrl.ONTOS_NS):] for s in g.subjects(RDF.type, ODRL.Action)}
    operands = {"ontos:" + str(s)[len(odrl.ONTOS_NS):] for s in g.subjects(RDF.type, ODRL.LeftOperand)}
    assert actions == {k for k in odrl.ACTIONS if k.startswith("ontos:")}
    assert operands == {k for k in odrl.LEFT_OPERANDS if k.startswith("ontos:")}
    for k in actions:
        assert (ONTOS[k.split(":", 1)[1]], ODRL.includedIn, ODRL.use) in g


def test_typed_principal_matches_typed_members():
    aud = CollectionDef(uid="urn:ontos:audience:a", name="A", members=["user:alice@x.com", "group:Eng"])
    r = Resolver(audiences={aud.uid: aud})
    pol = _pol({"uid": "p", "conflict": "prohibit", "permission": [{"target": "uc:main", "action": "read", "assignee": aud.uid}]})
    assert odrl.evaluate([pol], _req(principal="user:Alice@x.com"), r).verdict == "allow"
    assert odrl.evaluate([pol], _req(principal="bob@x.com", principal_groups=["group:eng"]), r).verdict == "allow"


def test_empty_collections_match_nothing():
    empty = CollectionDef(uid="urn:ontos:audience:e", name="Empty")
    r = Resolver(audiences={empty.uid: empty})
    pol = _pol({"uid": "p", "conflict": "prohibit", "permission": [{"target": "uc:main", "action": "read", "assignee": empty.uid}]})
    assert odrl.evaluate([pol], _req(), r).verdict == "not_applicable"
    inline = _pol({"uid": "q", "conflict": "prohibit", "permission": [{
        "target": "uc:main", "action": "read", "assignee": {"@type": "PartyCollection", "members": []}}]})
    assert odrl.evaluate([inline], _req()).verdict == "not_applicable"


def test_unresolved_named_refs_fail_closed_for_prohibitions():
    # Audience without an active version: permissions don't match, prohibitions still apply.
    pol = _pol({"uid": "p", "conflict": "prohibit",
                "permission": [{"target": "uc:main", "action": "read"}],
                "prohibition": [{"target": "uc:main.hr", "action": "read", "assignee": "urn:ontos:audience:gone"}]})
    d = odrl.evaluate([pol], _req(asset="uc:main.hr.salaries"))
    assert d.verdict == "deny" and d.unresolved_refs == ["urn:ontos:audience:gone"]
    grant = _pol({"uid": "g", "conflict": "prohibit", "permission": [
        {"target": "uc:main", "action": "read", "assignee": "urn:ontos:audience:gone"}]})
    assert odrl.evaluate([grant], _req()).verdict == "not_applicable"


def test_normalize_is_idempotent():
    doc = {"uid": "p", "permission": [{
        "target": "uc:a", "action": [{"rdf:value": {"@id": "odrl:read"}, "refinement": [
            {"leftOperand": "purpose", "operator": "eq", "rightOperand": "x"}]}],
        "constraint": [{"xone": {"@list": [
            {"leftOperand": "spatial", "operator": "eq", "rightOperand": "EU"},
            {"leftOperand": "purpose", "operator": "eq", "rightOperand": "y"}]}}]}]}
    once = _pol(doc)
    twice = _pol({"uid": "p", **{k: once[k] for k in odrl.RULE_KINDS}})
    assert twice["permission"] == once["permission"]



def test_offer_permission_is_conditional_not_allow():
    offer = odrl.normalize_policy({"@type": "Offer", "uid": "urn:ontos:policy:o", "conflict": "prohibit",
                                   "permission": [{"target": "uc:main.sales", "action": "read",
                                                   "assigner": "user:owner@x.com"}]})
    d = odrl.evaluate([offer], odrl.AccessRequest(principal="ana@x.com", action="read", asset="uc:main.sales.t"))
    assert d.verdict == odrl.VERDICT_CONDITIONAL and d.pending_duties == [odrl.OFFER_DUTY]

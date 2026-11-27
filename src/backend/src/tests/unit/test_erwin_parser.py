"""erwin XML export → IR (PRD #1718, slice 1 #1719)."""
import io
from pathlib import Path

import pytest

from src.model_import.erwin.builder import entities_in
from src.model_import.erwin.ir import KeyKind, ModelType, RelationshipKind
from src.model_import.erwin.parse import detect_format, parse_erwin
from src.model_import.erwin.xml_reader import ErwinParseError

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "erwin" / "sales_dw_standard.xml"


def _id(name: str) -> str:
    return "{" + name + "}+00000000"


@pytest.fixture(scope="module")
def model():
    with FIXTURE.open("rb") as f:
        return parse_erwin(f)


def _parse(xml: str):
    return parse_erwin(io.BytesIO(xml.encode("utf-8")))


def _wrap(body: str, ns: str = 'xmlns:EMX="http://www.erwin.com/dm/data"', prefix: str = "EMX:") -> str:
    p = prefix
    return (
        f'<?xml version="1.0"?><erwin xmlns="http://www.erwin.com/dm" {ns}>'
        f'<{p}Model id="{{M}}+0" name="m"><{p}ModelProps><{p}Name>m</{p}Name></{p}ModelProps>'
        f"{body}</{p}Model></erwin>"
    )


class TestModel:
    def test_header(self, model):
        assert model.id == _id("M-SALES")
        assert model.name == "Sales DW"
        assert model.model_type == ModelType.LOGICAL_PHYSICAL
        assert model.target_dbms == "Oracle"
        assert model.target_dbms_version == "19"
        assert model.source_format == "erwin_xml"

    def test_entities_and_view(self, model):
        names = [e.name for e in model.entities]
        assert names == [
            "Customer", "Order", "Product", "Order Line", "Party", "Person", "Organization",
            "v_customer_orders",
        ]
        view = model.entity(_id("V-CUST-ORD"))
        assert view.is_view
        assert view.view_sql.startswith("SELECT c.CUSTOMER_ID")
        assert [a.name for a in view.attributes] == ["CUSTOMER_ID", "ORDER_COUNT"]

    def test_entity_properties(self, model):
        order = model.entity(_id("E-ORD"))
        assert order.physical_name == "ORDERS"
        assert order.schema_name == "SALES"
        assert order.definition == "A request by a customer to buy products."
        assert order.note == "Orders older than 10 years are archived."

    def test_attribute_properties(self, model):
        email = model.attribute(_id("A-CUST-EMAIL"))
        assert email.physical_name == "EMAIL_ADDRESS"
        assert email.logical_type == "VARCHAR(255)"
        assert email.physical_type == "VARCHAR2(255)"
        assert email.nullable is True
        assert email.udps == {"Classification": "PII", "Critical Data Element": "true"}
        # Both the numeric code (1) and the name ("Not Null") mean required.
        assert model.attribute(_id("A-CUST-ID")).nullable is False
        assert model.attribute(_id("A-CUST-NAME")).nullable is False
        assert model.attribute(_id("A-CUST-SINCE")).default_value == "SYSDATE"

    def test_logical_only_attribute(self, model):
        note = model.attribute(_id("A-LINE-NOTE"))
        assert note.logical_only
        assert note.physical_name is None

    def test_entity_udps(self, model):
        assert model.entity(_id("E-CUST")).udps == {"Data Owner": "Sales Operations"}
        assert model.udp_names == ["Classification", "Critical Data Element", "Data Owner"]

    def test_keys_in_order(self, model):
        line = model.entity(_id("E-LINE"))
        pk = line.primary_key()
        assert pk.attribute_ids == [_id("A-LINE-ORD"), _id("A-LINE-NO")]
        cust = model.entity(_id("E-CUST"))
        kinds = {k.kind: k.attribute_ids for k in cust.key_groups}
        assert kinds[KeyKind.ALTERNATE] == [_id("A-CUST-EMAIL")]
        assert kinds[KeyKind.INVERSION] == [_id("A-CUST-NAME")]

    def test_domains(self, model):
        status = model.domain(_id("D-STATUS"))
        assert status.valid_values == ["NEW", "SHIPPED", "CANCELLED"]
        assert status.parent_id == _id("D-STRING")
        assert not status.is_builtin
        assert model.domain(_id("D-DEFAULT")).is_builtin
        assert model.domain(_id("D-STRING")).is_builtin
        assert model.attribute(_id("A-ORD-STATUS")).domain_id == _id("D-STATUS")


class TestRelationships:
    def _rel(self, model, rid):
        return next(r for r in model.relationships if r.id == _id(rid))

    def test_codes_and_names(self, model):
        assert self._rel(model, "R-CUST-ORD").kind == RelationshipKind.NON_IDENTIFYING
        assert self._rel(model, "R-ORD-LINE").kind == RelationshipKind.IDENTIFYING
        assert self._rel(model, "R-PARTY-CUST").kind == RelationshipKind.NON_IDENTIFYING

    def test_inferred_kind_is_flagged(self, model):
        r = self._rel(model, "R-PROD-LINE")
        assert r.kind == RelationshipKind.NON_IDENTIFYING
        assert r.kind_inferred
        assert any("inferred" in w for w in model.warnings)

    def test_verb_phrases_and_cardinality(self, model):
        r = self._rel(model, "R-CUST-ORD")
        assert r.parent_to_child_phrase == "places"
        assert r.child_to_parent_phrase == "is placed by"
        assert r.cardinality == "zero_or_more"
        assert self._rel(model, "R-ORD-LINE").cardinality == "one_or_more"
        assert self._rel(model, "R-PARTY-CUST").cardinality == "zero_or_one"

    def test_optionality(self, model):
        assert self._rel(model, "R-CUST-ORD").optional is False
        assert self._rel(model, "R-PARTY-CUST").optional is True

    def test_fk_pairs(self, model):
        assert self._rel(model, "R-ORD-LINE").fk_pairs == [[_id("A-LINE-ORD"), _id("A-ORD-ID")]]

    def test_subtypes(self, model):
        assert self._rel(model, "R-PARTY-PERSON").kind == RelationshipKind.SUBTYPE
        [group] = model.subtype_groups
        assert group.parent_id == _id("E-PARTY")
        assert group.child_ids == [_id("E-PERSON"), _id("E-ORG")]
        assert group.complete is True
        assert group.exclusive is True


class TestSubjectAreas:
    def test_membership(self, model):
        sa = {s.name: s.entity_ids for s in model.subject_areas}
        assert _id("E-CUST") in sa["Sales"] and _id("E-CUST") in sa["Party"]
        assert _id("V-CUST-ORD") in sa["Sales"]

    def test_entities_in(self, model):
        party = next(s for s in model.subject_areas if s.name == "Party")
        assert {e.name for e in entities_in(model, [party.id])} == {
            "Party", "Person", "Organization", "Customer",
        }
        assert len(entities_in(model, None)) == len(model.entities)


class TestNamespacesAndVariants:
    ENTITY = (
        '<{p}Entity_Groups><{p}Entity id="{{E}}+0" name="T"><{p}EntityProps><{p}Name>T</{p}Name>'
        "</{p}EntityProps><{p}Attribute_Groups>"
        '<{p}Attribute id="{{A}}+0" name="c"><{p}AttributeProps><{p}Name>c</{p}Name>'
        "<{p}Physical_Data_Type>INT</{p}Physical_Data_Type></{p}AttributeProps></{p}Attribute>"
        "</{p}Attribute_Groups></{p}Entity></{p}Entity_Groups>"
    )

    def test_default_namespace_without_prefix(self):
        m = _parse(_wrap(self.ENTITY.format(p=""), ns="", prefix=""))
        assert [e.name for e in m.entities] == ["T"]
        assert m.model_type == ModelType.PHYSICAL

    def test_min_info_warns_on_missing_null_option(self):
        m = _parse(_wrap(self.ENTITY.format(p="EMX:")))
        assert m.entities[0].attributes[0].nullable is None
        assert any("Min Info" in w for w in m.warnings)

    def test_dangling_references_are_warnings(self):
        body = self.ENTITY.format(p="EMX:").replace(
            "<EMX:Physical_Data_Type>INT</EMX:Physical_Data_Type>",
            "<EMX:Physical_Data_Type>INT</EMX:Physical_Data_Type>"
            "<EMX:Parent_Domain_Ref>{NOPE}+0</EMX:Parent_Domain_Ref>"
            "<EMX:Parent_Attribute_Ref>{GONE}+0</EMX:Parent_Attribute_Ref>",
        ) + (
            '<EMX:Relationship_Groups><EMX:Relationship id="{R}+0" name="R/1"><EMX:RelationshipProps>'
            "<EMX:Parent_Entity_Ref>{MISSING}+0</EMX:Parent_Entity_Ref>"
            "<EMX:Child_Entity_Ref>{E}+0</EMX:Child_Entity_Ref>"
            "</EMX:RelationshipProps></EMX:Relationship></EMX:Relationship_Groups>"
        )
        m = _parse(_wrap(body))
        attr = m.entities[0].attributes[0]
        assert attr.domain_id is None and attr.parent_attribute_id is None
        assert m.relationships == []
        assert any("dangling" in w for w in m.warnings)
        assert any("unknown entity" in w for w in m.warnings)

    @pytest.mark.parametrize("type_value,name,kind", [
        ("PK", "pk_t", KeyKind.PRIMARY), ("AK2", "uq", KeyKind.ALTERNATE),
        ("Primary Key", "my_key", KeyKind.PRIMARY), ("Alternate Key", "k", KeyKind.ALTERNATE),
        ("Inversion Entry", "k", KeyKind.INVERSION), ("", "XPKT", KeyKind.PRIMARY),
        ("", "XIF3T", KeyKind.FOREIGN),
    ])
    def test_key_group_types(self, type_value, name, kind):
        kg = (
            f'<EMX:Key_Group_Groups><EMX:Key_Group id="{{K}}+0" name="{name}"><EMX:Key_GroupProps>'
            f"<EMX:Name>{name}</EMX:Name><EMX:Key_Group_Type>{type_value}</EMX:Key_Group_Type>"
            "</EMX:Key_GroupProps><EMX:Key_Group_Member_Groups>"
            '<EMX:Key_Group_Member id="{KM}+0"><EMX:Key_Group_MemberProps>'
            "<EMX:Attribute_Ref>{A}+0</EMX:Attribute_Ref></EMX:Key_Group_MemberProps>"
            "</EMX:Key_Group_Member></EMX:Key_Group_Member_Groups></EMX:Key_Group></EMX:Key_Group_Groups>"
        )
        body = self.ENTITY.format(p="EMX:").replace("</EMX:Attribute_Groups>", "</EMX:Attribute_Groups>" + kg)
        [key] = _parse(_wrap(body)).entities[0].key_groups
        assert key.kind == kind
        assert key.attribute_ids == ["{A}+0"]

    def test_empty_model_warns(self):
        m = _parse(_wrap(""))
        assert m.entities == []
        assert any("no entities" in w for w in m.warnings)


class TestRejections:
    def test_billion_laughs_rejected(self):
        xml = (
            '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
            '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
            "<erwin><Model id=\"x\">&lol2;</Model></erwin>"
        )
        with pytest.raises(ErwinParseError, match="not allowed"):
            _parse(xml)

    def test_xxe_rejected(self):
        xml = (
            '<?xml version="1.0"?><!DOCTYPE erwin [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            "<erwin><Model id=\"x\"><ModelProps><Name>&xxe;</Name></ModelProps></Model></erwin>"
        )
        with pytest.raises(ErwinParseError, match="not allowed"):
            _parse(xml)

    def test_not_erwin_root(self):
        with pytest.raises(ErwinParseError, match="Not an erwin XML export"):
            _parse('<?xml version="1.0"?><html><body/></html>')

    def test_no_model(self):
        with pytest.raises(ErwinParseError, match="No <Model>"):
            _parse('<?xml version="1.0"?><erwin/>')

    def test_malformed_xml(self):
        with pytest.raises(ErwinParseError, match="Invalid XML"):
            _parse("<erwin><Model id='x'>")

    def test_json_not_supported_yet(self):
        with pytest.raises(ErwinParseError, match="JSON"):
            _parse('{"model": {}}')

    def test_native_binary_gets_export_hint(self):
        with pytest.raises(ErwinParseError, match="Save As"):
            parse_erwin(io.BytesIO(b"\x00\x01ERWIN binary"))

    @pytest.mark.parametrize("head,fmt", [
        (b"\xef\xbb\xbf<?xml", "xml"), (b"  \n<erwin", "xml"), (b"{", "json"), (b"PK\x03\x04", "unknown"),
    ])
    def test_detect_format(self, head, fmt):
        assert detect_format(head) == fmt

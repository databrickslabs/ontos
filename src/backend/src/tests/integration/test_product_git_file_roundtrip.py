"""The Git (Indirect) delivery file of a data product imports back to the same product.

The file is the product's ODPS export (#1385 review): a stored product is written,
the file is imported as a new product, and both are compared by every stored
column of the product and of its parts (ports, SBOM, input contracts, team,
support, custom properties, tags, domains).
"""
import json
import uuid
from pathlib import Path

import jsonschema
import yaml
from sqlalchemy import inspect as sa_inspect

from src.db_models.data_products import DataProductDb
from src.db_models.delivery_methods import DeliveryMethodDb
from src.db_models.teams import TeamDb
from src.file_models.data_products import DataProductFileModel
from src.repositories.entity_domain_association_repository import entity_domain_repo
from src.repositories.tags_repository import entity_tag_repo

_DATA = Path(__file__).parent.parent / "data" / "odps" / "maximal.odps_v1_0_0.yaml"
_SCHEMA = Path(__file__).parent.parent.parent / "schemas" / "odps-json-schema-v1.0.0.json"

# Keys and timestamps of a row, not fields of the product
_KEYS = {"id", "product_id", "output_port_id", "team_id", "created_at", "updated_at"}
# A new product has its own id and version family
_PRODUCT_KEYS = {"id", "version_family_id", "created_at", "updated_at"}
# The id the imported file had (the source file's, then the first product's), and
# the product's id and domain ids, which every export writes from the product (the
# import keeps them as plain custom properties; the next export writes them again)
_PROVENANCE = {"ontosOriginalId", "ontosEntityId", "ontosDomainId"}


def _columns(row, skip):
    return {
        attr.key: getattr(row, attr.key)
        for attr in sa_inspect(row).mapper.column_attrs if attr.key not in skip
    }


def _rows(rows):
    return sorted((_columns(row, _KEYS) for row in rows), key=repr)


def _stored(session, product_id):
    """Every stored field of a product, its parts included, without its keys."""
    session.expire_all()
    product = session.get(DataProductDb, product_id)
    team = product.team
    return {
        "product": _columns(product, _PRODUCT_KEYS),
        "description": _columns(product.description, _KEYS),
        "authoritative_definitions": _rows(product.authoritative_definitions),
        "custom_properties": [
            cp for cp in _rows(product.custom_properties) if cp["property"] not in _PROVENANCE
        ],
        "input_ports": _rows(product.input_ports),
        "output_ports": sorted((
            {
                **_columns(port, _KEYS),
                "sbom": _rows(port.sbom),
                "input_contracts": _rows(port.input_contracts),
            }
            for port in product.output_ports
        ), key=repr),
        "management_ports": _rows(product.management_ports),
        "support_channels": _rows(product.support_channels),
        "team": {**_columns(team, _KEYS), "members": _rows(team.members)},
        "tags": sorted(
            tag.fully_qualified_name for tag in entity_tag_repo.get_assigned_tags_for_entity(
                session, entity_id=product_id, entity_type="data_product")
        ),
        "domains": sorted(
            (d.domain_id, d.is_primary) for d in entity_domain_repo.get_domains_for_entity(
                session, entity_type="data_product", entity_id=product_id)
        ),
    }


def _upload(client, name, document, **form):
    resp = client.post(
        "/api/data-products/upload",
        files={"files": (name, yaml.safe_dump(document).encode(), "application/x-yaml")},
        data={"create_missing_domains": "true", "adopt_ids": "true", **form},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1, resp.text
    return resp.json()["created_ids"][0]


def _source_document(db_session):
    """The maximal ODPS document, plus the Ontos port fields ODPS has no place for."""
    method = DeliveryMethodDb(name=f"share-{uuid.uuid4().hex[:8]}", category="access")
    team = TeamDb(name=f"team-{uuid.uuid4().hex[:8]}", created_by="a@b.com",
                  updated_by="a@b.com")
    db_session.add_all([method, team])
    db_session.flush()
    document = yaml.safe_load(_DATA.read_bytes())
    document["owner_team_id"] = team.id
    document["outputPorts"][0].update({
        "deliveryMethodId": str(method.id), "assetType": "table",
        "assetIdentifier": "main.sales.orders", "status": "active",
        "server": {"host": "adb.example.com", "catalog": "main"},
        "containsPii": True, "autoApprove": True,
    })
    document["inputPorts"][0].update({"assetType": "table", "assetIdentifier": "main.raw.o"})
    return document


def test_the_git_file_of_a_product_imports_back_to_the_same_stored_product(
    client, db_session,
):
    source_id = _upload(client, "source.yaml", _source_document(db_session))
    source = _stored(db_session, source_id)
    port = source["output_ports"][0]
    assert port["delivery_method_id"] and port["contains_pii"] and port["auto_approve"]
    assert port["server"] and port["sbom"] and port["input_contracts"]
    assert source["tags"] and source["domains"] and source["product"]["owner_team_id"]

    product = db_session.get(DataProductDb, source_id)
    file_document = DataProductFileModel.wrap_as_resource(
        product, DataProductFileModel.to_yaml_dict(product))
    schema = json.loads(_SCHEMA.read_text())
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(file_document)) == []

    copy_id = _upload(client, DataProductFileModel.get_filename(product), file_document,
                      on_duplicate="new")

    assert copy_id != source_id
    assert _stored(db_session, copy_id) == source

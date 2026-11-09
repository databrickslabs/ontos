import yaml
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import patch, Mock


def test_odcs_upload_then_export_roundtrip(client: TestClient, db_session: Session):
    """Upload the reference ODCS YAML and verify exported YAML matches on key fields."""
    reference_path = Path(__file__).parent.parent / "data" / "odcs" / "full-example.odcs.yaml"
    assert reference_path.exists(), "Reference ODCS file is missing"

    with open(reference_path, 'rb') as f:
        file_bytes = f.read()

    reference = yaml.safe_load(file_bytes)

    # Patch domain resolution and semantic links to keep export deterministic
    with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
        mock_domain = Mock()
        mock_domain.id = 'domain-1'
        mock_domain.name = reference.get('domain') or 'seller'
        mock_domain_repo.get_by_name.return_value = mock_domain
        mock_domain_repo.create.return_value = mock_domain
        mock_domain_repo.get.return_value = mock_domain

        with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
            mock_semantic_manager.return_value.list_for_entity.return_value = []

            # Upload reference contract
            resp = client.post(
                "/api/data-contracts/upload",
                files={"files": ("full-example.odcs.yaml", file_bytes, "application/x-yaml")},
            )
            assert resp.status_code == 200, resp.text
            created = resp.json()
            # Endpoint now returns a BatchImportResult; a single-object upload
            # yields exactly one created entity.
            assert created["created"] == 1, resp.text
            contract_id = created["created_ids"][0]

            # Export back to ODCS YAML
            export_resp = client.get(f"/api/data-contracts/{contract_id}/odcs/export")
            assert export_resp.status_code == 200, export_resp.text
            exported = yaml.safe_load(export_resp.content)

    # --- Root-level checks ---
    assert exported["kind"] == reference["kind"]
    assert exported["apiVersion"] == reference["apiVersion"]
    assert exported["version"] == reference["version"]
    assert exported["status"] == reference["status"]

    # Name should match dataProduct from reference if no explicit name provided
    assert exported["name"] == reference["dataProduct"]

    # Optional top-level
    assert exported.get("tenant") == reference.get("tenant")
    assert exported.get("dataProduct") == reference.get("dataProduct")
    assert exported.get("domain") == reference.get("domain")
    assert exported.get("slaDefaultElement") == reference.get("slaDefaultElement")

    # --- Description object ---
    assert "description" in exported
    desc = exported["description"]
    ref_desc = reference.get("description", {})
    assert desc.get("usage") == ref_desc.get("usage")
    assert desc.get("purpose") == ref_desc.get("purpose")
    assert desc.get("limitations") == ref_desc.get("limitations")
    # authoritativeDefinitions should exist and contain at least the privacy-statement
    assert any(
        (ad.get("type") == "privacy-statement" and ad.get("url") == "https://example.com/gdpr.pdf")
        for ad in desc.get("authoritativeDefinitions", [])
    )

    # --- Servers ---
    assert exported.get("servers") and len(exported["servers"]) >= 1
    srv = exported["servers"][0]
    ref_srv = reference.get("servers", [{}])[0]
    assert srv.get("server") == ref_srv.get("server")
    assert srv.get("type") == ref_srv.get("type")
    assert srv.get("host") == ref_srv.get("host")
    assert srv.get("port") == ref_srv.get("port")
    assert srv.get("database") == ref_srv.get("database")
    assert srv.get("schema") == ref_srv.get("schema")

    # --- Schema and properties ---
    assert exported.get("schema") and len(exported["schema"]) == 1
    schema = exported["schema"][0]
    ref_schema = reference.get("schema", [{}])[0]
    assert schema.get("name") == ref_schema.get("name")
    assert schema.get("physicalName") == ref_schema.get("physicalName")
    assert schema.get("businessName") == ref_schema.get("businessName")
    assert schema.get("physicalType") == ref_schema.get("physicalType")
    assert schema.get("description") == ref_schema.get("description")
    assert set(schema.get("tags", [])) == set(ref_schema.get("tags", []))

    # Find specific properties by name
    props_by_name = {p.get("name"): p for p in schema.get("properties", [])}
    ref_props_by_name = {p.get("name"): p for p in ref_schema.get("properties", [])}

    # transaction_reference_date
    tx_ref = props_by_name.get("transaction_reference_date")
    ref_tx_ref = ref_props_by_name.get("transaction_reference_date")
    assert tx_ref and ref_tx_ref
    assert tx_ref.get("physicalName") == ref_tx_ref.get("physicalName")
    assert tx_ref.get("partitioned") == ref_tx_ref.get("partitioned")
    assert tx_ref.get("partitionKeyPosition") == ref_tx_ref.get("partitionKeyPosition")
    assert tx_ref.get("classification") == ref_tx_ref.get("classification")
    assert tx_ref.get("logicalType") == ref_tx_ref.get("logicalType")
    assert tx_ref.get("physicalType") == ref_tx_ref.get("physicalType")

    # rcvr_id primary key
    rcvr_id = props_by_name.get("rcvr_id")
    ref_rcvr_id = ref_props_by_name.get("rcvr_id")
    assert rcvr_id and ref_rcvr_id
    assert rcvr_id.get("primaryKey") is True
    assert rcvr_id.get("primaryKeyPosition") == ref_rcvr_id.get("primaryKeyPosition")

    # rcvr_cntry_code quality/customProperties presence
    rcvr_cc = props_by_name.get("rcvr_cntry_code")
    assert rcvr_cc
    assert isinstance(rcvr_cc.get("quality", []), list)

    # Schema-level quality should include countCheck rule
    assert isinstance(schema.get("quality", []), list)
    assert any(q.get("rule") == "countCheck" for q in schema.get("quality", []))

    # Schema-level customProperties include business-key
    assert any(
        (cp.get("property") == "business-key") for cp in schema.get("customProperties", [])
    )

    # --- Team ---
    team = exported.get("team", [])
    assert len(team) >= 3
    ce = next((m for m in team if m.get("username") == "ceastwood"), None)
    assert ce is not None and ce.get("role") == "Data Scientist"
    assert ce.get("dateIn") and ce.get("dateOut")

    # --- Roles ---
    roles = exported.get("roles", [])
    assert any(r.get("role") == "microstrategy_user_opr" for r in roles)

    # --- Price ---
    price = exported.get("price", {})
    assert price.get("priceCurrency") == reference.get("price", {}).get("priceCurrency")
    # numeric compare
    assert float(price.get("priceAmount")) == float(reference.get("price", {}).get("priceAmount"))



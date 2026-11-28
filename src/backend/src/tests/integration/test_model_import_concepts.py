"""erwin logical model → concepts through a staged run (PRD #1718, slice 2 #1720)."""
import hashlib
import io
from pathlib import Path

import pytest
from rdflib.namespace import OWL, RDF, RDFS
from rdflib import URIRef
from sqlalchemy.orm import Session

from src.app import app
from src.common.app_state import set_app_state_manager
from src.controller.model_import_manager import (
    ModelImportError,
    ModelImportManager,
    decode_ir,
)
from src.controller.semantic_models_manager import SemanticModelsManager
from src.models.model_import import ModelImportOptions
from src.repositories.concept_versions_repository import concept_versions_repo

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "erwin" / "sales_dw_standard.xml"
XML = FIXTURE.read_text(encoding="utf-8")
COLLECTION = "urn:ontology:sales-dw"


@pytest.fixture
def semantic(db_session: Session, tmp_path: Path):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    manager = SemanticModelsManager(db=db_session, data_dir=data_dir)
    app.state.semantic_models_manager = manager
    set_app_state_manager("semantic_models_manager", manager)

    class _NoopOSM:
        def sync_asset_types(self, *_a, **_k):
            return {"created": 0, "updated": 0}

    class _NoopAudit:
        def log_action(self, *_a, **_k):
            return None

        def log_event(self, *_a, **_k):
            return None

    app.state.ontology_schema_manager = _NoopOSM()
    app.state.audit_manager = _NoopAudit()
    yield manager
    for attr in ("semantic_models_manager", "ontology_schema_manager", "audit_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


@pytest.fixture
def manager(semantic):
    return ModelImportManager(semantic_models_manager=semantic, data_contracts_manager=None)


def _stage(manager, db, xml=XML, **opts):
    data = xml.encode("utf-8")
    options = ModelImportOptions(import_physical=False, **opts)
    return manager.create_run(
        db, stream=io.BytesIO(data), filename="sales_dw.xml", size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(), user_id="steward@example.com", options=options,
    )


def _import(manager, db, xml=XML, **opts):
    run = _stage(manager, db, xml, **opts)
    run = manager.confirm_run(db, run, run.confirm_token, "steward@example.com", run_inline=True)
    assert run.status == "completed", run.error
    return run


def _iri(slug):
    return URIRef(f"{COLLECTION}/{slug}")


class TestStaging:
    def test_preview_writes_nothing(self, manager, semantic, db_session):
        run = _stage(manager, db_session)
        assert run.status == "previewed"
        assert run.confirm_token
        assert decode_ir(run.model_ir).name == "Sales DW"
        logical = run.preview["logical"]
        assert logical["collection_iri"] == COLLECTION
        assert logical["collection_exists"] is False
        assert logical["counts"]["classes"] == 7
        assert logical["summary"]["new"] > 0
        assert semantic.get_collection(COLLECTION) is None

    def test_stale_token_rejected(self, manager, db_session):
        run = _stage(manager, db_session)
        old = run.confirm_token
        party = next(s["id"] for s in run.preview["model"]["subject_areas"] if s["name"] == "Party")
        run = manager.update_options(
            db_session, run, ModelImportOptions(import_physical=False, subject_area_ids=[party]),
        )
        assert run.confirm_token != old
        with pytest.raises(ModelImportError, match="preview changed"):
            manager.confirm_run(db_session, run, old, "steward@example.com", run_inline=True)

    def test_cancel_previewed_run_drops_model(self, manager, db_session):
        run = manager.cancel_run(db_session, _stage(manager, db_session))
        assert run.status == "cancelled"
        assert run.model_ir is None
        with pytest.raises(ModelImportError):
            manager.confirm_run(db_session, run, "x" * 40, "steward@example.com", run_inline=True)

    def test_unknown_subject_areas_are_dropped(self, manager, db_session):
        run = _stage(manager, db_session, subject_area_ids=["{NOPE}+0"])
        assert run.options["subject_area_ids"] == []


class TestFirstImport:
    def test_classes_properties_relationships(self, manager, semantic, db_session):
        run = _import(manager, db_session)
        assert run.result["logical"]["collection_iri"] == COLLECTION
        g = semantic._graph.get_context(URIRef(COLLECTION))

        customer = _iri("customer")
        assert (customer, RDF.type, OWL.Class) in g
        assert semantic.get_concept(str(customer))["comment"] == "A party that has placed at least one order."
        assert semantic.get_concept(str(customer))["status"] == "draft"

        email = _iri("customer.email-address")
        assert (email, RDF.type, OWL.DatatypeProperty) in g
        assert (email, RDFS.domain, customer) in g

        # Migrated FK attribute has no property of its own.
        assert (_iri("order.customer-id"), None, None) not in g

        places = _iri("customer.places.order")
        assert (places, RDF.type, OWL.ObjectProperty) in g
        assert (places, RDFS.range, _iri("order")) in g

        assert (_iri("person"), RDFS.subClassOf, _iri("party")) in g
        # Views are physical only.
        assert (_iri("v-customer-orders"), None, None) not in g

    def test_domains_are_concepts(self, manager, semantic, db_session):
        _import(manager, db_session)
        status = semantic.get_concept(f"{COLLECTION}/domain-order-status")
        assert status is not None
        assert status["comment"] == "Lifecycle state of an order."

    def test_concepts_get_v1(self, manager, db_session):
        _import(manager, db_session)
        cv = concept_versions_repo.get_current(db_session, f"{COLLECTION}/customer")
        assert cv is not None and cv.version == 1

    def test_subject_area_scope(self, manager, semantic, db_session):
        run = _stage(manager, db_session)
        party = next(s["id"] for s in run.preview["model"]["subject_areas"] if s["name"] == "Party")
        _import(manager, db_session, subject_area_ids=[party])
        g = semantic._graph.get_context(URIRef(COLLECTION))
        assert (_iri("party"), RDF.type, OWL.Class) in g
        assert (_iri("order"), None, None) not in g


class TestReimport:
    def test_identical_reimport_is_a_no_op(self, manager, db_session):
        _import(manager, db_session)
        run = _stage(manager, db_session)
        summary = run.preview["logical"]["summary"]
        assert summary["new"] == 0 and summary["modified"] == 0 and summary["removed"] == 0
        assert run.preview["previous_run_id"]

    def test_rename_keeps_iri_and_versions(self, manager, semantic, db_session):
        _import(manager, db_session)
        changed = XML.replace(
            "<EMX:Name>Customer</EMX:Name>", "<EMX:Name>Client</EMX:Name>",
        ).replace(
            "A party that has placed at least one order.", "A party that buys from us.",
        )
        run = _stage(manager, db_session, changed)
        assert run.preview["logical"]["summary"]["modified"] == 1
        manager.confirm_run(db_session, run, run.confirm_token, "steward@example.com", run_inline=True)
        concept = semantic.get_concept(f"{COLLECTION}/customer")
        assert concept["label"] == "Client"
        assert concept["comment"] == "A party that buys from us."
        assert concept_versions_repo.get_current(db_session, f"{COLLECTION}/customer").version == 2

        # A third, identical import changes nothing even though v1 history exists.
        again = _stage(manager, db_session, changed)
        assert again.preview["logical"]["summary"]["modified"] == 0

    def test_removed_entity_is_deprecated_not_deleted(self, manager, semantic, db_session):
        _import(manager, db_session)
        start = XML.index('<EMX:Entity id="{E-PROD}+00000000"')
        end = XML.index("</EMX:Entity>", start) + len("</EMX:Entity>")
        without_product = XML[:start] + XML[end:]
        run = _stage(manager, db_session, without_product)
        removed = {r["iri"] for r in run.preview["logical"]["removed"]}
        assert f"{COLLECTION}/product" in removed
        manager.confirm_run(db_session, run, run.confirm_token, "steward@example.com", run_inline=True)
        concept = semantic.get_concept(f"{COLLECTION}/product")
        assert concept is not None
        assert concept["status"] == "deprecated"

    def test_out_of_scope_concepts_are_kept(self, manager, db_session):
        _import(manager, db_session)
        run = _stage(manager, db_session)
        party = next(s["id"] for s in run.preview["model"]["subject_areas"] if s["name"] == "Party")
        run = manager.update_options(
            db_session, run, ModelImportOptions(import_physical=False, subject_area_ids=[party]),
        )
        assert run.preview["logical"]["summary"]["removed"] == 0

    def test_foreign_concepts_in_collection_are_kept(self, manager, semantic, db_session):
        semantic.create_collection(label="Sales DW", collection_type="ontology", created_by="x")
        semantic.create_concept(
            collection_iri=COLLECTION, label="Hand Made", definition="Not from erwin.",
            concept_type="class", created_by="x",
        )
        run = _stage(manager, db_session)
        assert run.preview["logical"]["collection_exists"] is True
        assert run.preview["logical"]["summary"]["removed"] == 0
        manager.confirm_run(db_session, run, run.confirm_token, "steward@example.com", run_inline=True)
        assert semantic.get_concept(f"{COLLECTION}/hand-made")["status"] != "deprecated"


class TestReviewFixes:
    def test_modified_concept_snapshot_matches_model(self, manager, semantic, db_session):
        """A re-import persists every predicate of a modified concept, not only label/definition."""
        _import(manager, db_session)
        changed = XML.replace(
            "<EMX:Logical_Data_Type>VARCHAR(255)</EMX:Logical_Data_Type>",
            "<EMX:Logical_Data_Type>INTEGER</EMX:Logical_Data_Type>",
        )
        run = _stage(manager, db_session, changed)
        assert run.preview["logical"]["summary"]["modified"] == 1
        manager.confirm_run(db_session, run, run.confirm_token, "steward@example.com", run_inline=True)
        from rdflib.namespace import XSD
        g = semantic._graph.get_context(URIRef(COLLECTION))
        email = _iri("customer.email-address")
        assert (email, RDFS.range, XSD.integer) in g
        assert (email, RDFS.range, XSD.string) not in g
        assert _stage(manager, db_session, changed).preview["logical"]["summary"]["modified"] == 0

    def test_subject_areas_annotate_classes(self, manager, semantic, db_session):
        from src.model_import.erwin.map_concepts import ERWIN
        _import(manager, db_session)
        g = semantic._graph.get_context(URIRef(COLLECTION))
        areas = {str(o) for o in g.objects(_iri("customer"), ERWIN.subjectArea)}
        assert areas == {"Sales", "Party"}

    def test_entity_turned_physical_only_is_deprecated(self, manager, semantic, db_session):
        _import(manager, db_session)
        changed = XML.replace(
            "<EMX:Name>Product</EMX:Name><EMX:Physical_Name>PRODUCT</EMX:Physical_Name>",
            "<EMX:Name>Product</EMX:Name><EMX:Physical_Name>PRODUCT</EMX:Physical_Name>"
            "<EMX:Physical_Only>true</EMX:Physical_Only>",
        )
        run = _stage(manager, db_session, changed)
        assert f"{COLLECTION}/product" in {r["iri"] for r in run.preview["logical"]["removed"]}

    def test_hand_made_concept_iri_is_not_taken_over(self, manager, semantic, db_session):
        semantic.create_collection(label="Sales DW", collection_type="ontology", created_by="x")
        semantic.create_concept(collection_iri=COLLECTION, label="Customer", definition="Ours.",
                                concept_type="class", created_by="x")
        _import(manager, db_session)
        assert semantic.get_concept(f"{COLLECTION}/customer")["comment"] == "Ours."
        assert semantic.get_concept(f"{COLLECTION}/customer-2")["comment"] == (
            "A party that has placed at least one order."
        )

    def test_custom_collection_iri_is_created_as_given(self, manager, semantic, db_session):
        run = _import(manager, db_session, collection_iri="urn:ontology:erwin-sales")
        assert run.result["logical"]["collection_iri"] == "urn:ontology:erwin-sales"
        assert semantic.get_collection("urn:ontology:erwin-sales") is not None

    def test_patch_keeps_run_options(self, manager, db_session):
        run = _stage(manager, db_session, collection_iri="urn:ontology:erwin-sales", contract_grouping="table")
        run = manager.update_options(db_session, run, ModelImportOptions(migration_mode=True))
        assert run.options["collection_iri"] == "urn:ontology:erwin-sales"
        assert run.options["contract_grouping"] == "table"
        assert run.options["import_physical"] is False
        assert run.options["migration_mode"] is True

    def test_confirm_twice_is_rejected(self, manager, db_session):
        run = _stage(manager, db_session)
        token = run.confirm_token
        manager.confirm_run(db_session, run, token, "steward@example.com", run_inline=True)
        with pytest.raises(ModelImportError):
            manager.confirm_run(db_session, run, token, "steward@example.com", run_inline=True)

    def test_orphaned_running_run_does_not_block_the_model(self, manager, db_session):
        from datetime import datetime, timedelta, timezone
        stuck = _stage(manager, db_session)
        stuck.status = "running"
        stuck.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
        db_session.commit()
        run = _stage(manager, db_session)
        run = manager.confirm_run(db_session, run, run.confirm_token, "steward@example.com", run_inline=True)
        assert run.status == "completed"
        db_session.refresh(stuck)
        assert stuck.status == "failed"


class TestFinalReviewFixes:
    def test_hand_added_annotations_survive_reimport(self, manager, semantic, db_session):
        from rdflib import Literal
        from src.repositories.rdf_triples_repository import rdf_triples_repo
        _import(manager, db_session)
        cv = concept_versions_repo.get_current(db_session, f"{COLLECTION}/customer")
        rdf_triples_repo.add_triple(
            db_session, subject_uri=f"{COLLECTION}/customer",
            predicate_uri="http://www.w3.org/2004/02/skos/core#example", object_value="ACME Corp",
            object_is_uri=False, context_name=COLLECTION, concept_version_id=cv.id,
        )
        db_session.commit()
        semantic.rebuild_graph_from_enabled()
        changed = XML.replace("A party that has placed at least one order.", "A party that buys from us.")
        run = _stage(manager, db_session, changed)
        manager.confirm_run(db_session, run, run.confirm_token, "steward@example.com", run_inline=True)
        g = semantic._graph.get_context(URIRef(COLLECTION))
        from rdflib.namespace import SKOS
        assert (_iri("customer"), SKOS.example, Literal("ACME Corp")) in g
        assert (_iri("customer"), SKOS.definition, Literal("A party that buys from us.")) in g

    def test_second_running_run_of_a_model_is_rejected(self, manager, db_session):
        from src.controller.model_import_manager import ModelImportConflict
        first = _stage(manager, db_session)
        first.status = "running"
        db_session.commit()
        run = _stage(manager, db_session)
        with pytest.raises(ModelImportConflict):
            manager.confirm_run(db_session, run, run.confirm_token, "steward@example.com", run_inline=True)

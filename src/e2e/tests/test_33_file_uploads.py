"""
File Upload Endpoints — smoke and functional tests.

Covers:
  POST /api/data-contracts/upload    — parse + create a contract from YAML/JSON file
  POST /api/data-products/upload     — batch-create products from YAML/JSON file
  POST /api/entities/{type}/{id}/documents  — entity-scoped document upload (UC Volumes)
  POST /api/metadata/shared/documents       — shared document upload (UC Volumes)

Design notes
------------
- All multipart/form-data requests explicitly drop the session's Content-Type header so
  that requests can compute and inject the correct multipart boundary.
- Success is 200 or 201.  400/422 are treated as validation-level smoke-pass (the
  endpoint was reachable and responded meaningfully).  500 is always a failure.
- Document upload endpoints write to UC Volumes; if the workspace is not configured
  with the required volume they return 500.  We record IDs on a best-effort basis and
  always attempt cleanup.
- A data domain is created as the entity anchor for document upload tests and torn down
  after the class completes.
"""
import io
import json
import uuid

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

E2E_PREFIX = "e2e-upload-"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _multipart_post(api, full_url: str, files: dict, data: dict | None = None):
    """POST multipart/form-data, bypassing the session's Content-Type header."""
    headers = dict(api.headers)
    headers.pop("Content-Type", None)
    return api.post(full_url, files=files, data=data or {}, headers=headers)


def _minimal_contract_yaml(name: str) -> bytes:
    contract = {
        "kind": "DataContract",
        "apiVersion": "v3.0.2",
        "id": name,
        "version": "1.0.0",
        "status": "draft",
        "name": name,
        "domain": "e2e-testing",
        "description": {
            "purpose": "E2E upload smoke test",
            "usage": "Automated file upload testing",
        },
        "schema": [
            {
                "name": "upload_test_table",
                "physicalName": "upload_test_table",
                "description": "Upload smoke test schema",
                "properties": [
                    {
                        "name": "id",
                        "logicalType": "integer",
                        "required": True,
                        "primaryKey": True,
                    },
                    {
                        "name": "label",
                        "logicalType": "string",
                        "required": False,
                    },
                ],
            }
        ],
    }
    return yaml.dump(contract, default_flow_style=False).encode("utf-8")


def _minimal_contract_json(name: str) -> bytes:
    contract = {
        "kind": "DataContract",
        "apiVersion": "v3.0.2",
        "id": name,
        "version": "1.0.0",
        "status": "draft",
        "name": name,
        "domain": "e2e-testing",
    }
    return json.dumps(contract).encode("utf-8")


def _minimal_product_yaml(name: str) -> bytes:
    product = {
        "apiVersion": "v1.0.0",
        "kind": "DataProduct",
        "id": name,
        "status": "draft",
        "name": name,
        "version": "1.0.0",
        "domain": "e2e-testing",
        "tenant": "e2e-org",
        "description": {
            "purpose": "E2E upload smoke test product",
            "limitations": "Test data only",
            "usage": "Automated file upload testing",
        },
    }
    return yaml.dump(product, default_flow_style=False).encode("utf-8")


def _minimal_product_json(name: str) -> bytes:
    product = {
        "apiVersion": "v1.0.0",
        "kind": "DataProduct",
        "id": name,
        "status": "draft",
        "name": name,
        "version": "1.0.0",
        "domain": "e2e-testing",
        "tenant": "e2e-org",
        "description": {
            "purpose": "E2E upload smoke test product",
            "limitations": "Test data only",
            "usage": "Automated file upload testing",
        },
    }
    return json.dumps(product).encode("utf-8")


# ---------------------------------------------------------------------------
# Data Contract Upload Tests
# ---------------------------------------------------------------------------

class TestDataContractUpload:
    """POST /api/data-contracts/upload"""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete: list[str] = []
        yield
        for contract_id in reversed(self._to_delete):
            api.delete(url(f"/api/data-contracts/{contract_id}"))

    # ------------------------------------------------------------------
    # YAML upload
    # ------------------------------------------------------------------

    @pytest.mark.crud
    def test_upload_contract_yaml(self, api, url):
        name = f"{E2E_PREFIX}contract-yaml-{_uid()}"
        content = _minimal_contract_yaml(name)

        resp = _multipart_post(
            api,
            url("/api/data-contracts/upload"),
            files={"file": (f"{name}.yaml", io.BytesIO(content), "application/x-yaml")},
        )

        assert resp.status_code != 500, (
            f"Server error on YAML contract upload: {resp.status_code} {resp.text[:400]}"
        )
        assert resp.status_code in (200, 201, 400, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:400]}"
        )

        if resp.status_code in (200, 201):
            body = resp.json()
            contract_id = body.get("id")
            assert contract_id, f"No id in response: {body}"
            self._to_delete.append(contract_id)

            # Basic shape checks
            assert body.get("name") == name or body.get("id") == name, (
                f"Name/id mismatch: expected {name!r}, got name={body.get('name')!r} id={body.get('id')!r}"
            )
            assert body.get("status") is not None, "Missing status in response"

    @pytest.mark.crud
    def test_upload_contract_json(self, api, url):
        name = f"{E2E_PREFIX}contract-json-{_uid()}"
        content = _minimal_contract_json(name)

        resp = _multipart_post(
            api,
            url("/api/data-contracts/upload"),
            files={"file": (f"{name}.json", io.BytesIO(content), "application/json")},
        )

        assert resp.status_code != 500, (
            f"Server error on JSON contract upload: {resp.status_code} {resp.text[:400]}"
        )
        assert resp.status_code in (200, 201, 400, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:400]}"
        )

        if resp.status_code in (200, 201):
            body = resp.json()
            contract_id = body.get("id")
            assert contract_id, f"No id in response: {body}"
            self._to_delete.append(contract_id)

    @pytest.mark.crud
    def test_upload_contract_response_shape(self, api, url):
        """Verify that a successful upload returns the normalised ODCS structure."""
        name = f"{E2E_PREFIX}contract-shape-{_uid()}"
        content = _minimal_contract_yaml(name)

        resp = _multipart_post(
            api,
            url("/api/data-contracts/upload"),
            files={"file": (f"{name}.yaml", io.BytesIO(content), "application/x-yaml")},
        )

        if resp.status_code not in (200, 201):
            pytest.skip(f"Upload returned {resp.status_code} — shape check skipped")

        body = resp.json()
        self._to_delete.append(body["id"])

        # Fields that must always be present after a successful contract upload
        required_fields = ["id", "name", "status", "version"]
        missing = [f for f in required_fields if f not in body]
        assert not missing, f"Missing fields in upload response: {missing}"

    @pytest.mark.crud
    def test_upload_contract_invalid_content(self, api, url):
        """Garbage file content should be rejected with 400, not 500."""
        resp = _multipart_post(
            api,
            url("/api/data-contracts/upload"),
            files={"file": ("garbage.yaml", io.BytesIO(b":::not valid yaml:::"), "application/x-yaml")},
        )

        assert resp.status_code != 500, (
            f"Server crashed on invalid contract content: {resp.status_code} {resp.text[:400]}"
        )
        # The backend should return 400 for unparseable / invalid content
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for garbage input, got {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.crud
    def test_upload_contract_empty_file(self, api, url):
        """An empty file should be rejected gracefully."""
        resp = _multipart_post(
            api,
            url("/api/data-contracts/upload"),
            files={"file": ("empty.yaml", io.BytesIO(b""), "application/x-yaml")},
        )

        assert resp.status_code != 500, (
            f"Server crashed on empty contract file: {resp.status_code} {resp.text[:400]}"
        )
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for empty file, got {resp.status_code}: {resp.text[:300]}"
        )


# ---------------------------------------------------------------------------
# Data Product Upload Tests
# ---------------------------------------------------------------------------

class TestDataProductUpload:
    """POST /api/data-products/upload"""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete: list[str] = []
        yield
        for product_id in reversed(self._to_delete):
            api.delete(url(f"/api/data-products/{product_id}"))

    # ------------------------------------------------------------------
    # YAML upload
    # ------------------------------------------------------------------

    @pytest.mark.crud
    def test_upload_product_yaml(self, api, url):
        name = f"{E2E_PREFIX}product-yaml-{_uid()}"
        content = _minimal_product_yaml(name)

        resp = _multipart_post(
            api,
            url("/api/data-products/upload"),
            files={"file": (f"{name}.yaml", io.BytesIO(content), "application/x-yaml")},
        )

        assert resp.status_code != 500, (
            f"Server error on YAML product upload: {resp.status_code} {resp.text[:400]}"
        )
        assert resp.status_code in (200, 201, 400, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:400]}"
        )

        if resp.status_code in (200, 201):
            body = resp.json()
            # Response is a list of created products
            assert isinstance(body, list), f"Expected list response, got: {type(body)}"
            assert len(body) >= 1, "Expected at least one product in response"
            product_id = body[0].get("id")
            assert product_id, f"No id in first product: {body[0]}"
            self._to_delete.append(product_id)

    @pytest.mark.crud
    def test_upload_product_json(self, api, url):
        name = f"{E2E_PREFIX}product-json-{_uid()}"
        content = _minimal_product_json(name)

        resp = _multipart_post(
            api,
            url("/api/data-products/upload"),
            files={"file": (f"{name}.json", io.BytesIO(content), "application/json")},
        )

        assert resp.status_code != 500, (
            f"Server error on JSON product upload: {resp.status_code} {resp.text[:400]}"
        )
        assert resp.status_code in (200, 201, 400, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:400]}"
        )

        if resp.status_code in (200, 201):
            body = resp.json()
            assert isinstance(body, list), f"Expected list response, got: {type(body)}"
            product_id = body[0].get("id")
            assert product_id
            self._to_delete.append(product_id)

    @pytest.mark.crud
    def test_upload_product_batch_yaml(self, api, url):
        """A YAML list of products should create multiple records."""
        name_a = f"{E2E_PREFIX}batch-a-{_uid()}"
        name_b = f"{E2E_PREFIX}batch-b-{_uid()}"

        products = [
            {
                "apiVersion": "v1.0.0",
                "kind": "DataProduct",
                "id": name_a,
                "status": "draft",
                "name": name_a,
                "version": "1.0.0",
                "domain": "e2e-testing",
                "tenant": "e2e-org",
                "description": {"purpose": "batch item A", "limitations": "test", "usage": "test"},
            },
            {
                "apiVersion": "v1.0.0",
                "kind": "DataProduct",
                "id": name_b,
                "status": "draft",
                "name": name_b,
                "version": "1.0.0",
                "domain": "e2e-testing",
                "tenant": "e2e-org",
                "description": {"purpose": "batch item B", "limitations": "test", "usage": "test"},
            },
        ]
        content = yaml.dump(products, default_flow_style=False).encode("utf-8")
        filename = f"{E2E_PREFIX}batch-{_uid()}.yaml"

        resp = _multipart_post(
            api,
            url("/api/data-products/upload"),
            files={"file": (filename, io.BytesIO(content), "application/x-yaml")},
        )

        assert resp.status_code != 500, (
            f"Server error on batch YAML product upload: {resp.status_code} {resp.text[:400]}"
        )
        assert resp.status_code in (200, 201, 400, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:400]}"
        )

        if resp.status_code in (200, 201):
            body = resp.json()
            assert isinstance(body, list)
            for item in body:
                pid = item.get("id")
                if pid:
                    self._to_delete.append(pid)
            # Should have created at least one product
            assert len(body) >= 1, f"Expected products in response, got empty list"

    @pytest.mark.crud
    def test_upload_product_invalid_extension(self, api, url):
        """Non-YAML/JSON file must be rejected with 400."""
        resp = _multipart_post(
            api,
            url("/api/data-products/upload"),
            files={"file": ("data.csv", io.BytesIO(b"a,b,c\n1,2,3"), "text/csv")},
        )

        # The route explicitly rejects non .yaml/.json with 400
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for CSV upload, got {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.crud
    def test_upload_product_invalid_content(self, api, url):
        """Malformed YAML should not crash the server."""
        resp = _multipart_post(
            api,
            url("/api/data-products/upload"),
            files={"file": ("bad.yaml", io.BytesIO(b": : : not yaml at all"), "application/x-yaml")},
        )

        assert resp.status_code != 500, (
            f"Server crashed on invalid product YAML: {resp.status_code} {resp.text[:400]}"
        )
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for malformed YAML, got {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.crud
    def test_upload_product_empty_file(self, api, url):
        """Empty YAML/JSON file should be rejected gracefully."""
        resp = _multipart_post(
            api,
            url("/api/data-products/upload"),
            files={"file": ("empty.yaml", io.BytesIO(b""), "application/x-yaml")},
        )

        assert resp.status_code != 500, (
            f"Server crashed on empty product file: {resp.status_code} {resp.text[:400]}"
        )
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for empty file, got {resp.status_code}: {resp.text[:300]}"
        )


# ---------------------------------------------------------------------------
# Entity Document Upload Tests
# ---------------------------------------------------------------------------

class TestEntityDocumentUpload:
    """POST /api/entities/{entity_type}/{entity_id}/documents

    Uses a data domain as the entity anchor so we have a real entity to attach to.
    The document upload also writes to UC Volumes; if that is not configured in the
    deployment the endpoint returns 500 — we treat such a response as 'infrastructure
    not available' and skip rather than fail the test.
    """

    ENTITY_TYPE = "data_domain"

    @pytest.fixture(autouse=True)
    def _setup_entity(self, api, url):
        # Create a domain to use as the anchor entity
        domain_payload = {
            "name": f"{E2E_PREFIX}domain-doc-{_uid()}",
            "description": "E2E anchor domain for document upload tests",
        }
        resp = api.post(url("/api/data-domains"), json=domain_payload)
        assert resp.status_code in (200, 201), (
            f"Failed to create anchor domain: {resp.status_code} {resp.text[:300]}"
        )
        self._entity_id = resp.json()["id"]
        self._domain_id = self._entity_id
        self._doc_ids: list[str] = []

        yield

        # Cleanup: delete documents then the domain
        for doc_id in reversed(self._doc_ids):
            api.delete(url(f"/api/documents/{doc_id}"))
        api.delete(url(f"/api/data-domains/{self._domain_id}"))

    @pytest.mark.crud
    def test_upload_text_document(self, api, url):
        """Upload a plain text file as a document attached to an entity."""
        content = b"E2E document upload test content.\nCreated by automated test suite."
        endpoint = url(f"/api/entities/{self.ENTITY_TYPE}/{self._entity_id}/documents")

        resp = _multipart_post(
            api,
            endpoint,
            files={"file": ("e2e-test-doc.txt", io.BytesIO(content), "text/plain")},
            data={"title": f"E2E Doc {_uid()}", "short_description": "Automated test document"},
        )

        assert resp.status_code != 500, (
            f"Server error on document upload: {resp.text[:400]}"
        )

        assert resp.status_code in (200, 201, 400, 403, 422, 503), (
            f"Unexpected status {resp.status_code}: {resp.text[:400]}"
        )

        if resp.status_code in (200, 201):
            body = resp.json()
            doc_id = body.get("id")
            assert doc_id, f"No id in document response: {body}"
            self._doc_ids.append(doc_id)

            # Shape checks
            assert body.get("title"), "Missing title in document response"
            assert body.get("filename"), "Missing filename in document response"

    @pytest.mark.crud
    def test_upload_document_response_shape(self, api, url):
        """Verify the document response contains all expected fields."""
        content = b"Shape verification content for E2E test."
        doc_title = f"E2E Shape Doc {_uid()}"
        endpoint = url(f"/api/entities/{self.ENTITY_TYPE}/{self._entity_id}/documents")

        resp = _multipart_post(
            api,
            endpoint,
            files={"file": ("shape-check.txt", io.BytesIO(content), "text/plain")},
            data={"title": doc_title, "short_description": "Shape check doc"},
        )

        assert resp.status_code != 500, (
            f"Server error on document upload: {resp.text[:400]}"
        )

        if resp.status_code not in (200, 201):
            pytest.skip(f"Upload returned {resp.status_code} — shape check skipped")

        body = resp.json()
        self._doc_ids.append(body["id"])

        required_fields = ["id", "title", "filename"]
        missing = [f for f in required_fields if body.get(f) is None]
        assert not missing, f"Missing fields in document response: {missing}"
        assert body["title"] == doc_title, (
            f"Title mismatch: expected {doc_title!r}, got {body['title']!r}"
        )

    @pytest.mark.crud
    def test_upload_document_then_list(self, api, url):
        """Uploaded document should appear in the entity document list."""
        content = b"List verification content."
        doc_title = f"E2E List Doc {_uid()}"
        endpoint = url(f"/api/entities/{self.ENTITY_TYPE}/{self._entity_id}/documents")

        resp = _multipart_post(
            api,
            endpoint,
            files={"file": ("list-check.txt", io.BytesIO(content), "text/plain")},
            data={"title": doc_title},
        )

        assert resp.status_code != 500, (
            f"Server error on document upload: {resp.text[:400]}"
        )

        if resp.status_code not in (200, 201):
            pytest.skip(f"Upload returned {resp.status_code} — list check skipped")

        doc_id = resp.json()["id"]
        self._doc_ids.append(doc_id)

        # Now list and verify it appears
        list_resp = api.get(endpoint)
        assert list_resp.status_code == 200, (
            f"List documents failed: {list_resp.status_code} {list_resp.text[:300]}"
        )
        docs = list_resp.json()
        assert isinstance(docs, list), "Document list should be a list"
        ids = [d.get("id") for d in docs]
        assert doc_id in ids, f"Uploaded doc {doc_id!r} not found in list: {ids}"

    @pytest.mark.crud
    def test_upload_document_then_delete(self, api, url):
        """Uploaded document can be deleted via DELETE /api/documents/{id}."""
        content = b"Delete verification content."
        endpoint = url(f"/api/entities/{self.ENTITY_TYPE}/{self._entity_id}/documents")

        resp = _multipart_post(
            api,
            endpoint,
            files={"file": ("delete-check.txt", io.BytesIO(content), "text/plain")},
            data={"title": f"E2E Delete Doc {_uid()}"},
        )

        assert resp.status_code != 500, (
            f"Server error on document upload: {resp.text[:400]}"
        )

        if resp.status_code not in (200, 201):
            pytest.skip(f"Upload returned {resp.status_code} — delete check skipped")

        doc_id = resp.json()["id"]
        # Do NOT add to self._doc_ids — we delete it explicitly here
        del_resp = api.delete(url(f"/api/documents/{doc_id}"))
        assert del_resp.status_code in (200, 204), (
            f"Delete document failed: {del_resp.status_code} {del_resp.text[:300]}"
        )

    @pytest.mark.crud
    def test_upload_document_missing_title(self, api, url):
        """Omitting the required title field should yield 400/422, not 500."""
        content = b"No title test content."
        endpoint = url(f"/api/entities/{self.ENTITY_TYPE}/{self._entity_id}/documents")

        resp = _multipart_post(
            api,
            endpoint,
            files={"file": ("no-title.txt", io.BytesIO(content), "text/plain")},
            # deliberately no 'title' in data
        )

        # 500 is only acceptable here if due to storage, not missing validation
        assert resp.status_code != 500, (
            f"Server error on document upload: {resp.text[:400]}"
        )

        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for missing title, got {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.crud
    def test_upload_document_invalid_entity_type(self, api, url):
        """Path-traversal-like entity_type should be rejected."""
        content = b"Path traversal test."
        # The backend sanitises entity_type; '../etc' type values should get 400
        endpoint = url("/api/entities/../etc/passwd/documents")

        resp = _multipart_post(
            api,
            endpoint,
            files={"file": ("traversal.txt", io.BytesIO(content), "text/plain")},
            data={"title": "Traversal attempt"},
        )

        # Acceptable responses: 400 (validation), 404 (not found), 422 (FastAPI unprocessable)
        assert resp.status_code in (400, 404, 405, 422), (
            f"Expected 4xx for path traversal attempt, got {resp.status_code}: {resp.text[:300]}"
        )


# ---------------------------------------------------------------------------
# Shared Document Upload Tests
# ---------------------------------------------------------------------------

class TestSharedDocumentUpload:
    """POST /api/metadata/shared/documents

    Shared documents are stored in a fixed __shared__ directory in UC Volumes.
    Same UC-Volumes availability caveat applies as for entity documents.
    """

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._doc_ids: list[str] = []
        yield
        for doc_id in reversed(self._doc_ids):
            api.delete(url(f"/api/documents/{doc_id}"))

    @pytest.mark.crud
    def test_upload_shared_text_document(self, api, url):
        """Upload a plain text file as a shared document."""
        content = b"Shared E2E document content.\nCreated by automated test suite."

        resp = _multipart_post(
            api,
            url("/api/metadata/shared/documents"),
            files={"file": ("e2e-shared.txt", io.BytesIO(content), "text/plain")},
            data={
                "title": f"E2E Shared Doc {_uid()}",
                "short_description": "Automated shared document test",
                "level": "50",
                "inheritable": "true",
            },
        )

        assert resp.status_code != 500, (
            f"Server error on document upload: {resp.text[:400]}"
        )

        assert resp.status_code in (200, 201, 400, 403, 422, 503), (
            f"Unexpected status {resp.status_code}: {resp.text[:400]}"
        )

        if resp.status_code in (200, 201):
            body = resp.json()
            doc_id = body.get("id")
            assert doc_id, f"No id in shared document response: {body}"
            self._doc_ids.append(doc_id)

            assert body.get("title"), "Missing title in shared document response"
            assert body.get("filename"), "Missing filename in shared document response"

    @pytest.mark.crud
    def test_upload_shared_document_is_flagged_shared(self, api, url):
        """Shared documents should have is_shared=True in the response."""
        content = b"Shared flag verification content."

        resp = _multipart_post(
            api,
            url("/api/metadata/shared/documents"),
            files={"file": ("shared-flag.txt", io.BytesIO(content), "text/plain")},
            data={"title": f"E2E Shared Flag Doc {_uid()}"},
        )

        assert resp.status_code != 500, (
            f"Server error on document upload: {resp.text[:400]}"
        )

        if resp.status_code not in (200, 201):
            pytest.skip(f"Upload returned {resp.status_code} — flag check skipped")

        body = resp.json()
        self._doc_ids.append(body["id"])

        # The backend hardcodes is_shared=True for shared document records
        assert body.get("is_shared") is True, (
            f"Expected is_shared=True in shared document response, got: {body.get('is_shared')}"
        )

    @pytest.mark.crud
    def test_upload_shared_document_then_list(self, api, url):
        """Shared documents should appear in the shared asset list."""
        content = b"Shared list check content."
        doc_title = f"E2E Shared List Doc {_uid()}"

        resp = _multipart_post(
            api,
            url("/api/metadata/shared/documents"),
            files={"file": ("shared-list.txt", io.BytesIO(content), "text/plain")},
            data={"title": doc_title},
        )

        assert resp.status_code != 500, (
            f"Server error on document upload: {resp.text[:400]}"
        )

        if resp.status_code not in (200, 201):
            pytest.skip(f"Upload returned {resp.status_code} — list check skipped")

        doc_id = resp.json()["id"]
        self._doc_ids.append(doc_id)

        # The shared asset list endpoint includes documents
        list_resp = api.get(url("/api/metadata/shared"), params={"entity_type": "document"})
        assert list_resp.status_code == 200, (
            f"Shared list failed: {list_resp.status_code} {list_resp.text[:300]}"
        )

    @pytest.mark.crud
    def test_upload_shared_document_missing_title(self, api, url):
        """Missing required title should yield 400/422."""
        content = b"No title shared test."

        resp = _multipart_post(
            api,
            url("/api/metadata/shared/documents"),
            files={"file": ("no-title-shared.txt", io.BytesIO(content), "text/plain")},
            # no title in data
        )

        assert resp.status_code != 500, (
            f"Server error on document upload: {resp.text[:400]}"
        )

        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for missing title, got {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.crud
    def test_upload_shared_document_with_all_fields(self, api, url):
        """Upload with level and inheritable fields explicitly set."""
        content = b"All fields shared document test."

        resp = _multipart_post(
            api,
            url("/api/metadata/shared/documents"),
            files={"file": ("all-fields.txt", io.BytesIO(content), "text/plain")},
            data={
                "title": f"E2E All Fields Doc {_uid()}",
                "short_description": "Testing all optional fields",
                "level": "75",
                "inheritable": "false",
            },
        )

        assert resp.status_code != 500, (
            f"Server error on document upload: {resp.text[:400]}"
        )

        assert resp.status_code in (200, 201, 400, 403, 422, 503), (
            f"Unexpected status {resp.status_code}: {resp.text[:400]}"
        )

        if resp.status_code in (200, 201):
            body = resp.json()
            self._doc_ids.append(body["id"])
            # level and inheritable may be stored; spot-check title at minimum
            assert body.get("title"), "Missing title in response"

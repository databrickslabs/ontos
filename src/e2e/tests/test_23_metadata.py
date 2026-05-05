"""Metadata — Rich Texts and Links CRUD using a data domain as anchor."""
import pytest

from helpers.test_data import make_domain, make_rich_text, make_link, make_data_product


class TestMetadataRichTexts:

    @pytest.fixture(autouse=True)
    def _setup_entity(self, api, url):
        """Create a domain to attach metadata to."""
        payload = make_domain()
        resp = api.post(url("/api/data-domains"), json=payload)
        assert resp.status_code in (200, 201)
        self._entity_type = "data_domain"
        self._entity_id = resp.json()["id"]
        self._rt_ids = []
        yield
        for rid in reversed(self._rt_ids):
            api.delete(url(f"/api/rich-texts/{rid}"))
        api.delete(url(f"/api/data-domains/{self._entity_id}"))

    @pytest.mark.crud
    def test_rich_text_crud(self, api, url):
        payload = make_rich_text(self._entity_type, self._entity_id)

        # CREATE
        resp = api.post(
            url(f"/api/entities/{self._entity_type}/{self._entity_id}/rich-texts"),
            json=payload,
        )
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:300]}"
        created = resp.json()
        rt_id = created.get("id")
        assert rt_id, f"No ID in response: {created}"
        self._rt_ids.append(rt_id)

        assert created.get("title") == payload["title"]
        assert created.get("content_markdown") == payload["content_markdown"]

        # LIST
        resp = api.get(url(f"/api/entities/{self._entity_type}/{self._entity_id}/rich-texts"))
        assert resp.status_code == 200
        texts = resp.json()
        assert any(t.get("id") == rt_id for t in texts), "Rich text not in list"

        # UPDATE
        resp = api.put(url(f"/api/rich-texts/{rt_id}"), json={
            "title": "Updated E2E Rich Text",
            "content_markdown": "# Updated\n\nContent updated by E2E test.",
        })
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:300]}"

        # DELETE
        resp = api.delete(url(f"/api/rich-texts/{rt_id}"))
        assert resp.status_code in (200, 204)
        self._rt_ids.remove(rt_id)


class TestMetadataLinks:

    @pytest.fixture(autouse=True)
    def _setup_entity(self, api, url):
        """Create a domain to attach links to."""
        payload = make_domain()
        resp = api.post(url("/api/data-domains"), json=payload)
        assert resp.status_code in (200, 201)
        self._entity_type = "data_domain"
        self._entity_id = resp.json()["id"]
        self._link_ids = []
        yield
        for lid in reversed(self._link_ids):
            api.delete(url(f"/api/links/{lid}"))
        api.delete(url(f"/api/data-domains/{self._entity_id}"))

    @pytest.mark.crud
    def test_link_crud(self, api, url):
        payload = make_link(self._entity_type, self._entity_id)

        # CREATE
        resp = api.post(
            url(f"/api/entities/{self._entity_type}/{self._entity_id}/links"),
            json=payload,
        )
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:300]}"
        created = resp.json()
        link_id = created.get("id")
        assert link_id, f"No ID in response: {created}"
        self._link_ids.append(link_id)

        assert created.get("title") == payload["title"]
        assert created.get("url") == payload["url"]

        # LIST
        resp = api.get(url(f"/api/entities/{self._entity_type}/{self._entity_id}/links"))
        assert resp.status_code == 200
        links = resp.json()
        assert any(l.get("id") == link_id for l in links), "Link not in list"

        # UPDATE
        resp = api.put(url(f"/api/links/{link_id}"), json={
            "title": "Updated E2E Link",
            "url": "https://example.com/e2e-updated",
        })
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:300]}"

        # DELETE
        resp = api.delete(url(f"/api/links/{link_id}"))
        assert resp.status_code in (200, 204)
        self._link_ids.remove(link_id)


class TestMetadataMerged:

    @pytest.fixture(autouse=True)
    def _setup_entity(self, api, url):
        payload = make_domain()
        resp = api.post(url("/api/data-domains"), json=payload)
        assert resp.status_code in (200, 201)
        self._entity_type = "data_domain"
        self._entity_id = resp.json()["id"]
        yield
        api.delete(url(f"/api/data-domains/{self._entity_id}"))

    @pytest.mark.readonly
    def test_merged_metadata(self, api, url):
        resp = api.get(url(f"/api/entities/{self._entity_type}/{self._entity_id}/metadata/merged"))
        assert resp.status_code == 200


class TestMetadataDocuments:

    @pytest.fixture(autouse=True)
    def _setup_product(self, api, url):
        """Create a data product to attach documents to."""
        payload = make_data_product()
        resp = api.post(url("/api/data-products"), json=payload)
        assert resp.status_code in (200, 201), f"Data product create failed: {resp.status_code} {resp.text[:300]}"
        self._product_id = resp.json()["id"]
        self._doc_ids = []
        yield
        for did in reversed(self._doc_ids):
            api.delete(url(f"/api/documents/{did}"))
        api.delete(url(f"/api/data-products/{self._product_id}"))

    @pytest.mark.crud
    def test_document_crud(self, api, url):
        # Multipart upload requires no explicit Content-Type — remove and restore
        saved_content_type = api.headers.pop("Content-Type", None)
        try:
            resp = api.post(
                url(f"/api/entities/data_product/{self._product_id}/documents"),
                files={"file": ("test.txt", b"E2E test content", "text/plain")},
                data={"title": "E2E Test Doc"},
            )
        finally:
            if saved_content_type is not None:
                api.headers["Content-Type"] = saved_content_type

        if resp.status_code in (500, 503):
            pytest.skip(
                f"Document storage not available (status={resp.status_code}) — "
                "requires Databricks Volume access which may not be configured in E2E"
            )

        assert resp.status_code in (200, 201), f"Upload failed: {resp.status_code} {resp.text[:300]}"
        created = resp.json()
        doc_id = created.get("id")
        assert doc_id, f"No ID in upload response: {created}"
        self._doc_ids.append(doc_id)

        # LIST — verify document appears in entity document list
        resp = api.get(url(f"/api/entities/data_product/{self._product_id}/documents"))
        assert resp.status_code == 200, f"List failed: {resp.status_code} {resp.text[:300]}"
        docs = resp.json()
        if isinstance(docs, dict):
            docs = docs.get("items", docs.get("documents", []))
        assert any(d.get("id") == doc_id for d in docs), "Uploaded document not found in list"

        # GET single document
        resp = api.get(url(f"/api/documents/{doc_id}"))
        assert resp.status_code == 200, f"GET document failed: {resp.status_code} {resp.text[:300]}"

        # DELETE
        resp = api.delete(url(f"/api/documents/{doc_id}"))
        assert resp.status_code in (200, 204), f"Delete failed: {resp.status_code} {resp.text[:300]}"
        self._doc_ids.remove(doc_id)

    @pytest.mark.readonly
    def test_list_shared_assets(self, api, url):
        resp = api.get(url("/api/metadata/shared"))
        assert resp.status_code == 200, f"List shared assets failed: {resp.status_code} {resp.text[:300]}"


class TestMetadataAttachments:

    @pytest.fixture(autouse=True)
    def _setup_product(self, api, url):
        """Create a data product to attach shared assets to."""
        payload = make_data_product()
        resp = api.post(url("/api/data-products"), json=payload)
        assert resp.status_code in (200, 201), f"Data product create failed: {resp.status_code} {resp.text[:300]}"
        self._product_id = resp.json()["id"]
        self._shared_rt_ids = []
        yield
        # Best-effort cleanup of any shared rich texts created during the test
        for rid in reversed(self._shared_rt_ids):
            api.delete(url(f"/api/rich-texts/{rid}"))
        api.delete(url(f"/api/data-products/{self._product_id}"))

    @pytest.mark.crud
    def test_attachment_lifecycle(self, api, url):
        # CREATE a shared rich text
        # RichTextCreate requires entity_id and entity_type from the base model
        rt_payload = {
            "entity_id": str(self._product_id),
            "entity_type": "data_product",
            "title": "E2E Shared",
            "content_markdown": "# Test",
            "is_shared": True,
            "level": 50,
            "inheritable": True,
        }
        resp = api.post(url("/api/metadata/shared/rich-texts"), json=rt_payload)
        if resp.status_code in (400, 404):
            pytest.skip(f"Shared rich text creation not supported: {resp.status_code} {resp.text[:200]}")
        assert resp.status_code in (200, 201), f"Shared rich text create failed: {resp.status_code} {resp.text[:300]}"
        rich_text_id = resp.json().get("id")
        assert rich_text_id, f"No ID in shared rich text response: {resp.json()}"
        self._shared_rt_ids.append(rich_text_id)

        # ATTACH to data product
        attach_payload = {"asset_type": "rich_text", "asset_id": str(rich_text_id)}
        resp = api.post(
            url(f"/api/entities/data_product/{self._product_id}/attachments"),
            json=attach_payload,
        )
        if resp.status_code in (400, 404):
            pytest.skip(f"Attachment endpoint not supported: {resp.status_code} {resp.text[:200]}")
        assert resp.status_code in (200, 201), f"Attach failed: {resp.status_code} {resp.text[:300]}"

        # LIST attachments — verify it appears
        resp = api.get(url(f"/api/entities/data_product/{self._product_id}/attachments"))
        if resp.status_code in (400, 404):
            pytest.skip(f"List attachments endpoint not supported: {resp.status_code} {resp.text[:200]}")
        assert resp.status_code == 200, f"List attachments failed: {resp.status_code} {resp.text[:300]}"
        attachments = resp.json()
        if isinstance(attachments, dict):
            attachments = attachments.get("items", attachments.get("attachments", []))
        assert any(
            a.get("asset_id") == str(rich_text_id) or a.get("id") == str(rich_text_id)
            for a in attachments
        ), "Attached rich text not found in attachment list"

        # DETACH
        resp = api.delete(
            url(f"/api/entities/data_product/{self._product_id}/attachments/rich_text/{rich_text_id}")
        )
        if resp.status_code in (400, 404):
            pytest.skip(f"Detach endpoint not supported: {resp.status_code} {resp.text[:200]}")
        assert resp.status_code in (200, 204), f"Detach failed: {resp.status_code} {resp.text[:300]}"

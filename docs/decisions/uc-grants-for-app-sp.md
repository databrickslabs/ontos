# UC Grants for the Ontos App Service Principal

**Date**: 2026-05-01
**Context**: When the `generate_pdf` step is configured with `storage: volume`, agreement PDFs are written to a UC Volume via the Databricks Files API. The app's service principal needs explicit UC grants on the catalog/schema/volume hierarchy — without them the upload fails silently and the agreement record ends up with `pdf_storage_path=null`.

## Required grants

| Object | Grant |
|---|---|
| Catalog (e.g. `<catalog>`) | `USE CATALOG` |
| Schema (e.g. `<catalog>.<schema>`) | `USE SCHEMA` |
| Volume (e.g. `<catalog>.<schema>.<volume>`) | `READ VOLUME`, `WRITE VOLUME` |

The same SP also needs `READ VOLUME` on the same Volume so the download endpoint (`GET /api/approvals/agreements/{id}/pdf`) can fetch the persisted PDF back via the SDK Files API. `WRITE VOLUME` implicitly grants read on most workspaces, but it's safer to grant both explicitly.

## How to apply (SQL)

```sql
GRANT USE CATALOG ON CATALOG <catalog> TO `<app-sp-application-id>`;
GRANT USE SCHEMA  ON SCHEMA  <catalog>.<schema> TO `<app-sp-application-id>`;
GRANT READ VOLUME, WRITE VOLUME ON VOLUME <catalog>.<schema>.<volume> TO `<app-sp-application-id>`;
```

Replace placeholders with the catalog, schema, and volume configured for the deployment (the values used by the Databricks Asset Bundle in `src/app.yaml` / deploy variables).

## Finding the app SP application ID

The app's service principal application ID can be found via:

```bash
databricks apps get <app-name> --profile <profile> --output JSON | jq '.service_principal_client_id'
```

Or in the Databricks UI under **Apps → \<app\> → Permissions** — the SP is listed there with its application ID.

## Symptoms when grants are missing

- E2E test of the `generate_pdf` step writing to Volume fails with:
  - `User does not have USE SCHEMA on Schema 'X.Y'`
  - `Permission denied`
- Approval wizard completes silently with `pdf_storage_path = null` in the agreement record (the upload path swallows the SDK exception and logs a warning, then the agreement is still committed).
- Backend logs (`/tmp/backend.log` in dev, app logs in prod) contain:
  - `Agreement PDF Volume upload/local write failed: ... — HTML download available via API`

## Related

- Implementation: `src/backend/src/controller/agreement_wizard_manager.py` — Volume upload path (commit `92db4b3`)
- Download endpoint mirror fix: `src/backend/src/routes/approvals_routes.py` — `download_agreement_pdf` uses `WorkspaceClient.files.download()` for `/Volumes/` paths
- E2E coverage: `src/e2e/test_approval_ux_v1.py` — behavior B3 verifies the file lands in the Volume

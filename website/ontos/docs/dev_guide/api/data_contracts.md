---
sidebar_position: 4
id: data_contracts
title: data contract
description: Create, version, review, certify, and publish ODCS v3.1.0 data contracts, and manage their schemas and sub-resources.
---

# Data Contract

Data Contracts implement the [Open Data Contract Standard (ODCS) v3.1.0](https://bitol-io.github.io/open-data-contract-standard/). This is the largest route group in Ontos: beyond CRUD it covers the contract lifecycle, the approval and certification workflows, semantic versioning with personal drafts, schema and property management, quality profiling, and a set of ODCS sub-resources (roles, support channels, pricing, custom properties, authoritative definitions, relationships).

**Swagger tag:** `Data Contracts` &nbsp;·&nbsp; **Feature ID:** `data-contracts` &nbsp;·&nbsp; **Route prefix:** `/api/data-contracts`

:::tip
Approve, reject, certify, decertify, and publish-decision operations are gated by the **`CONTRACTS` approval privilege** (`ApprovalChecker`) rather than by a feature access level. Approval privileges are configured per app role in Settings.
:::

## Lifecycle

Contract status follows the ODCS lifecycle. `POST /api/data-contracts/{contract_id}/change-status` validates every transition:

| From | Allowed transitions |
| --- | --- |
| `draft` | `proposed`, `deprecated` |
| `proposed` | `draft`, `under_review`, `deprecated` |
| `under_review` | `draft`, `approved`, `deprecated` |
| `approved` | `active`, `draft`, `deprecated` |
| `active` | `certified`, `deprecated` |
| `certified` | `deprecated`, `active` |
| `deprecated` | `retired`, `active` |
| `retired` | *terminal — no transitions* |

Certification is also exposed as a separate dimension through the certify and decertify operations.

## Operations at a glance

### Core CRUD

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-contracts` | Create a contract | `Read/Write` |
| `GET` | `/api/data-contracts` | List contracts | `Read-only` |
| `GET` | `/api/data-contracts/count` | Count all contracts | `Read-only` |
| `GET` | `/api/data-contracts/{contract_id}` | Get a contract with the full ODCS structure | `Read-only` |
| `PUT` | `/api/data-contracts/{contract_id}` | Update a contract | `Read/Write` |
| `DELETE` | `/api/data-contracts/{contract_id}` | Delete a contract | `Read/Write` |

### Import and export

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-contracts/upload` | Upload and parse an ODCS file | `Read/Write` |
| `POST` | `/api/data-contracts/odcs/import` | Import a pasted ODCS JSON object | `Read/Write` |
| `GET` | `/api/data-contracts/{contract_id}/odcs/export` | Export a contract as ODCS YAML | `Read-only` |
| `GET` | `/api/data-contracts/schema/odcs` | Fetch the bundled ODCS v3.1.0 JSON Schema | `Read-only` |

### Lifecycle, review, and approval

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-contracts/{contract_id}/change-status` | Change status directly | `Read/Write` |
| `POST` | `/api/data-contracts/{contract_id}/approve` | Approve a contract | `CONTRACTS` approval |
| `POST` | `/api/data-contracts/{contract_id}/reject` | Reject a contract | `CONTRACTS` approval |
| `POST` | `/api/data-contracts/{contract_id}/request-review` | Request a steward review | `Read/Write` |
| `POST` | `/api/data-contracts/{contract_id}/handle-review` | Record a steward's review decision | `data-asset-reviews` — `Read/Write` |
| `POST` | `/api/data-contracts/{contract_id}/request-status-change` | Request a status change | `Read-only` |
| `POST` | `/api/data-contracts/{contract_id}/handle-status-change` | Decide a status change request | `Read/Write` |

### Certification

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-contracts/{contract_id}/request-certify` | Request certification | `Read/Write` |
| `POST` | `/api/data-contracts/{contract_id}/handle-certify` | Decide a certification request | `CONTRACTS` approval |
| `POST` | `/api/data-contracts/{contract_id}/certify` | Certify directly | `CONTRACTS` approval |
| `POST` | `/api/data-contracts/{contract_id}/decertify` | Remove certification | `CONTRACTS` approval |

### Publication and deployment

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-contracts/{contract_id}/set-publication-scope` | Set publication scope | `Read/Write` |
| `POST` | `/api/data-contracts/{contract_id}/request-publish` | Request marketplace publication | `Read/Write` |
| `POST` | `/api/data-contracts/{contract_id}/handle-publish` | Decide a publication request | `CONTRACTS` approval |
| `POST` | `/api/data-contracts/{contract_id}/request-deploy` | Request deployment to Unity Catalog | `Read/Write` |
| `POST` | `/api/data-contracts/{contract_id}/handle-deploy` | Decide a deployment request | `Read/Write` |

### Versioning and drafts

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `GET` | `/api/data-contracts/{contract_id}/versions` | List every visible version in the family | `Read-only` |
| `GET` | `/api/data-contracts/{contract_id}/version-history` | Version lineage with parent-child links | `Read-only` |
| `GET` | `/api/data-contracts/families/{family_id}/latest` | Resolve a family to its latest visible version | `Read-only` |
| `POST` | `/api/data-contracts/{contract_id}/versions` | Create a new version (metadata only) | `Read/Write` |
| `POST` | `/api/data-contracts/{contract_id}/clone` | Clone into a new version with all nested entities | `Read/Write` |
| `POST` | `/api/data-contracts/compare` | Compare two contract payloads | `Read-only` |
| `POST` | `/api/data-contracts/{contract_id}/clone-for-editing` | Create a personal draft | `Read/Write` |
| `GET` | `/api/data-contracts/{contract_id}/diff-from-parent` | Diff a draft against its parent | `Read-only` |
| `POST` | `/api/data-contracts/{contract_id}/commit` | Commit a personal draft | `Read/Write` |
| `DELETE` | `/api/data-contracts/{contract_id}/discard` | Discard a personal draft | `Read/Write` |
| `GET` | `/api/data-contracts/my-drafts` | List the caller's personal drafts | `Read-only` |

### Schemas and properties

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `GET` | `/api/data-contracts/{contract_id}/schemas` | List schema objects | `Read-only` |
| `POST` | `/api/data-contracts/{contract_id}/schemas` | Append a schema object | `Read/Write` |
| `DELETE` | `/api/data-contracts/{contract_id}/schemas/{schema_name}` | Delete a schema object | `Read/Write` |
| `GET` | `/api/data-contracts/{contract_id}/schemas/{schema_name}/properties` | List a schema's properties (paginated) | `Read-only` |

### Quality profiling

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-contracts/{contract_id}/profile` | Start DQX profiling | `Read/Write` |
| `GET` | `/api/data-contracts/{contract_id}/profile-runs` | List profiling runs | `Read-only` |
| `GET` | `/api/data-contracts/{contract_id}/profile-runs/{run_id}/suggestions` | List suggestions from a run | `Read-only` |
| `POST` | `/api/data-contracts/{contract_id}/suggestions/accept` | Accept suggestions | `Read/Write` |
| `PUT` | `/api/data-contracts/{contract_id}/suggestions/{suggestion_id}` | Edit a suggestion | `Read/Write` |
| `POST` | `/api/data-contracts/{contract_id}/suggestions/reject` | Reject suggestions | `Read/Write` |

### ODCS sub-resources

| Resource | Paths |
| --- | --- |
| Custom properties | `/api/data-contracts/{contract_id}/custom-properties[/{property_id}]` |
| Support channels | `/api/data-contracts/{contract_id}/support[/{channel_id}]` |
| Pricing | `/api/data-contracts/{contract_id}/pricing` |
| Roles | `/api/data-contracts/{contract_id}/roles[/{role_id}]` |
| Contract tags | `/api/data-contracts/{contract_id}/tags[/{tag_id}]` |
| Authoritative definitions | `/api/data-contracts/{contract_id}/…/authoritative-definitions[/{definition_id}]` (contract, schema, and property levels) |
| Relationships | `/api/data-contracts/{contract_id}/schemas/{schema_id}[/properties/{prop_id}]/relationships[/{rel_id}]` |
| Team metadata | `/api/data-contracts/{contract_id}/team-metadata` |
| Comments | `/api/data-contracts/{contract_id}/comments` |

### Assets and relationships

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-contracts/{contract_id}/link-assets` | Auto-link schemas to matching assets | `Read/Write` |
| `GET` | `/api/data-contracts/{contract_id}/entity-relationships` | Relationships involving this contract | `Read-only` |
| `GET` | `/api/data-contracts/{contract_id}/import-team-members` | Team members formatted for the ODCS `team` array | `Read/Write` |

## Core CRUD

### Create a contract

```http
POST /api/data-contracts
```

Creates a contract with a normalized ODCS structure. Only `name` is strictly required; everything else has ODCS-conformant defaults.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

A `DataContractCreate` object. Key fields:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `string` | Yes | Contract name. |
| `version` | `string` | No | Semantic version. Defaults to `1.0.0`. |
| `status` | `string` | No | Initial status. Defaults to `draft`. |
| `kind` | `string` | No | ODCS resource kind. Defaults to `DataContract`. |
| `apiVersion` | `string` | No | ODCS version. Defaults to `v3.1.0`. |
| `owner_team_id` | `string` | No | Owning team UUID. |
| `project_id` | `string` | No | Project association. |
| `domainId` / `domainIds` / `primaryDomainId` | `string` / `string[]` / `string` | No | Single (legacy) domain, the full multi-domain set, and which of them is primary. |
| `tenant` | `string` | No | Organization identifier. |
| `dataProduct` | `string` | No | Associated data product name. |
| `description` | `object` | No | `{ "usage", "purpose", "limitations" }`. |
| `schema` | `SchemaObject[]` | No | Schema objects with their properties. |
| `slaDefaultElement`, `slaProperties` | `string`, `SLAProperty[]` | No | ODCS SLA section. |
| `price` | `object` | No | Pricing information. |
| `team` | `TeamMember[]` | No | ODCS team members (`username`, `role`, and so on). |
| `roles` | `ContractRole[]` | No | ODCS roles. |
| `support` | `SupportChannel[]` | No | Support channels. |
| `servers` | `ServerConfig[]` | No | Server / infrastructure configuration. |
| `authoritativeDefinitions` | `object[]` | No | `{ "url", "type" }` entries. |
| `customProperties` | `object` | No | Free-form key-value properties. |
| `tags` | `AssignedTagCreate[]` | No | Namespaced tags. See [Tags](./tags#assigned-tag-payloads). |

```json
{
  "name": "customer-360-core",
  "version": "1.0.0",
  "status": "draft",
  "owner_team_id": "3a4b5c6d-7e8f-9012-3456-789abcdef012",
  "domainIds": ["8f2b1c34-0d1a-4e77-9a0b-5c6d7e8f9a01"],
  "primaryDomainId": "8f2b1c34-0d1a-4e77-9a0b-5c6d7e8f9a01",
  "description": {
    "usage": "Authoritative customer profile for analytics",
    "purpose": "Single view of the customer",
    "limitations": "Excludes prospects that have not consented"
  },
  "schema": [
    {
      "name": "customers",
      "physicalName": "main.customer_360.customers",
      "physicalType": "table",
      "properties": [
        { "name": "customer_id", "logicalType": "string", "required": true, "primaryKey": true },
        { "name": "email",       "logicalType": "string", "classification": "PII" }
      ]
    }
  ]
}
```

#### Response

`200 OK` — a `DataContractRead` object containing the full ODCS structure.

:::note
Creation returns `200`, not `201` — the route does not override FastAPI's default status code.
:::

#### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | The contract data failed validation. |
| `403 Forbidden` | `project_id` is set and the caller is not a member of that project. |

### List data contracts

```http
GET /api/data-contracts
```

Returns contracts visible to the caller, with lightweight `DataContractSummary` objects (no schemas, quality rules, or comments).

By default the response is **collapsed by version family**: one row per `versionFamilyId` — the newest version visible to the caller — plus a `versionCount` field. Set `include_history=true` to get every visible version instead.

**Authorization:** `data-contracts` — `Read-only`

#### Query parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `domain_id` | `string` | — | Filter by a single domain ID. |
| `domain_ids` | `string` | — | Filter by multiple domain IDs, comma-separated. |
| `project_id` | `string` | — | Filter by project. |
| `status` | `string` | — | Narrow to one lifecycle status, for example `draft`, `proposed`, `active`. |
| `include_history` | `boolean` | `false` | `true` returns every visible version rather than one row per family. |

:::info
The `status` filter is applied **after** the role-aware visibility filter, so it can only narrow the set a caller is already permitted to see.
:::

```bash
curl -s "$ONTOS_URL/api/data-contracts?status=active&domain_id=8f2b1c34-…" \
  -H "X-Forwarded-Email: alice@example.com"
```

#### Response

`200 OK` — an array of `DataContractSummary` objects.

```json
[
  {
    "id": "urn:datacontract:customer:customer-360-core",
    "name": "customer-360-core",
    "version": "2.1.0",
    "status": "active",
    "kind": "DataContract",
    "apiVersion": "v3.1.0",
    "owner_team_id": "3a4b5c6d-…",
    "owner_team_name": "customer-data-platform",
    "project_id": "7c8d9e0f-…",
    "project_name": "customer-360-migration",
    "domain": "customer-360",
    "domainId": "8f2b1c34-…",
    "domainIds": ["8f2b1c34-…"],
    "primaryDomainId": "8f2b1c34-…",
    "versionFamilyId": "urn:datacontract:customer:customer-360-core",
    "versionCount": 4,
    "parentContractId": "urn:…:v2.0.0",
    "changeSummary": "Added consent columns",
    "draftOwnerId": null,
    "schemaObjectCount": 3,
    "publication_scope": "organization",
    "published_at": "2026-07-01T09:00:00Z",
    "published_by": "alice@example.com",
    "tags": [],
    "created": "2026-01-15T08:00:00Z",
    "updated": "2026-07-01T09:00:00Z"
  }
]
```

### Count contracts

```http
GET /api/data-contracts/count
```

Returns the total number of contracts without loading any relationships — a cheap operation for dashboards.

**Authorization:** `data-contracts` — `Read-only`

#### Response

`200 OK`

```json
{ "count": 128 }
```

### Get a contract

```http
GET /api/data-contracts/{contract_id}
```

Returns the full ODCS structure, including schemas with properties, quality rules, SLA, servers, roles, support, pricing, and team.

**Authorization:** `data-contracts` — `Read-only`

#### Response

`200 OK` — a `DataContractRead` object.

#### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No contract with that ID. |

### Update a contract

```http
PUT /api/data-contracts/{contract_id}
```

Partial update — omitted fields are left unchanged. Passing `schema` replaces the contract's schema objects wholesale; use the [schema operations](#schemas-and-properties-1) to change one schema at a time.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

A `DataContractUpdate` object. Accepts the same fields as create, all optional, plus versioning fields (`parentContractId`, `versionFamilyId`, `changeSummary`).

```json
{
  "status": "proposed",
  "description": { "usage": "Authoritative customer profile for analytics and ML" },
  "changeSummary": "Clarified usage guidance"
}
```

#### Response

`200 OK` — the updated `DataContractRead` object.

#### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | The contract data is invalid, or a blocking pre-update workflow failed. In the latter case `detail` is an object carrying `message` and the failed `workflows`. |
| `403 Forbidden` | The caller is not a member of the contract's project. |
| `404 Not Found` | No contract with that ID. |

### Delete a contract

```http
DELETE /api/data-contracts/{contract_id}
```

**Authorization:** `data-contracts` — `Read/Write`

#### Response

`204 No Content`

#### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No contract with that ID. |

## Import and export

### Upload a contract file

```http
POST /api/data-contracts/upload
```

Uploads an ODCS contract file and parses it into the normalized structure. Accepts JSON, YAML, and text files that follow the ODCS schema.

**Authorization:** `data-contracts` — `Read/Write`

#### Request

`multipart/form-data` with a single `file` part.

```bash
curl -s -X POST "$ONTOS_URL/api/data-contracts/upload" \
  -H "X-Forwarded-Email: alice@example.com" \
  -F "file=@customer-360-core.odcs.yaml"
```

#### Response

`200 OK` — the created contract, plus parse diagnostics.

### Import ODCS JSON

```http
POST /api/data-contracts/odcs/import
```

Imports a contract from a pasted ODCS JSON object rather than a file upload.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

The ODCS contract document itself, as a JSON object.

#### Response

`200 OK` — the created contract.

### Export as ODCS

```http
GET /api/data-contracts/{contract_id}/odcs/export
```

Rebuilds the ODCS document from the normalized database representation and returns it as YAML.

**Authorization:** `data-contracts` — `Read-only`

```bash
curl -s "$ONTOS_URL/api/data-contracts/urn:datacontract:customer:customer-360-core/odcs/export" \
  -H "X-Forwarded-Email: alice@example.com" \
  -o customer-360-core.odcs.yaml
```

#### Response

`200 OK` — the ODCS document as YAML.

#### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No contract with that ID. |

### Get the ODCS JSON Schema

```http
GET /api/data-contracts/schema/odcs
```

Returns the ODCS v3.1.0 JSON Schema bundled with Ontos — useful for client-side validation before upload.

**Authorization:** `data-contracts` — `Read-only`

#### Response

`200 OK` — the JSON Schema document.

## Lifecycle, review, and approval

### Change status

```http
POST /api/data-contracts/{contract_id}/change-status
```

Changes status directly, validating the transition against the [lifecycle table](#lifecycle).

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `new_status` | `string` | Yes | Target status. |

```json
{ "new_status": "proposed" }
```

#### Response

`200 OK`

```json
{ "status": "proposed", "from": "draft", "to": "proposed" }
```

#### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | The transition is not allowed from the current status. |
| `404 Not Found` | No contract with that ID. |

### Approve a contract

```http
POST /api/data-contracts/{contract_id}/approve
```

Moves a contract from `proposed` or `under_review` to `approved`.

**Authorization:** `CONTRACTS` approval privilege

#### Response

`200 OK`

### Reject a contract

```http
POST /api/data-contracts/{contract_id}/reject
```

Returns a `proposed` or `under_review` contract to `draft` for revision.

**Authorization:** `CONTRACTS` approval privilege

#### Response

`200 OK`

### Request a steward review

```http
POST /api/data-contracts/{contract_id}/request-review
```

Notifies data stewards that the contract is ready for review.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

Optional. Defaults to an empty payload.

| Field | Type | Description |
| --- | --- | --- |
| `message` | `string` | Note for the reviewers. |

```json
{ "message": "Consent columns added — please review the classification." }
```

#### Response

`200 OK`

### Handle a review decision

```http
POST /api/data-contracts/{contract_id}/handle-review
```

Records a steward's decision on a review request.

**Authorization:** `data-asset-reviews` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `decision` | `"approve" \| "reject" \| "clarify"` | Yes | The steward's decision. |
| `message` | `string` | No | Explanation sent back to the requester. |

#### Response

`200 OK`

### Request a status change

```http
POST /api/data-contracts/{contract_id}/request-status-change
```

Asks an approver to move the contract to a target status. Requires only `Read-only` access — requesting is not itself a mutation of the contract.

**Authorization:** `data-contracts` — `Read-only`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `target_status` | `string` | Yes | Requested status. |
| `justification` | `string` | Yes | Why the change is needed. |
| `current_status` | `string` | No | Current status, for reference. |

#### Response

`200 OK`

### Handle a status change request

```http
POST /api/data-contracts/{contract_id}/handle-status-change
```

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `decision` | `"approve" \| "deny" \| "clarify"` | Yes | Decision on the request. |
| `target_status` | `string` | Yes | The status that was requested. |
| `requester_email` | `string` | Yes | Email of the original requester. |
| `message` | `string` | No | Message from the approver. |

#### Response

`200 OK`

## Certification

### Request certification

```http
POST /api/data-contracts/{contract_id}/request-certify
```

Starts the certification workflow. Approvers then call [handle-certify](#handle-a-certification-request).

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `certification_level` | `integer` | Yes | Target certification level (matches a configured level's order). |
| `message` | `string` | No | Note for the approvers. |

```json
{ "certification_level": 2, "message": "All quality checks green for two quarters." }
```

#### Response

`200 OK`

### Handle a certification request

```http
POST /api/data-contracts/{contract_id}/handle-certify
```

**Authorization:** `CONTRACTS` approval privilege

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `approved` | `boolean` | Yes | Whether the request is granted. |
| `certification_level` | `integer` | No | Level to grant, when it differs from the request. |
| `notes` | `string` | No | Approver notes. |

#### Response

`200 OK`

### Certify directly

```http
POST /api/data-contracts/{contract_id}/certify
```

Certifies a contract at a specific level without going through the request workflow. The contract must be `active`.

**Authorization:** `CONTRACTS` approval privilege

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `certification_level` | `integer` | Yes | Certification level to apply. |
| `notes` | `string` | No | Certification notes. |

#### Response

`200 OK`

#### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | Contract not found, or no such certification level. |
| `409 Conflict` | The contract is not `active`. |
| `422 Unprocessable Entity` | `certification_level` is missing. |

### Decertify

```http
POST /api/data-contracts/{contract_id}/decertify
```

Removes the contract's certification.

**Authorization:** `CONTRACTS` approval privilege

#### Response

`200 OK`

## Publication and deployment

### Set publication scope

```http
POST /api/data-contracts/{contract_id}/set-publication-scope
```

Controls how widely the contract is published. The contract must be `active` or `approved` to be published; setting the scope back to `none` unpublishes it and fires the `on_unpublish` workflow trigger.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `scope` | `"none" \| "domain" \| "organization" \| "external"` | `none` | Target publication scope. |

```json
{ "scope": "organization" }
```

#### Response

`200 OK`

#### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No contract with that ID. |
| `409 Conflict` | The contract is not `active` or `approved` and `scope` is not `none`. |
| `422 Unprocessable Entity` | `scope` is not one of the four allowed values. |

### Request publication

```http
POST /api/data-contracts/{contract_id}/request-publish
```

Requests that an approved contract be published to the marketplace.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

Optional; defaults are applied when omitted.

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `justification` | `string` | — | Why the contract should be published. |
| `scope` | `string` | `organization` | Requested publication scope. |

#### Response

`200 OK`

### Handle a publication request

```http
POST /api/data-contracts/{contract_id}/handle-publish
```

**Authorization:** `CONTRACTS` approval privilege

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `decision` | `"approve" \| "deny"` | Yes | Decision on the request. |
| `message` | `string` | No | Message from the approver. |

#### Response

`200 OK`

### Request deployment to Unity Catalog

```http
POST /api/data-contracts/{contract_id}/request-deploy
```

Requests approval to materialize the contract's schemas in Unity Catalog. The requested target is validated against the configured deployment policy.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

Optional.

| Field | Type | Description |
| --- | --- | --- |
| `catalog` | `string` | Target Unity Catalog catalog. |
| `schema` | `string` | Target schema. |
| `message` | `string` | Note for the approvers. |

```json
{ "catalog": "main", "schema": "customer_360", "message": "Deploying v2.1.0" }
```

#### Response

`200 OK`

### Handle a deployment request

```http
POST /api/data-contracts/{contract_id}/handle-deploy
```

Decides a deployment request and, optionally, executes the deployment in the same call.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `decision` | `"approve" \| "deny"` | — | Decision on the request. Required. |
| `message` | `string` | — | Message from the approver. |
| `execute_deployment` | `boolean` | `false` | When `true`, actually trigger the deployment after approving. |

#### Response

`200 OK`

## Versioning and drafts

Ontos groups every version of a contract into a **version family** identified by `versionFamilyId`. Personal drafts (tier 1) are visible only to their owner; committing promotes a draft to team and project visibility (tier 2).

### List versions

```http
GET /api/data-contracts/{contract_id}/versions
```

Returns every visible version of the contract's family, newest first. Personal drafts owned by other users are hidden.

**Authorization:** `data-contracts` — `Read-only`

#### Response

`200 OK` — an array of version objects.

### Get version history

```http
GET /api/data-contracts/{contract_id}/version-history
```

Returns the version lineage with parent-child relationships, for rendering a version graph.

**Authorization:** `data-contracts` — `Read-only`

#### Response

`200 OK` — a lineage object.

### Resolve a family's latest version

```http
GET /api/data-contracts/families/{family_id}/latest
```

Resolves a "follow latest" family reference to a concrete contract row, using the role-aware visibility rank. Use this when you store a `contract_family_id` rather than a pinned version.

**Authorization:** `data-contracts` — `Read-only`

#### Response

`200 OK` — the latest visible contract in the family.

### Create a new version

```http
POST /api/data-contracts/{contract_id}/versions
```

Creates a lightweight new version — metadata only, without cloning nested entities. Use [clone](#clone-into-a-new-version) when you need the schemas and sub-resources copied too.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `new_version` | `string` | Yes | New semantic version, for example `1.1.0`. |

#### Response

`200 OK` — the new version's identity fields.

#### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | `new_version` is missing. |

### Clone into a new version

```http
POST /api/data-contracts/{contract_id}/clone
```

Clones a contract into a new version, copying all nested entities (schemas, properties, roles, support channels, and so on).

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `new_version` | `string` | Yes | Version for the clone. |
| `change_summary` | `string` | No | Summary of what changed. |

#### Response

`201 Created` — the cloned contract.

#### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | `new_version` is missing, or the contract data is invalid. |

### Compare two contracts

```http
POST /api/data-contracts/compare
```

Analyzes the differences between two contract payloads and recommends a semantic version bump.

**Authorization:** `data-contracts` — `Read-only`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `old_contract` | `object` | Yes | The baseline contract document. |
| `new_contract` | `object` | Yes | The candidate contract document. |

#### Response

`200 OK` — a diff analysis with a suggested bump (`major`, `minor`, or `patch`).

### Clone for editing (create a personal draft)

```http
POST /api/data-contracts/{contract_id}/clone-for-editing
```

Creates a personal draft visible only to the caller. The draft's version is set to `{parent_version}-draft` as a placeholder until it is committed.

**Authorization:** `data-contracts` — `Read/Write`

#### Response

`201 Created` — the new draft contract.

### Diff a draft against its parent

```http
GET /api/data-contracts/{contract_id}/diff-from-parent
```

Compares a draft to the version it was cloned from and suggests a version bump.

**Authorization:** `data-contracts` — `Read-only`

#### Response

`200 OK`

| Field | Type | Description |
| --- | --- | --- |
| `parent_version` | `string` | The parent's version. |
| `parent_status` | `string` | The parent's status. |
| `suggested_bump` | `"major" \| "minor" \| "patch"` | Recommended bump. |
| `suggested_version` | `string` | Recommended version string. |
| `analysis` | `object` | Detailed change analysis. |

### Commit a personal draft

```http
POST /api/data-contracts/{contract_id}/commit
```

Promotes a personal draft from tier 1 (owner only) to tier 2 (team and project members), assigning it a final version.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `new_version` | `string` | Yes | Final semantic version, for example `1.1.0`. |
| `change_summary` | `string` | Yes | Summary of changes in this version. |

```json
{ "new_version": "2.2.0", "change_summary": "Added consent and preference columns" }
```

#### Response

`200 OK` — the committed contract's identity fields.

### Discard a personal draft

```http
DELETE /api/data-contracts/{contract_id}/discard
```

Deletes a personal draft and all its child entities. Only the draft's owner may discard it.

**Authorization:** `data-contracts` — `Read/Write`

#### Response

`200 OK`

### List the caller's drafts

```http
GET /api/data-contracts/my-drafts
```

**Authorization:** `data-contracts` — `Read-only`

#### Query parameters

| Name | Type | Default | Constraints |
| --- | --- | --- | --- |
| `skip` | `integer` | `0` | `>= 0` |
| `limit` | `integer` | `100` | `1`–`1000` |

#### Response

`200 OK` — an array of the caller's personal drafts.

## Schemas and properties

### List schema objects

```http
GET /api/data-contracts/{contract_id}/schemas
```

Returns the contract's schema objects with property counts but without loading the properties themselves.

**Authorization:** `data-contracts` — `Read-only`

#### Response

`200 OK` — an array of schema summaries.

```json
[
  {
    "id": "d1e2f3a4-…",
    "name": "customers",
    "physicalName": "main.customer_360.customers",
    "businessName": "Customers",
    "physicalType": "table",
    "description": "One row per consented customer",
    "propertyCount": 42
  }
]
```

#### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No contract with that ID. |

### Append a schema object

```http
POST /api/data-contracts/{contract_id}/schemas
```

Appends a single schema object — with its properties — without touching the contract's existing schemas.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

A `SchemaObject`. Key fields:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `string` | Yes | Logical schema object name. |
| `physicalName` | `string` | No | Fully qualified physical name. |
| `physicalType` | `string` | No | `table`, `view`, and so on. |
| `businessName` | `string` | No | Business-facing name. |
| `description` | `string` | No | Description. |
| `properties` | `ColumnProperty[]` | No | Columns. Each requires `name` and `logicalType`. |
| `quality` | `QualityRule[]` | No | ODCS quality rules scoped to this schema. |
| `relationships` | `SchemaRelationship[]` | No | Schema-level foreign keys. |
| `authoritativeDefinitions` | `object[]` | No | `{ "url", "type" }` entries. |
| `customProperties` | `object[]` | No | Free-form properties. |

```json
{
  "name": "customer_consent",
  "physicalName": "main.customer_360.customer_consent",
  "physicalType": "table",
  "properties": [
    { "name": "customer_id",  "logicalType": "string", "required": true, "primaryKey": true },
    { "name": "consent_type", "logicalType": "string", "required": true },
    { "name": "granted_at",   "logicalType": "date" }
  ]
}
```

#### Response

`201 Created`

```json
{ "status": "ok", "schema_name": "customer_consent" }
```

### Delete a schema object

```http
DELETE /api/data-contracts/{contract_id}/schemas/{schema_name}
```

Deletes one schema by name, leaving the contract's other schemas untouched.

**Authorization:** `data-contracts` — `Read/Write`

#### Response

`204 No Content`

### List schema properties

```http
GET /api/data-contracts/{contract_id}/schemas/{schema_name}/properties
```

Returns a paginated list of the schema's properties.

**Authorization:** `data-contracts` — `Read-only`

#### Query parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `skip` | `integer` | `0` | Records to skip. |
| `limit` | `integer` | `50` | Maximum records. Use `limit=0` to return **all** properties without pagination. |

#### Response

`200 OK`

```json
{
  "items": [
    {
      "name": "customer_id",
      "logicalType": "string",
      "physicalType": "STRING",
      "required": true,
      "unique": true,
      "primaryKey": true,
      "primaryKeyPosition": 1,
      "partitioned": false,
      "partitionKeyPosition": -1,
      "classification": null,
      "businessName": "Customer ID",
      "criticalDataElement": true
    }
  ],
  "total": 42,
  "skip": 0,
  "limit": 50
}
```

#### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No schema with that name on the contract. |

## Quality profiling

### Start profiling

```http
POST /api/data-contracts/{contract_id}/profile
```

Starts a DQX profiling run for selected schemas. The run executes as a background job and produces quality-check suggestions.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

| Field | Type | Description |
| --- | --- | --- |
| `schema_names` | `string[]` | Schemas to profile. Defaults to an empty list. |

```json
{ "schema_names": ["customers", "customer_consent"] }
```

#### Response

`200 OK` — the run identity and status.

### List profiling runs

```http
GET /api/data-contracts/{contract_id}/profile-runs
```

**Authorization:** `data-contracts` — `Read-only`

#### Response

`200 OK` — an array of runs with suggestion counts.

### List suggestions from a run

```http
GET /api/data-contracts/{contract_id}/profile-runs/{run_id}/suggestions
```

**Authorization:** `data-contracts` — `Read-only`

#### Response

`200 OK` — an array of suggested quality checks.

### Accept suggestions

```http
POST /api/data-contracts/{contract_id}/suggestions/accept
```

Adds the selected suggestions to the contract as quality rules, optionally bumping the contract version.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

| Field | Type | Description |
| --- | --- | --- |
| `suggestion_ids` | `string[]` | Suggestions to accept. Defaults to an empty list. |
| `bump_version` | `string` | Optional version to bump the contract to. |

#### Response

`200 OK`

### Edit a suggestion

```http
PUT /api/data-contracts/{contract_id}/suggestions/{suggestion_id}
```

Edits a suggestion before it is accepted.

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

The suggestion fields to change, as a JSON object.

#### Response

`200 OK`

### Reject suggestions

```http
POST /api/data-contracts/{contract_id}/suggestions/reject
```

**Authorization:** `data-contracts` — `Read/Write`

#### Request body

| Field | Type | Description |
| --- | --- | --- |
| `suggestion_ids` | `string[]` | Suggestions to reject. |

#### Response

`200 OK`

## ODCS sub-resources

These collections all follow the same shape: `GET` to list, `POST` to create (`201`), `PUT` to update, `DELETE` to remove (`204`). Reads require `Read-only` and writes require `Read/Write` on `data-contracts`. A missing contract or sub-resource yields `404`.

### Custom properties

```
GET    /api/data-contracts/{contract_id}/custom-properties
POST   /api/data-contracts/{contract_id}/custom-properties
PUT    /api/data-contracts/{contract_id}/custom-properties/{property_id}
DELETE /api/data-contracts/{contract_id}/custom-properties/{property_id}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `property` | `string` | Yes (create) | Property key. Maximum 255 characters. |
| `value` | `string` | No | Property value. |

```json
{ "property": "retention_days", "value": "2555" }
```

### Support channels

```
GET    /api/data-contracts/{contract_id}/support
POST   /api/data-contracts/{contract_id}/support
PUT    /api/data-contracts/{contract_id}/support/{channel_id}
DELETE /api/data-contracts/{contract_id}/support/{channel_id}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `channel` | `string` | Yes (create) | Channel type, for example `email`, `slack`, `teams`. |
| `url` | `string` | Yes (create) | Channel URL. |
| `description` | `string` | No | Description. |
| `tool` | `string` | No | Tool name, for example `Slack`, `JIRA`. |
| `scope` | `string` | No | Support scope, for example `technical`, `business`. |
| `invitation_url` | `string` | No | Invitation or join URL. |

```json
{
  "channel": "slack",
  "url": "https://example.slack.com/archives/C012345",
  "tool": "Slack",
  "scope": "technical",
  "description": "Primary support channel for schema questions"
}
```

### Pricing

```
GET /api/data-contracts/{contract_id}/pricing
PUT /api/data-contracts/{contract_id}/pricing
```

Pricing is a **singleton** per contract: `GET` returns an empty object when unset, and `PUT` creates or updates it.

| Field | Type | Description |
| --- | --- | --- |
| `price_amount` | `string` | Price amount. |
| `price_currency` | `string` | Currency code, for example `USD`. Maximum 10 characters. |
| `price_unit` | `string` | Unit, for example `per GB`, `per query`. Maximum 50 characters. |

```json
{ "price_amount": "0.05", "price_currency": "USD", "price_unit": "per GB scanned" }
```

### Roles

```
GET    /api/data-contracts/{contract_id}/roles
POST   /api/data-contracts/{contract_id}/roles
PUT    /api/data-contracts/{contract_id}/roles/{role_id}
DELETE /api/data-contracts/{contract_id}/roles/{role_id}
```

Roles carry nested custom properties. On update, supplying `custom_properties` replaces the existing set; deleting a role cascades to its properties.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `role` | `string` | Yes (create) | Role name, for example `Data Steward`, `Consumer`. |
| `description` | `string` | No | Role description. |
| `access` | `string` | No | Access level or permissions. |
| `first_level_approvers` | `string` | No | Comma-separated approvers. |
| `second_level_approvers` | `string` | No | Comma-separated approvers. |
| `custom_properties` | `object[]` | No | `{ "property", "value" }` entries. |

```json
{
  "role": "Data Steward",
  "access": "read_write",
  "first_level_approvers": "alice@example.com,bob@example.com",
  "custom_properties": [{ "property": "sla_hours", "value": "24" }]
}
```

### ODCS top-level tags

```
GET    /api/data-contracts/{contract_id}/tags
POST   /api/data-contracts/{contract_id}/tags
PUT    /api/data-contracts/{contract_id}/tags/{tag_id}
DELETE /api/data-contracts/{contract_id}/tags/{tag_id}
```

These are the **simple, string-valued** ODCS top-level tags. They are distinct from the namespaced, governed tags in the [Tags API](./tags) — a contract can carry both.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `string` | Yes | Tag name. 1–255 characters. |

```json
{ "name": "gold-layer" }
```

### Authoritative definitions

Authoritative definitions link a contract, schema, or property to an external source of truth. The same payload works at all three levels.

```
# Contract level
GET|POST     /api/data-contracts/{contract_id}/authoritative-definitions
PUT|DELETE   /api/data-contracts/{contract_id}/authoritative-definitions/{definition_id}

# Schema level — schema_id accepts either the schema UUID or the schema name
GET|POST     /api/data-contracts/{contract_id}/schemas/{schema_id}/authoritative-definitions
PUT|DELETE   /api/data-contracts/{contract_id}/schemas/{schema_id}/authoritative-definitions/{definition_id}

# Property level
GET|POST     /api/data-contracts/{contract_id}/schemas/{schema_id}/properties/{property_id}/authoritative-definitions
PUT|DELETE   /api/data-contracts/{contract_id}/schemas/{schema_id}/properties/{property_id}/authoritative-definitions/{definition_id}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `url` | `string` | Yes (create) | URL of the authoritative source. |
| `type` | `string` | Yes (create) | Type of authority, for example `glossary`, `standard`, `documentation`. |

```json
{ "url": "https://glossary.example.com/terms/customer", "type": "glossary" }
```

Responses include exactly one populated context field — `contract_id`, `schema_object_id`, or `property_id` — depending on the level.

### Relationships

ODCS v3.1.0 relationships (foreign keys) exist at both schema and property level.

```
# Schema level
GET|POST     /api/data-contracts/{contract_id}/schemas/{schema_id}/relationships
PUT|DELETE   /api/data-contracts/{contract_id}/schemas/{schema_id}/relationships/{rel_id}

# Property level
GET|POST     /api/data-contracts/{contract_id}/schemas/{schema_id}/properties/{prop_id}/relationships
PUT|DELETE   /api/data-contracts/{contract_id}/schemas/{schema_id}/properties/{prop_id}/relationships/{rel_id}
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `type` | `string` | `foreignKey` | Relationship type. |
| `from` | `string \| string[]` | — | Source column(s). |
| `to` | `string \| string[]` | `""` | Target column(s), typically `schema.column`. |
| `customProperties` | `object[]` | — | Free-form properties. |

```json
{
  "type": "foreignKey",
  "from": "customer_id",
  "to": "customers.customer_id"
}
```

### Team metadata

```
GET /api/data-contracts/{contract_id}/team-metadata
PUT /api/data-contracts/{contract_id}/team-metadata
```

Manages the ODCS v3.1.0 `Team` object's own metadata — distinct from the individual team members in the contract's `team` array.

| Field | Type | Description |
| --- | --- | --- |
| `name` | `string` | Team name. |
| `description` | `string` | Team description. |
| `tags` | `string[]` | Simple tags. |
| `customProperties` | `object[]` | Free-form properties. |
| `authoritativeDefinitions` | `object[]` | `{ "url", "type" }` entries. |

### Comments

```
GET  /api/data-contracts/{contract_id}/comments
POST /api/data-contracts/{contract_id}/comments
```

Comments are returned oldest-first.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `message` | `string` | Yes | Comment text. |

```json
{ "message": "Confirmed the consent columns match the ODCS classification guidance." }
```

Read shape: `{ "id", "author", "message", "created_at" }`.

## Assets and relationships

### Auto-link schemas to assets

```http
POST /api/data-contracts/{contract_id}/link-assets
```

Matches the contract's schema objects against Table and View assets in Ontos and creates the relationships: `implementsContract` from each matching asset to this contract, and `governedBy` from the parent datasets.

**Authorization:** `data-contracts` — `Read/Write`

#### Response

`200 OK` — a summary of the links created.

### Get entity relationships

```http
GET /api/data-contracts/{contract_id}/entity-relationships
```

Returns the entity relationships involving this contract, such as incoming `governedBy` edges.

**Authorization:** `data-contracts` — `Read-only`

#### Response

`200 OK`

### Import team members

```http
GET /api/data-contracts/{contract_id}/import-team-members
```

Returns an Ontos team's members formatted for the contract's ODCS `team` array, ready to be merged into an update.

**Authorization:** `data-contracts` — `Read/Write`

#### Query parameters

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `team_id` | `string` | Yes | Ontos team to import from. |

#### Response

`200 OK` — an array of ODCS team member objects.

## See also

- [Define Data Contracts](../../user_guide/data_contracts) — the user-facing guide, including the lifecycle diagram and a sample ODCS document.
- [Data Products API](./data_products) — products reference contracts through their output ports.
- [Tags API](./tags) — namespaced tags applied to contracts.
- [Costs API](./costs) — attach cost items using entity type `data_contract`.

---
sidebar_position: 5
id: data_products
title: data product
description: Create, version, review, certify, publish, and subscribe to ODPS v1.0.0 data products.
---

# Data Product

Data Products implement the [Open Data Product Standard (ODPS) v1.0.0](https://bitol-io.github.io/open-data-product-standard/). A product bundles input ports, output ports (each optionally governed by a data contract), management ports, support channels, and team information, and moves through a lifecycle from draft to active and beyond. Consumers subscribe to products to be notified about status changes, compliance violations, and new versions.

**Swagger tag:** `Data Products` &nbsp;·&nbsp; **Feature ID:** `data-products` &nbsp;·&nbsp; **Route prefix:** `/api/data-products`

:::tip
Approve, reject, certify, decertify, and the certification and publication *decision* operations are gated by the **`PRODUCTS` approval privilege** (`ApprovalChecker`) rather than by a feature access level.
:::

## Lifecycle

`DataProductStatus` values:

`draft` · `sandbox` · `proposed` · `under_review` · `approved` · `active` · `deprecated` · `retired`

Typical progression, with the operation that drives each step:

```text
draft ──move-to-sandbox──▶ sandbox
  │                          │
  └────submit-review─────────┴──▶ proposed ──▶ under_review
                                                 │
                              ┌──────approve─────┘
                              ▼
                           approved ──publish──▶ active ──deprecate──▶ deprecated
                              ▲                    │
                              └──────reject────────┘ (returns to draft)
```

Certification is a **separate dimension** from status: an `active` product can be certified at a level without its status changing. Publication is a third dimension, controlled by `publication_scope` (`none`, `domain`, `organization`, `external`).

## Operations at a glance

### Core CRUD

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-products` | Create a product | `Read/Write` |
| `GET` | `/api/data-products` | List products | `Read-only` |
| `GET` | `/api/data-products/{product_id}` | Get a product | `Read-only` |
| `PUT` | `/api/data-products/{product_id}` | Update a product | `Read/Write` |
| `DELETE` | `/api/data-products/{product_id}` | Delete a product | `Admin` |
| `POST` | `/api/data-products/upload` | Upload products from a file | `Read/Write` |

### Lookups and marketplace

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `GET` | `/api/data-products/statuses` | Distinct statuses in use | `Read-only` |
| `GET` | `/api/data-products/types` | Distinct product types in use | `Read-only` |
| `GET` | `/api/data-products/owners` | Distinct owners in use | `Read-only` |
| `GET` | `/api/data-products/published` | Products published to the marketplace | `Read-only` |
| `GET` | `/api/data-products/my-subscriptions` | Products the caller is subscribed to | Authenticated |

### Lifecycle

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-products/{product_id}/move-to-sandbox` | `draft` → `sandbox` | `Read/Write` |
| `POST` | `/api/data-products/{product_id}/submit-review` | `draft`/`sandbox` → `proposed` | `Read/Write` |
| `POST` | `/api/data-products/{product_id}/submit-certification` | Alias of `submit-review` | `Read/Write` |
| `POST` | `/api/data-products/{product_id}/request-review` | Request a steward review, with notifications | `Read/Write` |
| `POST` | `/api/data-products/{product_id}/approve` | `under_review` → `approved` | `PRODUCTS` approval |
| `POST` | `/api/data-products/{product_id}/reject` | `under_review` → `draft` | `PRODUCTS` approval |
| `POST` | `/api/data-products/{product_id}/publish` | `approved` → `active` | `Read/Write` |
| `POST` | `/api/data-products/{product_id}/deprecate` | `active`/certified → `deprecated` | `Read/Write` |
| `POST` | `/api/data-products/{product_id}/change-status` | Change status directly | `Read/Write` |
| `POST` | `/api/data-products/{product_id}/request-status-change` | Request a status change | `Read-only` |
| `POST` | `/api/data-products/{product_id}/handle-status-change` | Decide a status change request | `Read/Write` |

### Certification

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-products/{product_id}/request-certify` | Request certification | `Read/Write` |
| `POST` | `/api/data-products/{product_id}/handle-certify` | Decide a certification request | `PRODUCTS` approval |
| `POST` | `/api/data-products/{product_id}/certify` | Certify directly | `PRODUCTS` approval |
| `POST` | `/api/data-products/{product_id}/decertify` | Remove certification | `PRODUCTS` approval |

### Publication

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-products/{product_id}/set-publication-scope` | Set publication scope | `Read/Write` |
| `POST` | `/api/data-products/{product_id}/unpublish` | Remove from the marketplace | `Read/Write` |
| `POST` | `/api/data-products/{product_id}/request-publish` | Request publication | `Read/Write` |
| `POST` | `/api/data-products/{product_id}/handle-publish` | Decide a publication request | `PRODUCTS` approval |

### Versioning and drafts

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `GET` | `/api/data-products/{product_id}/versions` | List every visible version in the family | `Read-only` |
| `GET` | `/api/data-products/families/{family_id}/latest` | Resolve a family to its latest visible version | `Read-only` |
| `POST` | `/api/data-products/{product_id}/versions` | Create a new version | `Read/Write` |
| `POST` | `/api/data-products/compare` | Compare two product payloads | `Read-only` |
| `POST` | `/api/data-products/{product_id}/clone-for-editing` | Create a personal draft | `Read/Write` |
| `GET` | `/api/data-products/{product_id}/diff-from-parent` | Diff a draft against its parent | `Read-only` |
| `POST` | `/api/data-products/{product_id}/commit` | Commit a personal draft | `Read/Write` |
| `DELETE` | `/api/data-products/{product_id}/discard` | Discard a personal draft | `Read/Write` |

### Contracts, datasets, and assets

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-products/from-contract` | Create a product from a data contract | `Read/Write` |
| `GET` | `/api/data-products/by-contract/{contract_id}` | Products whose output ports use a contract | `Read-only` |
| `GET` | `/api/data-products/{product_id}/contracts` | Contract IDs used by a product | `Read-only` |
| `GET` | `/api/data-products/{product_id}/datasets` | Datasets linked to a product | `Read-only` |
| `POST` | `/api/data-products/{product_id}/datasets` | Link a dataset | `Read/Write` |
| `DELETE` | `/api/data-products/{product_id}/datasets/{dataset_id}` | Unlink a dataset | `Read/Write` |
| `GET` | `/api/data-products/{product_id}/assets` | Assets linked to a product | `Read-only` |
| `GET` | `/api/data-products/{product_id}/hierarchy` | Product → dataset → table → column hierarchy | `Read-only` |
| `GET` | `/api/data-products/{product_id}/odps/export` | Export as ODPS YAML | `Read-only` |
| `GET` | `/api/data-products/{product_id}/import-team-members` | Team members for the ODPS `team` array | `Read/Write` |

### Subscriptions

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-products/{product_id}/subscribe` | Subscribe the caller | Authenticated |
| `DELETE` | `/api/data-products/{product_id}/subscribe` | Unsubscribe the caller | Authenticated |
| `GET` | `/api/data-products/{product_id}/subscription` | Caller's subscription status | Authenticated |
| `GET` | `/api/data-products/{product_id}/subscribers` | Full subscriber list | `Read/Write` |
| `GET` | `/api/data-products/{product_id}/subscriber-count` | Subscriber count | Authenticated |

### Genie

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-products/genie-space` | Create a Genie Space from products | `Read/Write` |

## Core CRUD

### Create a data product

```http
POST /api/data-products
```

**Authorization:** `data-products` — `Read/Write`

#### Request body

An ODPS v1.0.0 product document. `id` and `status` are required; everything else is optional.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | `string` | Yes | Unique product identifier. |
| `status` | `string` | Yes | Initial status, typically `draft`. |
| `apiVersion` | `string` | No | ODPS version. Defaults to `v1.0.0`. |
| `kind` | `string` | No | Resource kind. Defaults to `DataProduct`. |
| `name` | `string` | No | Product name. |
| `version` | `string` | No | Product version. |
| `domain_ids` / `primary_domain_id` | `string[]` / `string` | No | Assigned domains and which one is primary. |
| `tenant` | `string` | No | Organization identifier. |
| `owner_team_id` | `string` | No | Owning team UUID. |
| `project_id` | `string` | No | Project association. |
| `description` | `object` | No | Structured description. |
| `inputPorts` | `InputPort[]` | No | Input ports. |
| `outputPorts` | `OutputPort[]` | No | Output ports. Each may carry a `dataContractId`. |
| `managementPorts` | `ManagementPort[]` | No | Management ports. |
| `support` | `Support[]` | No | Support channels. |
| `team` | `object` | No | ODPS team object. |
| `tags` | `AssignedTagCreate[]` | No | Namespaced tags. See [Tags](./tags#assigned-tag-payloads). |
| `customProperties` | `CustomProperty[]` | No | Free-form properties. |
| `authoritativeDefinitions` | `object[]` | No | `{ "url", "type" }` entries. |
| `consumer_principals` | `ConsumerPrincipal[]` | No | Expected consumers, as `{ "type": "user" \| "group" \| "service_principal", "value": "…" }`. Validated against the workspace SCIM directory. |
| `max_level_inheritance` | `integer` | No | Maximum metadata level inherited from contracts. `0`–`999`, defaults to `99`. |

```json
{
  "apiVersion": "v1.0.0",
  "kind": "DataProduct",
  "id": "dp-customer-churn",
  "name": "Customer Churn Signals",
  "version": "1.0.0",
  "status": "draft",
  "owner_team_id": "3a4b5c6d-7e8f-9012-3456-789abcdef012",
  "domain_ids": ["8f2b1c34-0d1a-4e77-9a0b-5c6d7e8f9a01"],
  "primary_domain_id": "8f2b1c34-0d1a-4e77-9a0b-5c6d7e8f9a01",
  "outputPorts": [
    {
      "name": "churn_scores",
      "dataContractId": "urn:datacontract:customer:churn-scores"
    }
  ],
  "consumer_principals": [
    { "type": "group", "value": "marketing-analysts" }
  ]
}
```

#### Response

`201 Created` — the created `DataProduct` object.

### List data products

```http
GET /api/data-products
```

Returns products visible to the caller. Products the caller does not own and that are not published are hidden; `data-products` administrators see everything.

By default the response is **collapsed by version family** — one row per `versionFamilyId` with a `versionCount` field. Set `include_history=true` to get every visible version.

**Authorization:** `data-products` — `Read-only`

#### Query parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `project_id` | `string` | — | Filter by project. |
| `domain_id` | `string` | — | Filter by a single domain ID. |
| `domain_ids` | `string` | — | Filter by multiple domain IDs, comma-separated. |
| `include_history` | `boolean` | `false` | `true` returns every visible version rather than one row per family. |

```bash
curl -s "$ONTOS_URL/api/data-products?domain_id=8f2b1c34-…&include_history=false" \
  -H "X-Forwarded-Email: alice@example.com"
```

#### Response

`200 OK` — an array of product objects.

### Get a data product

```http
GET /api/data-products/{product_id}
```

**Authorization:** `data-products` — `Read-only`

:::note
A direct read is scoped by the same ownership rules as the listing: a consumer cannot read an unpublished draft they do not own. Such a request returns `404`, not `403`, so the draft's existence is not disclosed.
:::

#### Response

`200 OK` — the product document.

#### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | The product does not exist, or the caller may not read it. |

### Update a data product

```http
PUT /api/data-products/{product_id}
```

Replaces the product document. Callers may only update products belonging to projects they are members of, when the product has a `project_id`.

**Authorization:** `data-products` — `Read/Write`

#### Request body

A full `DataProduct` document. The body's `id` **must match** the path `product_id`.

#### Response

`200 OK` — the updated `DataProduct` object.

#### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | Invalid JSON body, or the body's `id` does not match the path. |
| `403 Forbidden` | The caller is not a member of the product's project. |
| `404 Not Found` | No product with that ID. |
| `422 Unprocessable Entity` | The body failed ODPS validation. The `detail` field lists the field-level errors. |

### Delete a data product

```http
DELETE /api/data-products/{product_id}
```

**Authorization:** `data-products` — `Admin`

#### Response

`204 No Content`

#### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No product with that ID. |

### Upload data products

```http
POST /api/data-products/upload
```

Uploads a file containing one or more products and creates them.

**Authorization:** `data-products` — `Read/Write`

#### Request

`multipart/form-data` with a single `file` part.

```bash
curl -s -X POST "$ONTOS_URL/api/data-products/upload" \
  -H "X-Forwarded-Email: alice@example.com" \
  -F "file=@products.yaml"
```

#### Response

`201 Created` — an array of the created `DataProduct` objects.

## Lookups and marketplace

### Distinct statuses, types, and owners

```http
GET /api/data-products/statuses
GET /api/data-products/types
GET /api/data-products/owners
```

Each returns an array of strings — the distinct values present across the products in the workspace. Useful for populating filter controls.

**Authorization:** `data-products` — `Read-only`

```json
["draft", "proposed", "active", "deprecated"]
```

### List published products

```http
GET /api/data-products/published
```

Returns products with a `publication_scope` other than `none` — the marketplace view.

**Authorization:** `data-products` — `Read-only`

#### Query parameters

| Name | Type | Description |
| --- | --- | --- |
| `scope` | `string` | Narrow to a single publication scope: `domain`, `organization`, or `external`. Case-insensitive. |

#### Response

`200 OK` — an array of `DataProduct` objects.

### List the caller's subscriptions

```http
GET /api/data-products/my-subscriptions
```

Returns every product the authenticated caller is subscribed to.

**Authorization:** Authenticated caller — no feature permission required.

#### Query parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `skip` | `integer` | `0` | Records to skip. |
| `limit` | `integer` | `100` | Maximum records to return. |

#### Response

`200 OK` — an array of `DataProduct` objects.

## Lifecycle

### Move to sandbox

```http
POST /api/data-products/{product_id}/move-to-sandbox
```

Moves a `draft` product to `sandbox` for testing.

**Authorization:** `data-products` — `Read/Write`

#### Response

`200 OK`

```json
{ "status": "sandbox" }
```

#### Errors

| Code | Condition |
| --- | --- |
| `409 Conflict` | The product is not in a state that allows this transition. |

### Submit for review

```http
POST /api/data-products/{product_id}/submit-review
POST /api/data-products/{product_id}/submit-certification
```

Moves a `draft` or `sandbox` product to `proposed`. Both paths invoke the same handler — `submit-certification` is retained as an alias.

**Authorization:** `data-products` — `Read/Write`

#### Response

`200 OK`

#### Errors

| Code | Condition |
| --- | --- |
| `409 Conflict` | The product is not `draft` or `sandbox`. |

### Request a steward review

```http
POST /api/data-products/{product_id}/request-review
```

Transitions `draft`/`sandbox` → `proposed` → `under_review` and notifies the nominated reviewer.

**Authorization:** `data-products` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `reviewer_email` | `string` | Yes | Email of the steward to notify. |
| `message` | `string` | No | Note for the reviewer. |

```json
{ "reviewer_email": "steward@example.com", "message": "Ready for governance review." }
```

#### Response

`200 OK`

#### Errors

| Code | Condition |
| --- | --- |
| `409 Conflict` | The product cannot transition from its current status. |

### Approve a product

```http
POST /api/data-products/{product_id}/approve
```

Moves an `under_review` product to `approved`.

**Authorization:** `PRODUCTS` approval privilege

#### Response

`200 OK`

### Reject a product

```http
POST /api/data-products/{product_id}/reject
```

Returns an `under_review` product to `draft`.

**Authorization:** `PRODUCTS` approval privilege

#### Response

`200 OK`

### Publish a product

```http
POST /api/data-products/{product_id}/publish
```

Moves an `approved` product to `active` and makes it available in the marketplace. **Every output port must have `dataContractId` set** before publication is allowed.

**Authorization:** `data-products` — `Read/Write`

#### Response

`200 OK`

#### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | An output port is missing its `dataContractId`, or a linked contract is not in an approved status. |
| `409 Conflict` | The status transition to `active` is not allowed from the product's current status. |

### Deprecate a product

```http
POST /api/data-products/{product_id}/deprecate
```

Signals that an `active` or certified product will be retired soon.

**Authorization:** `data-products` — `Read/Write`

#### Response

`200 OK`

```json
{ "status": "deprecated" }
```

#### Errors

| Code | Condition |
| --- | --- |
| `409 Conflict` | The product is not `active` or certified. |

### Change status directly

```http
POST /api/data-products/{product_id}/change-status
```

For administrators and owners — changes status without going through the approval workflow.

**Authorization:** `data-products` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `new_status` | `string` | Yes | Target status. |

```json
{ "new_status": "active" }
```

#### Response

`200 OK`

#### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | The product does not exist, or the transition is not valid. |

### Request a status change

```http
POST /api/data-products/{product_id}/request-status-change
```

Creates a request that administrators can approve or deny. Requires only `Read-only` access — requesting is not itself a mutation.

**Authorization:** `data-products` — `Read-only`

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
POST /api/data-products/{product_id}/handle-status-change
```

Only administrators and owners may decide status change requests.

**Authorization:** `data-products` — `Read/Write`

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
POST /api/data-products/{product_id}/request-certify
```

Starts the certification workflow. Approvers then call [handle-certify](#handle-a-certification-request).

**Authorization:** `data-products` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `certification_level` | `integer` | Yes | Target certification level. |
| `message` | `string` | No | Note for the approvers. |

#### Response

`200 OK`

### Handle a certification request

```http
POST /api/data-products/{product_id}/handle-certify
```

**Authorization:** `PRODUCTS` approval privilege

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `approved` | `boolean` | Yes | Whether the request is granted. |
| `certification_level` | `integer` | No | Level to grant, when it differs from the request. |
| `notes` | `string` | No | Approver notes. |

#### Response

`200 OK`

#### Errors

| Code | Condition |
| --- | --- |
| `422 Unprocessable Entity` | `approved` is missing. |

### Certify directly

```http
POST /api/data-products/{product_id}/certify
```

Certifies a product at a specific level. The product must be `active`.

**Authorization:** `PRODUCTS` approval privilege

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `certification_level` | `integer` | Yes | Certification level to apply. |
| `notes` | `string` | No | Certification notes. |

```json
{ "certification_level": 2, "notes": "Quality checks green for two quarters." }
```

#### Response

`200 OK`

#### Errors

| Code | Condition |
| --- | --- |
| `409 Conflict` | The product is not `active`. |
| `422 Unprocessable Entity` | `certification_level` is missing. |

### Decertify

```http
POST /api/data-products/{product_id}/decertify
```

**Authorization:** `PRODUCTS` approval privilege

#### Response

`200 OK`

## Publication

### Set publication scope

```http
POST /api/data-products/{product_id}/set-publication-scope
```

The product must be `active` to be published to any scope other than `none`.

**Authorization:** `data-products` — `Read/Write`

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
| `409 Conflict` | The product is not `active`. |
| `422 Unprocessable Entity` | `scope` is not one of the four allowed values. |

### Unpublish

```http
POST /api/data-products/{product_id}/unpublish
```

Removes the product from the marketplace by setting `publication_scope` to `none`.

**Authorization:** `data-products` — `Read/Write`

#### Response

`200 OK`

### Request publication

```http
POST /api/data-products/{product_id}/request-publish
```

Requests that the product be published, for an approver to decide.

**Authorization:** `data-products` — `Read/Write`

#### Request body

| Field | Type | Description |
| --- | --- | --- |
| `scope` | `string` | Requested publication scope. |
| `justification` | `string` | Why the product should be published. |

#### Response

`200 OK`

### Handle a publication request

```http
POST /api/data-products/{product_id}/handle-publish
```

**Authorization:** `PRODUCTS` approval privilege

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `approved` | `boolean` | Yes | Whether the request is granted. |
| `scope` | `string` | No | Scope to publish to when approving. |
| `notes` | `string` | No | Approver notes. |

#### Response

`200 OK`

#### Errors

| Code | Condition |
| --- | --- |
| `422 Unprocessable Entity` | `approved` is missing. |

## Versioning and drafts

Products use the same version-family model as contracts: every version shares a `versionFamilyId`, and personal drafts are visible only to their owner until committed.

### List versions

```http
GET /api/data-products/{product_id}/versions
```

Returns every visible version of the product's family, newest first. Personal drafts owned by other users are hidden.

**Authorization:** `data-products` — `Read-only`

#### Response

`200 OK` — an array of version objects.

### Resolve a family's latest version

```http
GET /api/data-products/families/{family_id}/latest
```

Resolves a "follow latest" family reference to a concrete product. Visibility is role-aware: subscribers and owners of any version in the family see in-flight rows (`draft`, `proposed`, and so on), while plain consumers see only `active` and `deprecated` versions.

**Authorization:** `data-products` — `Read-only`

#### Response

`200 OK` — the latest visible product in the family.

### Create a new version

```http
POST /api/data-products/{product_id}/versions
```

**Authorization:** `data-products` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `new_version` | `string` | Yes | New version string, for example `1.1.0` or `2.0.0`. |

```json
{ "new_version": "1.1.0" }
```

#### Response

`201 Created` — the new `DataProduct` version.

### Compare two products

```http
POST /api/data-products/compare
```

Analyzes the differences between two product payloads and recommends a semantic version bump.

**Authorization:** `data-products` — `Read-only`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `old_product` | `object` | Yes | The baseline product document. |
| `new_product` | `object` | Yes | The candidate product document. |

#### Response

`200 OK` — a diff analysis with a suggested bump.

### Clone for editing (create a personal draft)

```http
POST /api/data-products/{product_id}/clone-for-editing
```

Creates a copy of the product as a personal draft visible only to the caller. Use this when editing a product that is `active` or beyond.

**Authorization:** `data-products` — `Read/Write`

#### Response

`200 OK` — the new draft `DataProduct`.

### Diff a draft against its parent

```http
GET /api/data-products/{product_id}/diff-from-parent
```

**Authorization:** `data-products` — `Read-only`

#### Response

`200 OK` — a `DiffFromParentResponse` object.

| Field | Type | Description |
| --- | --- | --- |
| `parent_version` | `string` | The parent's version. |
| `suggested_bump` | `"major" \| "minor" \| "patch"` | Recommended bump. |
| `suggested_version` | `string` | Recommended version string. |
| `analysis` | `object` | Detailed diff analysis. |

### Commit a personal draft

```http
POST /api/data-products/{product_id}/commit
```

Promotes the draft from tier 1 (owner only) to tier 2 (team and project). The product is **not** published to the marketplace — that is a separate action.

**Authorization:** `data-products` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `new_version` | `string` | Yes | Version for the committed product. |
| `change_summary` | `string` | Yes | Summary of the changes made. |

```json
{ "new_version": "1.2.0", "change_summary": "Added churn probability output port" }
```

#### Response

`200 OK` — a `CommitDraftResponse` object with the product's `id`, `name`, `version`, `status`, and `draftOwnerId` (`null` after the commit).

### Discard a personal draft

```http
DELETE /api/data-products/{product_id}/discard
```

Only the draft's owner may discard it.

**Authorization:** `data-products` — `Read/Write`

#### Response

`200 OK`

## Contracts, datasets, and assets

### Create a product from a contract

```http
POST /api/data-products/from-contract
```

Creates a product whose output port is governed by an existing data contract. `domain_id`, `owner_team_id`, and `project_id` are inherited from the contract.

**Authorization:** `data-products` — `Read/Write`

#### Request body

All fields are embedded body parameters.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `contract_id` | `string` | Yes | Contract that governs the output port. |
| `product_name` | `string` | Yes | Name for the new product. |
| `product_type` | `string` | Yes | Product type. |
| `version` | `string` | Yes | Version for the new product. |
| `output_port_name` | `string` | No | Name for the generated output port. |

```json
{
  "contract_id": "urn:datacontract:customer:churn-scores",
  "product_name": "Customer Churn Signals",
  "product_type": "source-aligned",
  "version": "1.0.0",
  "output_port_name": "churn_scores"
}
```

#### Response

`201 Created` — the created `DataProduct`.

#### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | Invalid `product_type`, or the contract data cannot produce a product. |
| `500 Internal Server Error` | Creation failed. |

:::warning
This operation currently fails at runtime: the handler imports `DataProductType` from `src.models.data_products`, but that enum does not exist in the module, so the `product_type` conversion raises an `ImportError` and the request returns `500`. Track this before relying on the endpoint — the other creation paths (`POST /api/data-products`, `POST /api/data-products/upload`) are unaffected.
:::

### List products using a contract

```http
GET /api/data-products/by-contract/{contract_id}
```

Returns every product with an output port linked to the given contract.

**Authorization:** `data-products` — `Read-only`

#### Response

`200 OK` — an array of `DataProduct` objects.

### List a product's contracts

```http
GET /api/data-products/{product_id}/contracts
```

Returns the contract IDs referenced by the product's output ports. The array is empty when no contracts are linked.

**Authorization:** `data-products` — `Read-only`

#### Response

`200 OK` — an array of strings.

```json
["urn:datacontract:customer:churn-scores"]
```

### List linked datasets

```http
GET /api/data-products/{product_id}/datasets
```

Returns the Dataset assets linked to the product through `hasDataset` relationships.

**Authorization:** `data-products` — `Read-only`

#### Response

`200 OK` — an array of dataset objects.

### Link a dataset

```http
POST /api/data-products/{product_id}/datasets
```

Creates a `hasDataset` relationship from the product to a Dataset asset.

**Authorization:** `data-products` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `dataset_id` | `string` | Yes | UUID of the Dataset asset. |

```json
{ "dataset_id": "e5f6a7b8-1234-5678-9abc-def012345678" }
```

#### Response

`200 OK`

#### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | The dataset cannot be linked. |
| `422 Unprocessable Entity` | `dataset_id` is missing or empty. |

### Unlink a dataset

```http
DELETE /api/data-products/{product_id}/datasets/{dataset_id}
```

Removes the `hasDataset` relationship.

**Authorization:** `data-products` — `Read/Write`

#### Response

`200 OK`

### List linked assets

```http
GET /api/data-products/{product_id}/assets
```

Returns the assets linked to the product through entity relationships.

**Authorization:** `data-products` — `Read-only`

:::note
This operation is gated by `data-products` only — deliberately **not** by the `assets` feature — so data consumers can see a product's linked assets even when the `assets` feature is not granted to them. Their access to the product is the implicit authorization.
:::

#### Query parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `skip` | `integer` | `0` | Records to skip. |
| `limit` | `integer` | `200` | Maximum records to return. |

#### Response

`200 OK` — an array of asset objects.

### Get the product hierarchy

```http
GET /api/data-products/{product_id}/hierarchy
```

Returns the full data product → dataset → table/view → column hierarchy in one call.

**Authorization:** `data-products` — `Read-only`

#### Response

`200 OK` — a nested hierarchy object.

### Export as ODPS

```http
GET /api/data-products/{product_id}/odps/export
```

Exports the product as ODPS v1.0.0 YAML, including datasets discovered through entity relationships.

**Authorization:** `data-products` — `Read-only`

```bash
curl -s "$ONTOS_URL/api/data-products/dp-customer-churn/odps/export" \
  -H "X-Forwarded-Email: alice@example.com" \
  -o dp-customer-churn.odps.yaml
```

#### Response

`200 OK` — the ODPS document as YAML.

### Import team members

```http
GET /api/data-products/{product_id}/import-team-members
```

Returns an Ontos team's members formatted for the product's ODPS `team` array.

**Authorization:** `data-products` — `Read/Write`

#### Query parameters

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `team_id` | `string` | Yes | Ontos team to import from. |

#### Response

`200 OK` — an array of ODPS team member objects.

## Subscriptions

Subscribers receive notifications about status changes, compliance violations, and new versions. Products must be `active` or certified to be subscribed to.

### Subscribe

```http
POST /api/data-products/{product_id}/subscribe
```

Subscribes the authenticated caller. Optionally subscribes on behalf of a group or service principal, which is validated against the workspace SCIM directory.

**Authorization:** Authenticated caller — no feature permission required.

#### Request body

Optional.

| Field | Type | Description |
| --- | --- | --- |
| `reason` | `string` | Why the caller is subscribing. |
| `on_behalf_of` | `object` | `{ "type": "user" \| "group" \| "service_principal", "value": "…" }`. |

```json
{
  "reason": "Feeding the marketing propensity model",
  "on_behalf_of": { "type": "group", "value": "marketing-analysts" }
}
```

#### Response

`200 OK` — a `SubscriptionResponse` object.

```json
{
  "subscribed": true,
  "subscription": {
    "id": "sub-1234",
    "product_id": "dp-customer-churn",
    "subscriber_email": "alice@example.com",
    "subscribed_at": "2026-08-05T13:00:00Z",
    "subscription_reason": "Feeding the marketing propensity model",
    "on_behalf_of_type": "group",
    "on_behalf_of_value": "marketing-analysts"
  }
}
```

#### Errors

| Code | Condition |
| --- | --- |
| `401 Unauthorized` | No authenticated caller. |

### Unsubscribe

```http
DELETE /api/data-products/{product_id}/subscribe
```

**Authorization:** Authenticated caller — no feature permission required.

#### Response

`200 OK` — a `SubscriptionResponse` object with `subscribed: false`.

### Get subscription status

```http
GET /api/data-products/{product_id}/subscription
```

**Authorization:** Authenticated caller — no feature permission required.

#### Response

`200 OK` — a `SubscriptionResponse` object.

### List subscribers

```http
GET /api/data-products/{product_id}/subscribers
```

Returns the full subscriber list. Restricted to product owners and administrators.

**Authorization:** `data-products` — `Read/Write`

#### Query parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `skip` | `integer` | `0` | Records to skip. |
| `limit` | `integer` | `100` | Maximum records to return. |

#### Response

`200 OK` — a `SubscribersListResponse` object.

```json
{
  "product_id": "dp-customer-churn",
  "subscriber_count": 12,
  "subscribers": [
    {
      "email": "alice@example.com",
      "subscribed_at": "2026-08-05T13:00:00Z",
      "reason": "Feeding the marketing propensity model"
    }
  ]
}
```

### Get the subscriber count

```http
GET /api/data-products/{product_id}/subscriber-count
```

Returns just the count — no feature permission required, so it can be shown to any authenticated caller on the marketplace listing.

**Authorization:** Authenticated caller.

#### Response

`200 OK`

## Genie

### Create a Genie Space from products

```http
POST /api/data-products/genie-space
```

Starts creation of a Databricks Genie Space seeded with the selected products' datasets. The work runs in the background and the caller is notified on completion.

**Authorization:** `data-products` — `Read/Write`

#### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `product_ids` | `string[]` | Yes | Products to include. Must be non-empty. |

```json
{ "product_ids": ["dp-customer-churn", "dp-customer-profile"] }
```

#### Response

`202 Accepted`

```json
{ "message": "Genie Space creation process initiated. You will be notified upon completion." }
```

#### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | `product_ids` is empty. |
| `500 Internal Server Error` | Genie Space creation could not be started. |

## See also

- [Create Data Products](../../user_guide/basic_elements) — the user-facing guide.
- [Data Contracts API](./data_contracts) — the contracts that govern output ports.
- [Tags API](./tags) — namespaced tags applied to products.
- [Costs API](./costs) — attach cost items using entity type `data_product`.

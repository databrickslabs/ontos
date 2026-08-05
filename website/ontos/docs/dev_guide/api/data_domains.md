---
sidebar_position: 1
id: data_domains
title: data domain
description: Create, read, update, and delete data domains, and inspect the impact of deleting one.
---

# Data Domains 

Data Domains organize data products, contracts, teams, and assets into business areas. Domains are hierarchical — a domain may have a parent and any number of children — and entities can be assigned to multiple domains, one of which is the *primary* (canonical) domain.

**Swagger tag:** `Data Domains` &nbsp;·&nbsp; **Feature ID:** `data-domains` &nbsp;·&nbsp; **Route prefix:** `/api/data-domains`

## Operations

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/data-domains` | Create a data domain | `Read/Write` |
| `GET` | `/api/data-domains` | List data domains | `Read-only` |
| `GET` | `/api/data-domains/{domain_id}` | Get a domain by ID | `Read-only` |
| `GET` | `/api/data-domains/{domain_id}/deletion-impact` | Check whether a domain can be deleted | `Read-only` |
| `PUT` | `/api/data-domains/{domain_id}` | Update a domain | `Read/Write` |
| `DELETE` | `/api/data-domains/{domain_id}` | Delete a domain | `Admin` |

## Create a data domain

```http
POST /api/data-domains
```

Creates a new data domain. Fires the `on_create` workflow trigger for entity type `DOMAIN`.

**Authorization:** `data-domains` — `Read/Write`

### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `string` | Yes | Name of the data domain. Minimum length 1. Must be unique. |
| `description` | `string` | No | Free-text description. |
| `parent_id` | `uuid` | No | ID of the parent domain, for hierarchical domains. |
| `tags` | `AssignedTagCreate[]` | No | Rich tags to assign. Each entry takes `tag_fqn` **or** `tag_id`, plus an optional `assigned_value`. See [Tags](./tags#assigned-tag-payloads). |

```json
{
  "name": "customer-360",
  "description": "Customer master data and derived customer analytics",
  "parent_id": null,
  "tags": [
    { "tag_fqn": "default/pii", "assigned_value": "high" }
  ]
}
```

### Response

`201 Created` — a `DataDomainRead` object.

```json
{
  "id": "8f2b1c34-0d1a-4e77-9a0b-5c6d7e8f9a01",
  "name": "customer-360",
  "description": "Customer master data and derived customer analytics",
  "parent_id": null,
  "parent_name": null,
  "parent_info": null,
  "children_count": 2,
  "children_info": [
    { "id": "b1c2…", "name": "customer-profile" },
    { "id": "c3d4…", "name": "customer-events" }
  ],
  "tags": [
    {
      "tag_id": "11111111-2222-3333-4444-555555555555",
      "tag_name": "pii",
      "namespace_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
      "namespace_name": "default",
      "status": "active",
      "fully_qualified_name": "default/pii",
      "assigned_value": "high",
      "assigned_by": "alice@example.com",
      "assigned_at": "2026-08-05T10:12:33Z"
    }
  ],
  "created_at": "2026-08-05T10:12:33Z",
  "updated_at": "2026-08-05T10:12:33Z",
  "created_by": "alice@example.com"
}
```

### Errors

| Code | Condition |
| --- | --- |
| `409 Conflict` | A domain with the same name already exists. |
| `500 Internal Server Error` | Creation failed. |

## List data domains

```http
GET /api/data-domains
```

Returns all data domains the caller can read.

**Authorization:** `data-domains` — `Read-only`

### Query parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `skip` | `integer` | `0` | Number of records to skip. |
| `limit` | `integer` | `100` | Maximum number of records to return. |

```bash
curl -s "$ONTOS_URL/api/data-domains?skip=0&limit=50" \
  -H "X-Forwarded-Email: alice@example.com"
```

### Response

`200 OK` — an array of `DataDomainRead` objects.

## Get a data domain

```http
GET /api/data-domains/{domain_id}
```

**Authorization:** `data-domains` — `Read-only`

### Path parameters

| Name | Type | Description |
| --- | --- | --- |
| `domain_id` | `uuid` | ID of the data domain. |

### Response

`200 OK` — a `DataDomainRead` object, including `parent_info` and `children_info`.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No domain with that ID. |

## Check deletion impact

```http
GET /api/data-domains/{domain_id}/deletion-impact
```

Reports whether a domain can be deleted and which entities would block the deletion. `deletable` is `false` when the domain — or any descendant that would cascade-delete with it — is the **primary** domain for at least one entity.

Call this before `DELETE` to warn users instead of surfacing a `409`.

**Authorization:** `data-domains` — `Read-only`

### Response

`200 OK`

| Field | Type | Description |
| --- | --- | --- |
| `domain_id` | `string` | The domain that was checked. |
| `domain_name` | `string` | Name of the domain. |
| `deletable` | `boolean` | `false` when at least one entity uses this domain (or a descendant) as its primary domain. |
| `primary_assignments` | `object[]` | Blocking entities, each as `{ "entity_type", "entity_id" }`. |
| `assignment_counts` | `object` | Per entity type, `{ "primary": n, "additional": n }` counts across the domain and its descendants. |

```json
{
  "domain_id": "8f2b1c34-0d1a-4e77-9a0b-5c6d7e8f9a01",
  "domain_name": "customer-360",
  "deletable": false,
  "primary_assignments": [
    { "entity_type": "data_product", "entity_id": "dp-customer-churn" },
    { "entity_type": "team", "entity_id": "3a4b…" }
  ],
  "assignment_counts": {
    "data_product": { "primary": 1, "additional": 4 },
    "team": { "primary": 1, "additional": 0 }
  }
}
```

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No domain with that ID. |

## Update a data domain

```http
PUT /api/data-domains/{domain_id}
```

Partial update — omitted fields are left unchanged. Fires the `on_update` workflow trigger for entity type `DOMAIN`.

**Authorization:** `data-domains` — `Read/Write`

### Request body

| Field | Type | Description |
| --- | --- | --- |
| `name` | `string` | New name. Minimum length 1. |
| `description` | `string` | New description. |
| `parent_id` | `uuid` | New parent domain ID. Set to `null` to detach from the parent. |
| `tags` | `AssignedTagCreate[]` | Replaces the current tag set. |

```json
{
  "description": "Customer master data, profiles, and consent records",
  "parent_id": "0a1b2c3d-4e5f-6789-abcd-ef0123456789"
}
```

### Response

`200 OK` — the updated `DataDomainRead` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No domain with that ID. |
| `409 Conflict` | The new name collides with an existing domain. |

## Delete a data domain

```http
DELETE /api/data-domains/{domain_id}
```

Deletes a data domain. Child domains cascade-delete with the parent. Fires the `on_delete` workflow trigger for entity type `DOMAIN`.

:::warning
This operation requires the `Admin` access level and cascades to child domains. Call [`GET /api/data-domains/{domain_id}/deletion-impact`](#check-deletion-impact) first to see what would be affected.
:::

**Authorization:** `data-domains` — `Admin`

### Response

`200 OK` — the deleted `DataDomainRead` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No domain with that ID. |
| `409 Conflict` | The domain (or a descendant) is the primary domain for an entity. The `detail` field carries the same structured body as [deletion-impact](#check-deletion-impact). |

```json
{
  "detail": {
    "domain_id": "8f2b1c34-0d1a-4e77-9a0b-5c6d7e8f9a01",
    "domain_name": "customer-360",
    "deletable": false,
    "primary_assignments": [
      { "entity_type": "data_product", "entity_id": "dp-customer-churn" }
    ],
    "assignment_counts": {
      "data_product": { "primary": 1, "additional": 4 }
    }
  }
}
```

## Related operations

Domains appear in other route groups as filters or sub-collections:

- [`GET /api/domains/{domain_id}/teams`](./teams#list-teams-in-a-domain) — teams assigned to a domain.
- [`GET /api/data-contracts?domain_id=…`](./data_contracts#list-data-contracts) — contracts filtered by domain.
- [`GET /api/data-products?domain_id=…`](./data_products#list-data-products) — products filtered by domain.
- [Costs](./costs) — cost items can be attached to a domain using entity type `data_domain`.

## See also

- [Organize with Domains](../../user_guide/domains) — the user-facing guide.
- [Core Concepts](../../introduction/concepts) — how domains relate to other Ontos entities.

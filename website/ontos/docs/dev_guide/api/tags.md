---
sidebar_position: 6
id: tags
title: tag
description: Manage tag namespaces, tags, namespace permissions, and tag assignments on any entity.
---

# Tag
Tags in Ontos are namespaced, governed objects rather than free-text labels. A **namespace** groups related tags and carries group-level permissions; a **tag** lives in exactly one namespace, may declare a set of allowed values, and can be arranged into a hierarchy through `parent_id`. Tags are then **assigned** to entities — data products, contracts, domains, catalog objects, and so on.

A tag's fully qualified name (FQN) is `{namespace}/{tag_name}`, for example `default/pii`.

**Swagger tag:** `Tags` &nbsp;·&nbsp; **Feature ID:** `tags` &nbsp;·&nbsp; **Route prefixes:** `/api/tags`, `/api/entities/{entity_type}/{entity_id}/tags`

## Operations

### Namespaces

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/tags/namespaces` | Create a namespace | `Admin` |
| `GET` | `/api/tags/namespaces` | List namespaces | `Read-only` |
| `GET` | `/api/tags/namespaces/{namespace_id}` | Get a namespace | `Read-only` |
| `PUT` | `/api/tags/namespaces/{namespace_id}` | Update a namespace | `Admin` |
| `DELETE` | `/api/tags/namespaces/{namespace_id}` | Delete a namespace | `Admin` |

### Tags

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/tags` | Create a tag | `Read/Write` |
| `GET` | `/api/tags` | List and filter tags | `Read-only` |
| `GET` | `/api/tags/{tag_id}` | Get a tag by ID | `Read-only` |
| `GET` | `/api/tags/fqn/{fully_qualified_name}` | Get a tag by FQN | `Read-only` |
| `GET` | `/api/tags/{tag_id}/entities` | List entities carrying a tag | `Read-only` |
| `PUT` | `/api/tags/{tag_id}` | Update a tag | `Read/Write` |
| `DELETE` | `/api/tags/{tag_id}` | Delete a tag | `Admin` |

### Namespace permissions

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/tags/namespaces/{namespace_id}/permissions` | Grant a group access to a namespace | `Admin` |
| `GET` | `/api/tags/namespaces/{namespace_id}/permissions` | List namespace permissions | `Read-only` |
| `GET` | `/api/tags/namespaces/{namespace_id}/permissions/{permission_id}` | Get one permission | `Read-only` |
| `PUT` | `/api/tags/namespaces/{namespace_id}/permissions/{permission_id}` | Update a permission | `Admin` |
| `DELETE` | `/api/tags/namespaces/{namespace_id}/permissions/{permission_id}` | Revoke a permission | `Admin` |

### Entity tag assignments

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `GET` | `/api/entities/{entity_type}/{entity_id}/tags` | List an entity's tags | `Read-only` |
| `POST` | `/api/entities/{entity_type}/{entity_id}/tags:set` | Replace an entity's tags | `Read/Write` |
| `POST` | `/api/entities/{entity_type}/{entity_id}/tags:add` | Add one tag to an entity | `Read/Write` |
| `DELETE` | `/api/entities/{entity_type}/{entity_id}/tags:remove` | Remove one tag from an entity | `Read/Write` |

## Enumerations

### `TagStatus`

`active` · `draft` · `candidate` · `deprecated` · `inactive` · `retired`

### `TagAccessLevel`

`read_only` · `read_write` · `admin`

## Create a tag namespace

```http
POST /api/tags/namespaces
```

**Authorization:** `tags` — `Admin`

### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `string` | Yes | Namespace name. Must match `^[a-zA-Z0-9_-]+$`, 1–255 characters. |
| `description` | `string` | No | Free-text description. |

```json
{
  "name": "governance",
  "description": "Tags applied by the data governance office"
}
```

### Response

`201 Created` — a `TagNamespace` object.

```json
{
  "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  "name": "governance",
  "description": "Tags applied by the data governance office",
  "created_by": "alice@example.com",
  "created_at": "2026-08-05T12:00:00Z",
  "updated_at": "2026-08-05T12:00:00Z"
}
```

## List tag namespaces

```http
GET /api/tags/namespaces
```

**Authorization:** `tags` — `Read-only`

### Query parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `skip` | `integer` | `0` | Records to skip. |
| `limit` | `integer` | `100` | Maximum records to return. Maximum allowed value is `1000`. |

### Response

`200 OK` — an array of `TagNamespace` objects.

## Get a tag namespace

```http
GET /api/tags/namespaces/{namespace_id}
```

**Authorization:** `tags` — `Read-only`

### Response

`200 OK` — a `TagNamespace` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No namespace with that ID. |

## Update a tag namespace

```http
PUT /api/tags/namespaces/{namespace_id}
```

**Authorization:** `tags` — `Admin`

### Request body

| Field | Type | Description |
| --- | --- | --- |
| `name` | `string` | New name. Must match `^[a-zA-Z0-9_-]+$`. |
| `description` | `string` | New description. |

### Response

`200 OK` — the updated `TagNamespace` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No namespace with that ID. |

## Delete a tag namespace

```http
DELETE /api/tags/namespaces/{namespace_id}
```

**Authorization:** `tags` — `Admin`

### Response

`204 No Content`

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | Namespace not found, or it could not be deleted (for example, it still contains tags). |

## Create a tag

```http
POST /api/tags
```

**Authorization:** `tags` — `Read/Write`

### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `string` | Yes | Tag name. Must match `^[a-zA-Z0-9_-]+$`, 1–255 characters. |
| `description` | `string` | No | Free-text description. |
| `possible_values` | `string[]` | No | Allowed values for assignments of this tag. Also accepts a JSON-encoded array string. |
| `status` | `TagStatus` | No | Lifecycle status. Defaults to `active`. |
| `version` | `string` | No | Tag version, for example `v1.0`. |
| `parent_id` | `uuid` | No | Parent tag, for hierarchical tags. |
| `namespace_id` | `uuid` | No | Target namespace by ID. Takes precedence over `namespace_name`. |
| `namespace_name` | `string` | No | Target namespace by name. Defaults to `default` when neither field is supplied. |

```json
{
  "name": "confidentiality",
  "description": "Confidentiality classification",
  "possible_values": ["public", "internal", "confidential", "restricted"],
  "status": "active",
  "version": "v1.0",
  "namespace_name": "governance"
}
```

### Response

`201 Created` — a `Tag` object. `fully_qualified_name` is computed from the namespace and tag name.

```json
{
  "id": "11111111-2222-3333-4444-555555555555",
  "name": "confidentiality",
  "description": "Confidentiality classification",
  "possible_values": ["public", "internal", "confidential", "restricted"],
  "status": "active",
  "version": "v1.0",
  "parent_id": null,
  "namespace_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  "namespace_name": "governance",
  "fully_qualified_name": "governance/confidentiality",
  "created_by": "alice@example.com",
  "created_at": "2026-08-05T12:05:00Z",
  "updated_at": "2026-08-05T12:05:00Z"
}
```

## List tags

```http
GET /api/tags
```

**Authorization:** `tags` — `Read-only`

### Query parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `skip` | `integer` | `0` | Records to skip. |
| `limit` | `integer` | `100` | Maximum records to return. Maximum allowed value is `1000`. |
| `namespace_id` | `uuid` | — | Filter by namespace ID. |
| `namespace_name` | `string` | — | Filter by namespace name. |
| `name_contains` | `string` | — | Filter by tag name substring (case-insensitive). |
| `status` | `TagStatus` | — | Filter by lifecycle status. |
| `parent_id` | `uuid` | — | Filter by parent tag ID. |
| `is_root` | `boolean` | — | `true` returns only root tags (no parent); `false` returns only non-root tags. |

```bash
# Active tags in the governance namespace
curl -s "$ONTOS_URL/api/tags?namespace_name=governance&status=active" \
  -H "X-Forwarded-Email: alice@example.com"
```

### Response

`200 OK` — an array of `Tag` objects.

## Get a tag by ID

```http
GET /api/tags/{tag_id}
```

**Authorization:** `tags` — `Read-only`

### Response

`200 OK` — a `Tag` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No tag with that ID. |

## Get a tag by fully qualified name

```http
GET /api/tags/fqn/{fully_qualified_name}
```

Resolves a tag from its `{namespace}/{tag_name}` FQN. Because the FQN contains a slash, this path segment is matched as a path parameter — send it unescaped.

**Authorization:** `tags` — `Read-only`

```bash
curl -s "$ONTOS_URL/api/tags/fqn/governance/confidentiality" \
  -H "X-Forwarded-Email: alice@example.com"
```

### Response

`200 OK` — a `Tag` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No tag with that FQN. |

## List entities carrying a tag

```http
GET /api/tags/{tag_id}/entities
```

Returns every entity the tag is assigned to. Useful for impact analysis before deprecating or deleting a tag.

**Authorization:** `tags` — `Read-only`

### Query parameters

| Name | Type | Description |
| --- | --- | --- |
| `entity_type` | `string` | Narrow results to one entity type, for example `data_product`, `data_contract`, `dataset`. |

### Response

`200 OK` — an array of objects containing `entity_id`, `entity_type`, `assigned_value`, and assignment metadata.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No tag with that ID. |

## Update a tag

```http
PUT /api/tags/{tag_id}
```

Partial update — omitted fields are left unchanged.

**Authorization:** `tags` — `Read/Write`

### Request body

| Field | Type | Description |
| --- | --- | --- |
| `name` | `string` | New tag name. Must match `^[a-zA-Z0-9_-]+$`. |
| `description` | `string` | New description. |
| `possible_values` | `string[] \| string` | New allowed values. Accepts an array or a JSON-encoded array string. |
| `status` | `TagStatus` | New lifecycle status. |
| `version` | `string` | New version. |
| `parent_id` | `uuid` | New parent tag. |

:::note
A tag cannot be moved to a different namespace through this operation.
:::

### Response

`200 OK` — the updated `Tag` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No tag with that ID. |

## Delete a tag

```http
DELETE /api/tags/{tag_id}
```

**Authorization:** `tags` — `Admin`

### Response

`204 No Content`

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | Tag not found, or it could not be deleted. |

## Grant a namespace permission

```http
POST /api/tags/namespaces/{namespace_id}/permissions
```

Grants a Databricks group an access level within a namespace.

**Authorization:** `tags` — `Admin`

### Request body

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `group_id` | `string` | Yes | Databricks group name or ID. |
| `access_level` | `TagAccessLevel` | Yes | `read_only`, `read_write`, or `admin`. |
| `namespace_id` | `uuid` | No | Redundant here — the namespace comes from the path. |

```json
{
  "group_id": "data-governance-office",
  "access_level": "admin"
}
```

### Response

`201 Created` — a `TagNamespacePermission` object.

```json
{
  "id": "cccccccc-dddd-eeee-ffff-000000000000",
  "namespace_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  "group_id": "data-governance-office",
  "access_level": "admin",
  "created_by": "alice@example.com",
  "created_at": "2026-08-05T12:10:00Z",
  "updated_at": "2026-08-05T12:10:00Z"
}
```

## List namespace permissions

```http
GET /api/tags/namespaces/{namespace_id}/permissions
```

**Authorization:** `tags` — `Read-only`

### Query parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `skip` | `integer` | `0` | Records to skip. |
| `limit` | `integer` | `100` | Maximum records to return. Maximum allowed value is `1000`. |

### Response

`200 OK` — an array of `TagNamespacePermission` objects.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No namespace with that ID. |

## Get a namespace permission

```http
GET /api/tags/namespaces/{namespace_id}/permissions/{permission_id}
```

**Authorization:** `tags` — `Read-only`

### Response

`200 OK` — a `TagNamespacePermission` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | The permission does not exist, or does not belong to that namespace. |

## Update a namespace permission

```http
PUT /api/tags/namespaces/{namespace_id}/permissions/{permission_id}
```

**Authorization:** `tags` — `Admin`

### Request body

| Field | Type | Description |
| --- | --- | --- |
| `group_id` | `string` | New group name or ID. |
| `access_level` | `TagAccessLevel` | New access level. |

### Response

`200 OK` — the updated `TagNamespacePermission` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | The permission does not exist, or does not belong to that namespace. |

## Revoke a namespace permission

```http
DELETE /api/tags/namespaces/{namespace_id}/permissions/{permission_id}
```

**Authorization:** `tags` — `Admin`

### Response

`204 No Content`

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | The permission does not exist, or does not belong to that namespace. |

## Assigned tag payloads

Tag assignments use two shapes.

### `AssignedTagCreate` (write)

Identify the tag by **either** `tag_fqn` or `tag_id`; `tag_id` wins when both are present. A bare string is also accepted and interpreted as `tag_fqn`.

| Field | Type | Description |
| --- | --- | --- |
| `tag_fqn` | `string` | Fully qualified name, for example `governance/confidentiality`. |
| `tag_id` | `uuid` | Direct tag ID. Overrides `tag_fqn`. |
| `assigned_value` | `string` | Value for this assignment, when the tag declares `possible_values`. |

```json
[
  { "tag_fqn": "governance/confidentiality", "assigned_value": "restricted" },
  { "tag_id": "11111111-2222-3333-4444-555555555555" }
]
```

### `AssignedTag` (read)

| Field | Type | Description |
| --- | --- | --- |
| `tag_id` | `uuid` | Tag ID. |
| `tag_name` | `string` | Tag name. |
| `namespace_id` | `uuid` | Namespace ID. |
| `namespace_name` | `string` | Namespace name. |
| `status` | `TagStatus` | Tag lifecycle status. |
| `fully_qualified_name` | `string` | `{namespace}/{tag_name}`. |
| `assigned_value` | `string \| null` | Value assigned for this entity. |
| `assigned_by` | `string \| null` | Who assigned it. |
| `assigned_at` | `datetime` | When it was assigned. |

## List an entity's tags

```http
GET /api/entities/{entity_type}/{entity_id}/tags
```

**Authorization:** `tags` — `Read-only`

### Path parameters

| Name | Type | Description |
| --- | --- | --- |
| `entity_type` | `string` | Entity type, for example `data_product`, `data_contract`, `data_domain`, `catalog-object`. |
| `entity_id` | `string` | Entity ID. URL-encode identifiers containing dots or slashes. |

### Response

`200 OK` — an array of `AssignedTag` objects.

## Replace an entity's tags

```http
POST /api/entities/{entity_type}/{entity_id}/tags:set
```

Replaces the entity's entire tag set with the supplied list. Send `[]` to remove all tags.

**Authorization:** `tags` — `Read/Write`

### Request body

An array of [`AssignedTagCreate`](#assignedtagcreate-write) objects.

```bash
curl -s -X POST \
  "$ONTOS_URL/api/entities/data_product/dp-customer-churn/tags:set" \
  -H "Content-Type: application/json" \
  -H "X-Forwarded-Email: alice@example.com" \
  -d '[{"tag_fqn": "governance/confidentiality", "assigned_value": "restricted"}]'
```

### Response

`200 OK` — the resulting array of `AssignedTag` objects.

## Add a tag to an entity

```http
POST /api/entities/{entity_type}/{entity_id}/tags:add
```

Adds a single tag without disturbing the entity's other assignments.

**Authorization:** `tags` — `Read/Write`

### Query parameters

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `tag_id` | `uuid` | Yes | Tag to assign. |
| `assigned_value` | `string` | No | Value for this assignment. |

:::note
`tag_id` and `assigned_value` are query parameters on this operation, not a JSON body.
:::

```bash
curl -s -X POST \
  "$ONTOS_URL/api/entities/data_contract/urn:datacontract:customer/tags:add?tag_id=11111111-2222-3333-4444-555555555555&assigned_value=internal" \
  -H "X-Forwarded-Email: alice@example.com"
```

### Response

`200 OK` — the created `AssignedTag` object.

## Remove a tag from an entity

```http
DELETE /api/entities/{entity_type}/{entity_id}/tags:remove
```

**Authorization:** `tags` — `Read/Write`

### Query parameters

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `tag_id` | `uuid` | Yes | Tag to unassign. |

### Response

`204 No Content`

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | The tag is not assigned to that entity. |

## Related operations

Several entities also expose their own tag surface:

- Domains, teams, projects, and products accept a `tags` array of `AssignedTagCreate` on create and update.
- Data contracts additionally maintain simple ODCS top-level tags — see [contract tags](./data_contracts#odcs-top-level-tags), which are separate from the namespaced tags described here.

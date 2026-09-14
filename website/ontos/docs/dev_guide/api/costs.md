---
sidebar_position: 7
id: costs
title: cost
description: Record and summarize cost items attached to data domains, products, and contracts.
---

# Cost

Cost items attach recurring or one-off cost figures to a governed entity so that the cost of running a domain, product, or contract can be reported alongside it. Each item belongs to a cost center, carries an amount in minor currency units, and is active over a month range.

**Swagger tag:** `Costs` &nbsp;·&nbsp; **Route prefixes:** `/api/entities/{entity_type}/{entity_id}/cost-items`, `/api/cost-items`

:::info
Cost operations are currently gated by the **`data-domains`** feature ID rather than a dedicated `costs` feature. Audit entries, however, are written under the `costs` feature.
:::

## Operations

| Method | Path | Description | Authorization |
| --- | --- | --- | --- |
| `POST` | `/api/entities/{entity_type}/{entity_id}/cost-items` | Create a cost item | `Read/Write` |
| `GET` | `/api/entities/{entity_type}/{entity_id}/cost-items` | List an entity's cost items | `Read-only` |
| `GET` | `/api/entities/{entity_type}/{entity_id}/cost-items/summary` | Summarize costs for a month | `Read-only` |
| `PUT` | `/api/cost-items/{id}` | Update a cost item | `Read/Write` |
| `DELETE` | `/api/cost-items/{id}` | Delete a cost item | `Read/Write` |

:::note
Creating and listing are scoped by entity; updating and deleting address a cost item directly by its own ID.
:::

## Supported entity types

`entity_type` must be one of:

| Value | Entity |
| --- | --- |
| `data_domain` | A data domain |
| `data_product` | A data product |
| `data_contract` | A data contract |

## Cost centers

`cost_center` must be one of:

`INFRASTRUCTURE` · `HR` · `STORAGE` · `MAINTENANCE` · `OTHER`

Use `custom_center_name` alongside `OTHER` to label a center that does not fit the fixed list.

## The `CostItem` object

| Field | Type | Description |
| --- | --- | --- |
| `id` | `uuid` | Cost item ID. |
| `entity_id` | `string` | ID of the entity the cost belongs to. |
| `entity_type` | `string` | `data_domain`, `data_product`, or `data_contract`. |
| `title` | `string \| null` | Short label. Maximum 255 characters. |
| `description` | `string \| null` | Longer description. Maximum 2000 characters. |
| `cost_center` | `string` | One of the cost centers above. |
| `custom_center_name` | `string \| null` | Custom center label. Maximum 255 characters. |
| `amount_cents` | `integer` | Amount in minor currency units (cents). Must be `>= 0`. |
| `currency` | `string` | ISO 4217 currency code, exactly 3 characters. Defaults to `USD`. |
| `start_month` | `date` | First month the cost applies to. |
| `end_month` | `date \| null` | Last month the cost applies to. `null` means open-ended. |
| `created_by` / `updated_by` | `string \| null` | Audit fields. |
| `created_at` / `updated_at` | `datetime` | Audit timestamps. |

:::tip
Amounts are integers in cents to avoid floating-point rounding. `amount_cents: 125000` with `currency: "USD"` is \$1,250.00.
:::

## Create a cost item

```http
POST /api/entities/{entity_type}/{entity_id}/cost-items
```

**Authorization:** `data-domains` — `Read/Write`

### Request body

A `CostItemCreate` object. `cost_center`, `amount_cents`, and `start_month` are required, and `entity_type` and `entity_id` **must match the path** — a mismatch is rejected with `400`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `entity_id` | `string` | Yes | Must equal the path `entity_id`. |
| `entity_type` | `string` | Yes | Must equal the path `entity_type`. |
| `cost_center` | `string` | Yes | One of the cost centers above. |
| `amount_cents` | `integer` | Yes | Amount in cents, `>= 0`. |
| `start_month` | `date` | Yes | ISO date; the day component is ignored in practice. |
| `title` | `string` | No | Short label. |
| `description` | `string` | No | Longer description. |
| `custom_center_name` | `string` | No | Custom center label. |
| `currency` | `string` | No | 3-character currency code. Defaults to `USD`. |
| `end_month` | `date` | No | Last applicable month. Omit for an open-ended cost. |

```json
{
  "entity_id": "8f2b1c34-0d1a-4e77-9a0b-5c6d7e8f9a01",
  "entity_type": "data_domain",
  "title": "Warehouse compute",
  "description": "Serverless SQL warehouse used by customer-360 dashboards",
  "cost_center": "INFRASTRUCTURE",
  "amount_cents": 125000,
  "currency": "USD",
  "start_month": "2026-01-01",
  "end_month": null
}
```

```bash
curl -s -X POST \
  "$ONTOS_URL/api/entities/data_domain/8f2b1c34-…/cost-items" \
  -H "Content-Type: application/json" \
  -H "X-Forwarded-Email: alice@example.com" \
  -d @cost-item.json
```

### Response

`201 Created` — a `CostItem` object.

### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | `entity_type` or `entity_id` in the body does not match the path. |
| `422 Unprocessable Entity` | A field failed validation — unknown cost center, negative amount, or a currency code that is not 3 characters. |
| `500 Internal Server Error` | Creation failed. |

## List cost items

```http
GET /api/entities/{entity_type}/{entity_id}/cost-items
```

Returns the entity's cost items. When `month` is supplied, only items active in that month are returned — that is, items whose `start_month` is at or before the month and whose `end_month` is absent or at or after it.

**Authorization:** `data-domains` — `Read-only`

### Query parameters

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `month` | `string` | No | `YYYY-MM`. Filters to recurring items active in that month. |

```bash
curl -s "$ONTOS_URL/api/entities/data_product/dp-customer-churn/cost-items?month=2026-08" \
  -H "X-Forwarded-Email: alice@example.com"
```

### Response

`200 OK` — an array of `CostItem` objects.

### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | `month` is not in `YYYY-MM` format. |

## Summarize cost items

```http
GET /api/entities/{entity_type}/{entity_id}/cost-items/summary
```

Aggregates the entity's costs for one month, broken down by cost center.

**Authorization:** `data-domains` — `Read-only`

### Query parameters

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `month` | `string` | **Yes** | `YYYY-MM` month to summarize. |

### Response

`200 OK` — a `CostSummary` object.

| Field | Type | Description |
| --- | --- | --- |
| `month` | `string` | The month summarized, as `YYYY-MM`. |
| `currency` | `string` | Currency of the totals. |
| `total_cents` | `integer` | Sum of all active items, in cents. |
| `items_count` | `integer` | Number of items contributing to the total. |
| `by_center` | `object` | Cost center → total in cents. |

```json
{
  "month": "2026-08",
  "currency": "USD",
  "total_cents": 187500,
  "items_count": 3,
  "by_center": {
    "INFRASTRUCTURE": 125000,
    "STORAGE": 42500,
    "OTHER": 20000
  }
}
```

### Errors

| Code | Condition |
| --- | --- |
| `400 Bad Request` | `month` is missing or not in `YYYY-MM` format. |

## Update a cost item

```http
PUT /api/cost-items/{id}
```

Partial update — omitted fields are left unchanged. The item's entity association cannot be changed.

**Authorization:** `data-domains` — `Read/Write`

### Path parameters

| Name | Type | Description |
| --- | --- | --- |
| `id` | `string` | Cost item ID. |

### Request body

A `CostItemUpdate` object. All fields optional.

| Field | Type | Description |
| --- | --- | --- |
| `title` | `string` | New label. |
| `description` | `string` | New description. |
| `cost_center` | `string` | New cost center. |
| `custom_center_name` | `string` | New custom center label. |
| `amount_cents` | `integer` | New amount in cents, `>= 0`. |
| `currency` | `string` | New 3-character currency code. |
| `start_month` | `date` | New first applicable month. |
| `end_month` | `date` | New last applicable month. |

```json
{
  "amount_cents": 98000,
  "end_month": "2026-12-01"
}
```

### Response

`200 OK` — the updated `CostItem` object.

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No cost item with that ID. |
| `422 Unprocessable Entity` | A field failed validation. |
| `500 Internal Server Error` | Update failed. |

## Delete a cost item

```http
DELETE /api/cost-items/{id}
```

**Authorization:** `data-domains` — `Read/Write`

### Response

`204 No Content`

### Errors

| Code | Condition |
| --- | --- |
| `404 Not Found` | No cost item with that ID. |
| `500 Internal Server Error` | Deletion failed. |

## See also

- [Data Domains API](./data_domains) — the `data_domain` entity type and the feature that gates these operations.
- [Data Products API](./data_products) — the `data_product` entity type.
- [Data Contracts API](./data_contracts) — the `data_contract` entity type.

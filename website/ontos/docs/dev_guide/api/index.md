---
sidebar_position: 0
id: index
title: API Reference
description: REST API reference for the Ontos backend, generated from the FastAPI route definitions.
---

# API Reference

Ontos exposes a REST API built with [FastAPI](https://fastapi.tiangolo.com/). Every route documented here is served by the same application that serves the Ontos UI, so the API base URL is the URL of your Ontos deployment.

## Interactive documentation

Because the backend is a FastAPI application, it ships with an always up-to-date OpenAPI (Swagger) description of every operation:

| Path | Description |
| --- | --- |
| `/docs` | Swagger UI — browse and try out operations interactively |
| `/redoc` | ReDoc — a read-only, reference-style rendering |
| `/openapi.json` | The raw OpenAPI 3.1 schema |

```bash
# Browse the interactive Swagger UI
open https://<your-ontos-app-url>/docs

# Fetch the raw schema for code generation
curl -s https://<your-ontos-app-url>/openapi.json -o ontos-openapi.json
```

:::tip
The pages in this section describe the *stable, feature-facing* operations grouped by entity. When you need the exact request and response schemas — including every nested ODCS and ODPS field — use `/openapi.json` as the source of truth.
:::

## Entity reference pages

| Page | Swagger tag | Route prefix |
| --- | --- | --- |
| [Data Domains](./api/data_domains) | `Data Domains` | `/api/data-domains` |
| [Teams](./api/teams) | `Teams` | `/api/teams` |
| [Projects](./api/projects) | `Projects` | `/api/projects` |
| [Data Contracts](./api/data_contracts) | `Data Contracts` | `/api/data-contracts` |
| [Data Products](./api/data_products) | `Data Products` | `/api/data-products` |
| [Tags](./api/tags) | `Tags` | `/api/tags`, `/api/entities/{entity_type}/{entity_id}/tags` |
| [Costs](./api/costs) | `Costs` | `/api/entities/{entity_type}/{entity_id}/cost-items`, `/api/cost-items` |

:::info
Additional route groups exist in the backend (assets, compliance, semantic models, settings, workflows, and more). They are not covered by these pages yet — browse them in Swagger UI under their respective tags.
:::

## Conventions

### Base path

All operations live under the `/api` prefix. Paths in this reference are written in full, for example `GET /api/data-domains`.

### Content type

Request and response bodies are JSON (`application/json`), except where noted:

- File uploads (`POST /api/data-contracts/upload`, `POST /api/data-products/upload`) use `multipart/form-data`.
- ODCS and ODPS exports return YAML.

### Authentication

Ontos runs as a Databricks App and relies on the identity headers injected by the Databricks Apps proxy:

| Header | Purpose |
| --- | --- |
| `X-Forwarded-Email` | Caller's email — the primary identity used for authorization and audit |
| `X-Forwarded-User` | Fallback identity when `X-Forwarded-Email` is absent |
| `x-forwarded-access-token` | On-behalf-of token used for Databricks SDK calls made for the caller |

When calling the API from outside the browser session, forward these headers. In local development the backend can also resolve the current user from the Databricks CLI profile — see [Environment Variables](./env_var).

### Authorization

Every operation is guarded by one of two dependencies:

- **`PermissionChecker(feature_id, level)`** — checks the caller's effective access level for a feature (`data-domains`, `teams`, `projects`, `data-contracts`, `data-products`, `tags`) against the app roles configured in Settings. Levels, from lowest to highest: `None`, `Read-only`, `Filtered`, `Read/Write`, `Full`, `Admin`. A level of `Read/Write` therefore also satisfies a `Read-only` requirement.
- **`ApprovalChecker(entity)`** — checks a dedicated *approval privilege* (`DOMAINS`, `CONTRACTS`, `PRODUCTS`, `BUSINESS_TERMS`, `ASSET_REVIEWS`) rather than an access level. Used by approve, reject, certify, and decertify operations.

Each operation below lists the level it requires under **Authorization**.

### Common status codes

| Code | Meaning |
| --- | --- |
| `200 OK` | Success with a response body |
| `201 Created` | Resource created |
| `202 Accepted` | Work accepted and running in the background |
| `204 No Content` | Success with no response body (typically `DELETE`) |
| `400 Bad Request` | Malformed input that Pydantic could not reject on its own (e.g. bad month format) |
| `403 Forbidden` | Caller lacks the required access level or approval privilege |
| `404 Not Found` | Resource does not exist |
| `409 Conflict` | Name collision, or an operation blocked by the entity's current state |
| `422 Unprocessable Entity` | Request body or query parameters failed validation |
| `500 Internal Server Error` | Unhandled server-side failure |

Error responses use FastAPI's standard shape:

```json
{
  "detail": "Data domain with id '3f0c…' not found"
}
```

Some conflicts return a structured `detail` object instead of a string — `DELETE /api/data-domains/{domain_id}` is one example.

### Pagination

List operations that support pagination accept `skip` and `limit` query parameters. Defaults vary per operation and are documented individually.

### Auditing

Mutating operations write an entry to the audit trail with the caller's username, client IP, feature ID, action, and success flag. Nothing extra is required from the client.

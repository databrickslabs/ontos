# Test data fixtures: ODCS contracts & ODPS data products

This directory holds YAML fixtures used by the backend unit and integration
tests to exercise import/export, parsing, and validation of Bitol standard
documents plus this app's own extensions to those standards.

## Folder layout

```
tests/data/
├── odcs/   # Open Data Contract Standard (Bitol ODCS) contracts
└── odps/   # Open Data Product Standard (Bitol ODPS) data products
```

### `odcs/` — Data Contracts

| File | Purpose |
|---|---|
| `full-example.odcs.yaml` | Canonical reference loaded by `test_odcs_roundtrip.py` and `test_odcs_export_validation.py`. **Keep to a single schema object, team-as-array, and rule-based quality** — those tests assert `len(exported["schema"]) == 1` and look for a `countCheck` rule. |
| `full-example.odcs_v3_0_2.yaml` | Bitol full example, ODCS v3.0.2 shape (team array, `rule`-based quality). |
| `full-example.odcs_v3_1_0.yaml` | Bitol full example, ODCS v3.1.0 shape (team object, `metric`-based quality, `relationships`, stable `id`s, two schema objects). |
| `full-example.odcs_v3_1_0-ontos-extensions.yaml` | v3.1.0 full example **plus all Ontos extensions** (namespaced tag FQNs, semantic assignments at every level, `ontos.businessOwners`, stable ids). |
| `team-as-object.odcs_v3_1_0.yaml` | Focused fixture for the v3.1.0 Team-as-object shape (team-level tags / customProperties / authoritativeDefinitions). |
| `minimal.odcs_v3_1_0.yaml` | Only the required fields — negative/edge surface for "optional sections absent". |
| `relationships-composite-keys.odcs_v3_1_0.yaml` | Schema-level composite FKs and property-level relationships. |
| `quality-rules-matrix.odcs_v3_1_0.yaml` | Every quality `type`, comparator, and dimension, at schema and property level. |
| `all-data-types.odcs.yaml` | Logical-type options matrix (string/number/date/array/object constraints). |
| `semantic-test.odcs.yaml` | Semantic-assignment-only contract. |
| `postgresql-adventureworks-contract.odcs_v3_0_2.yaml` / `_v3_1_0.yaml` | Large real-world AdventureWorks contract for both ODCS versions. |

### `odps/` — Data Products

| File | Purpose |
|---|---|
| `full-example.odps_v1_0_0.yaml` | Comprehensive ODPS v1.0.0 product: input/output/management ports, server connection details, SBOM, input contracts, support, team. |
| `full-example.odps_v1_0_0-ontos-extensions.yaml` | Full example **plus Ontos extensions** (`consumer_principals`, `max_level_inheritance`, `ontos.businessOwners`, namespaced tag FQNs, semantic assignments on product and ports). |
| `minimal.odps_v1_0_0.yaml` | Only the required fields (`apiVersion`, `kind`, `id`, `status`). |
| `ports-matrix.odps_v1_0_0.yaml` | Every input/output/management port variant (Kafka topic, Databricks share, S3 file, BigQuery, contract-less, tagged). |
| `multi-product-batch.odps_v1_0_0.yaml` | Top-level list of products (mix of valid + invalid) for the batch upload path. |

## Ontos extension encoding conventions

The app extends ODCS/ODPS with concepts the native specs do not model. To keep
fixtures **spec-valid**, extensions are encoded using existing in-spec carriers:

1. **Semantic assignments** — encoded as `authoritativeDefinitions` entries
   whose `type` is the semantic-assignment IRI
   `http://databricks.com/ontology/uc/semanticAssignment`. The `url` points at
   the ontology class (`rdfs:Class`) or property (`rdf:Property`). Valid at the
   contract, schema, property, role, team, product, and port levels. These are
   ingested by `process_all_semantic_links_from_odcs`. Non-semantic
   authoritative-definition `type`s (e.g. `businessDefinition`) must be
   preserved as-is.

2. **Unified tags with namespaces** — encoded as FQN strings inside the native
   `tags:` arrays. A bare name (`transactions`) maps to the `default`
   namespace; a slash-qualified name (`finance/payments`) maps to namespace
   `finance`, tag `payments`. The FQN is parsed via `AssignedTagCreate.tag_fqn`.

3. **Polymorphic business owners** — encoded under `customProperties` using the
   reserved key `ontos.businessOwners`, whose value is a list of records shaped
   like `BusinessOwnerCreate`:
   `{ objectType: data_contract|data_product|asset|data_domain|business_term|tag|dataset, userEmail, roleName }`.
   This mirrors the demo MDM contracts' use of `mdm*` custom properties, so the
   document stays schema-valid.

Other Ontos-only fields surfaced at the top level of ODPS products
(`consumer_principals`, `max_level_inheritance`) are parsed directly by the
`DataProduct` Pydantic model.

## Schema references

Live JSON Schemas used for validation are in `src/backend/src/schemas/`:

- `odcs-json-schema-v3.0.2.json`, `odcs-json-schema-v3.0.2-strict.json`,
  `odcs-json-schema-v3.1.0.json` — ODCS contract schemas.
- `odps-json-schema-v1.0.0.json` — ODPS product schema.

Bitol upstream sources:

- ODCS: <https://github.com/bitol-io/open-data-contract-standard>
- ODPS: <https://github.com/bitol-io/open-data-product-standard>

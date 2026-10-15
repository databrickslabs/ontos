# Linked contract/product fixtures

A small mesh of ODCS data contracts and ODPS data products that reference each
other by **stable UUID**, so the links survive import into Ontos and keep
resolving on read.

## Files

| File | Kind | `id` |
|------|------|------|
| `raw_orders.odcs.yaml` | Contract C1 | `fbfa8318-bb26-4172-a705-80c1ec94c4b6` |
| `sales_aggregates.odcs.yaml` | Contract C2 | `c8e034aa-0145-4e41-ae9b-b64dbcea41c8` |
| `exec_metrics.odcs.yaml` | Contract C3 | `7fdfef67-477b-4428-b53a-8fc2c4284f53` |
| `sales_analytics.odps.yaml` | Product P1 | `9fd027b7-b920-4fa0-940e-c27d5db03f9b` |
| `executive_dashboard.odps.yaml` | Product P2 | `7f6def4c-9f8e-4b95-aa80-e18fc071c301` |

## Link graph

```
C1 Raw Orders ◀──in──── P1 Sales Analytics ──out──▶ C2 Sales Aggregates
                                 ▲                          │
                                 └──── dataProduct ─────────┘
                                                            │
                                            in (shared contract)
                                                            ▼
                              C3 Executive Metrics ◀──out── P2 Executive Dashboard
                                        │                          ▲
                                        └──── dataProduct ─────────┘
```

- **P1 → C1**  `inputPorts[].contractId` (P1 consumes Raw Orders)
- **P1 → C2**  `outputPorts[].contractId` (P1 produces Sales Aggregates)
- **C2 → P1**  `dataProduct` (reciprocal: C2 names its producing product)
- **P2 → C2**  `inputPorts[].contractId` (P2 consumes P1's output — cross-product chain)
- **P2 → C3**  `outputPorts[].contractId` (P2 produces Executive Metrics)
- **C3 → P2**  `dataProduct` (reciprocal)

Every referenced value equals the target entity's top-level `id`, so there are
no dangling references.

## Why the links survive import

- **Stable ids** — each entity carries a UUID `id`. With `adopt_ids` ON
  (default; PR #853) the importer adopts it as the primary key instead of
  minting a new one, so every cross-reference still points at a real row.
- **Read-time resolution** (PR #854) —
  - input-port `contractId` → resolves to the contract's `contractName`;
  - contract `dataProduct` → resolves id-first to `dataProductName` /
    `dataProductId`.
  Unknown referents degrade gracefully (name stays null, raw value preserved).

## Import order

Order does not matter for persistence — references are stored verbatim and
resolved lazily on read. To see every link resolve **immediately** after each
import, load in dependency order:

1. `raw_orders.odcs.yaml` (C1)
2. `sales_analytics.odps.yaml` (P1)
3. `sales_aggregates.odcs.yaml` (C2)
4. `executive_dashboard.odps.yaml` (P2)
5. `exec_metrics.odcs.yaml` (C3)

Contracts import via the data-contracts upload / `POST /api/data-contracts/upload`;
products via the data-products upload / `POST /api/data-products/upload`.

## Round-trip check

Export any entity after import and confirm the reserved `ontos*` custom
properties (`ontosEntityId`, etc.) are emitted and that re-importing rebinds by
UUID rather than creating duplicates.

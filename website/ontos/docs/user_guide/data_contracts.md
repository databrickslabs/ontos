---
sidebar_position: 4
---

# Define Data Contracts

Data Contracts establish the technical specifications and guarantees for data assets in accordance with the Open Data Contract Standard (ODCS) v3.1.0. They include schema definitions covering column names, types, constraints, and descriptions, as well as quality guarantees that specify data quality rules and Service Level Objectives (SLOs). Additionally, they facilitate semantic linking by connecting schemas and properties to business concepts, and support versioning to track the evolution of contracts over time.

For a basic definition of Contracts, please refer to the [Core Concepts](../introduction/concepts) page.

## Contract lifecycle

Data Contracts in Ontos have a lifecycle and follow the order described below:

| Stage Name | Description | Status |
| --- | --- | --- |
| 📝 Draft | Initial creation. Defines scope, fields, types, and SLAs. | In Progress |
| 🙋 Proposed | Stakeholder review of requirements and definition. | Awaiting Review |
| 🔍 Under Review | Validation by legal, compliance, and engineering teams. | Active Evaluation |
| ✅ Approved | Contract finalized and accepted by all parties. | Finalized |
| 🚀 Active | Contract is implemented, enforced, and operational. | Deployed & Monitored |
| 🏅 Certified | Verified for compliance, quality, and standards. | Compliant & Proven |
| ⚠️ Deprecated | No longer recommended; replacement planned. | Sunset Notice |
| 🛑 Retired | Officially decommissioned and archived. Not in use. | Archived |

## Create and modify contracts

To create a Data Contract, follow these instructions:

1. Select the 📄 *Contracts* option in the Ontos sidebar.
2. Click on the *New Contract* button.
3. Add the details to your new Data Contract.

![Create a new Data Contract](../assets/contract_creation.png)

4. Select *Create Contract* to finish.

:::tip
To edit/modify your Data Contract, click on the Contract name from the Contracts page.
:::

## Upload contracts

In Ontos, you can upload predefined Data Contracts in ODCS v3.1.0 format. Currently, Ontos accepts JSON, YAML, or text files following the ODCS schema.

To upload an ODCS contract to Ontos:

1. Select the 📄 *Contracts* option in the Ontos sidebar.
2. Click on the *Upload File* button.
3. Select your ODCS contract file to upload or upload the following sample Customer contract:

<details>
<summary>Sample Customer 360 Core contract (ODCS JSON)</summary>

```json
{
  "apiVersion": "v3.1.0",
  "kind": "DataContract",
  "id": "urn:datacontract:customer:customer-360-core",
  "version": "1.0.0",
  "status": "active",
  "name": "Customer 360 Core",
  "domain": "customer",
  "dataProduct": "customer-360",
  "tenant": "AcmeRetailInc",
  "description": {
    "purpose": "Deduplicated view of every Acme retail customer with contact details and marketing consent.",
    "usage": "Customer segmentation, churn modelling and marketing activation. Join on customer_id.",
    "limitations": "Contains personal identifiers. Marketing activation must respect marketing_opt_in."
  },
  "tags": ["customer", "pii"],
  "servers": [
    {
      "server": "acme-prod-uc",
      "type": "databricks",
      "environment": "prod",
      "host": "dbc-a1b2c3d4-e5f6.cloud.databricks.com",
      "catalog": "acme_prod",
      "schema": "customer_360"
    }
  ],
  "schema": [
    {
      "name": "customers",
      "physicalName": "customers_v1",
      "logicalType": "object",
      "physicalType": "table",
      "description": "One row per customer.",
      "properties": [
        {
          "name": "customer_id",
          "description": "Immutable surrogate key issued at first contact.",
          "logicalType": "string",
          "logicalTypeOptions": { "format": "uuid" },
          "physicalType": "STRING",
          "required": true,
          "unique": true,
          "primaryKey": true,
          "primaryKeyPosition": 1,
          "classification": "internal",
          "examples": ["6f2a7c1e-8b34-4d5a-9f10-2c7e5a41b9d0"]
        },
        {
          "name": "email",
          "description": "Primary lowercase email address.",
          "logicalType": "string",
          "logicalTypeOptions": { "format": "email" },
          "physicalType": "STRING",
          "required": false,
          "classification": "restricted",
          "examples": ["ada.lovelace@example.com"]
        },
        {
          "name": "full_name",
          "description": "Customer's display name.",
          "logicalType": "string",
          "physicalType": "STRING",
          "required": false,
          "classification": "restricted"
        },
        {
          "name": "country_code",
          "description": "ISO 3166-1 alpha-2 country of residence.",
          "logicalType": "string",
          "logicalTypeOptions": { "pattern": "^[A-Z]{2}$" },
          "physicalType": "STRING",
          "required": true,
          "classification": "internal",
          "examples": ["GB", "DE"]
        },
        {
          "name": "status",
          "description": "Lifecycle state of the customer record.",
          "logicalType": "string",
          "logicalTypeOptions": { "pattern": "^(prospect|active|dormant|churned)$" },
          "physicalType": "STRING",
          "required": true,
          "classification": "internal",
          "examples": ["active"]
        },
        {
          "name": "marketing_opt_in",
          "description": "True when the customer has given explicit consent to marketing contact.",
          "logicalType": "boolean",
          "physicalType": "BOOLEAN",
          "required": true,
          "classification": "internal"
        },
        {
          "name": "updated_at",
          "description": "UTC timestamp of the last change to this record.",
          "logicalType": "timestamp",
          "physicalType": "TIMESTAMP",
          "required": true,
          "classification": "internal"
        }
      ],
      "quality": [
        {
          "description": "customer_id is never null.",
          "type": "library",
          "metric": "nullValues",
          "mustBe": 0,
          "dimension": "completeness",
          "severity": "error"
        },
        {
          "description": "The golden record is deduplicated.",
          "type": "library",
          "metric": "duplicateValues",
          "mustBe": 0,
          "dimension": "uniqueness",
          "severity": "error"
        }
      ]
    }
  ],
  "team": {
    "name": "Customer Data Platform",
    "members": [
      {
        "username": "r.okonkwo@acme.example.com",
        "name": "Rachel Okonkwo",
        "role": "Data Product Owner"
      },
      {
        "username": "s.varga@acme.example.com",
        "name": "Sam Varga",
        "role": "Lead Data Engineer"
      }
    ]
  },
  "roles": [
    {
      "role": "customer_360_reader",
      "access": "read",
      "firstLevelApprovers": "Data Product Owner"
    }
  ],
  "slaProperties": [
    { "property": "latency", "value": 2, "unit": "h", "element": "customers.updated_at" },
    { "property": "frequency", "value": 1, "unit": "d", "element": "customers.updated_at" }
  ],
  "support": [
    {
      "channel": "#customer-360-support",
      "tool": "slack",
      "url": "https://acme.slack.com/archives/C0CUST360"
    }
  ],
  "contractCreatedTs": "2026-08-04T09:00:00+00:00"
}
```
</details>


## Contract actions

Once a contract is created, users in Ontos can perform various actions, including:

### Certify

Certify a contract for high-value or regulated use cases. Certified contracts are publicly visible with a certification badge.

Certification is available at the following levels:

- Bronze
- Silver
- Gold

### Publish

Publishing defines the scope of visibility, indicating who can discover this entity once published. The available scopes are:

| Scope | Description |
| --- | --- |
| Organization | Visible across the organization |
| Domain | Individual domain within the organization |
| Not published | Remains part of the project (private or team) that it belongs to |
| External | Visible outside the organization |

### Request

Types of requests to be performed on the data contract, including:

| Request | Description |
| --- | --- |
| Change Status | Transition the [lifecycle](#contract-lifecycle) status of this contract to another stage. |
| Deploy to Unity Catalog | Request approval to deploy this contract to Unity Catalog. |
| Publish | Request to publish this contract with a defined visibility scope. |
| Certification | Request that this contract be certified at a specific level. |
| Access | Request permission to view and use this data contract. |

### Comments

Displays a timeline of activities, including contract object modifications and user comments. Comments can be submitted to project-level boundaries or at the Global level.

### Create a new version

Generates a new Data Contract version based on user input. After creating it, a dropdown menu appears on the main contract page, showing the current and past versions.

![Data Contract versions](../assets/contract_versions.png)

### Delete

Deletes the current version of the Data Contract.

:::warning
Make sure you don't delete certified or active versions. Transition the state into Deprecated first and then proceed to delete if needed.
:::

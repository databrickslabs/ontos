# Ontos User Guide

## Table of Contents

1. [Introduction](#introduction)
2. [Core Concepts](#core-concepts)
3. [Getting Started](#getting-started)
4. [Growing with Ontos](#growing-with-ontos)
5. [Working with Domains](#working-with-domains)
6. [Managing Teams](#managing-teams)
7. [Organizing Projects](#organizing-projects)
8. [Managing Datasets](#managing-datasets)
9. [Creating Data Contracts](#creating-data-contracts)
10. [Building Data Products](#building-data-products)
11. [Semantic Models](#semantic-models)
12. [Compliance Checks](#compliance-checks)
13. [Process Workflows](#process-workflows)
14. [Asset Review Workflow](#asset-review-workflow)
15. [User Roles and Permissions](#user-roles-and-permissions)
16. [MCP Integration (AI Assistants)](#mcp-integration-ai-assistants)
17. [Delivery Modes](#delivery-modes)
18. [Best Practices](#best-practices)

---

## Introduction

**Ontos** is a comprehensive data governance and management platform built for Databricks Unity Catalog. It provides enterprise teams with the tools to organize, govern, and deliver high-quality data products following Data Mesh principles and industry standards like ODCS (Open Data Contract Standard) and ODPS (Open Data Product Specification).

### Key Capabilities

- **Organizational Structure**: Organize data work using domains, teams, and projects
- **Datasets**: Register and group existing data assets (tables, views, metrics, topics) across platforms and environments
- **Data Contracts**: Define formal specifications for data assets with schema, quality rules, and semantic meaning
- **Data Products**: Group and manage related Databricks assets as cohesive products
- **Semantic Models**: Link data assets to business concepts and maintain a knowledge graph
- **Compliance Automation**: Enforce governance policies using a declarative rules language
- **Review Workflows**: Manage data steward reviews and approvals for governance
- **AI Integration (MCP)**: Enable AI assistants to discover and interact with your data governance platform via the Model Context Protocol
- **Multi-Platform Connectors**: Pluggable architecture for Unity Catalog, Snowflake, Kafka, Power BI, and more

### Who Should Use This Guide

This guide is intended for:
- **Data Product Owners**: Managing product vision and delivery
- **Data Engineers**: Building and maintaining data pipelines and products
- **Data Stewards**: Ensuring governance, compliance, and quality
- **Data Consumers**: Discovering and using data products
- **Analytics Teams**: Working with curated data for insights
- **Platform Engineers**: Integrating AI assistants and automating workflows via MCP

---

## Core Concepts

Understanding these foundational concepts will help you effectively use Ontos.

![Ontos Object Model](/ontos-obj-model.svg)

### Domains

**Domains** represent logical groupings of data based on business areas or organizational structure. They provide high-level organization for your data assets.

- **Hierarchical**: Domains can have parent-child relationships (e.g., "Retail" → "Retail Operations")
- **Examples**: Finance, Sales, Marketing, Customer, Product, Supply Chain
- **Purpose**: Group related data products and provide clear ownership boundaries

### Teams

**Teams** are collections of users and groups working together on data initiatives.

- **Members**: Can include individual users or Databricks workspace groups
- **Domain Assignment**: Teams can be associated with specific domains
- **Role Overrides**: Individual members can have custom roles within the team
- **Metadata**: Track team information like Slack channels, leads, and tools

### Projects

**Projects** are workspace containers that organize team initiatives with defined boundaries.

- **Types**: 
  - **Personal**: Individual user workspaces (auto-created)
  - **Team**: Shared workspaces for collaborative work
- **Team Assignment**: Multiple teams can collaborate on a project
- **Isolation**: Provides logical boundaries for development work

### Assets & Asset Explorer

**Assets** are the unified representation of all cataloged objects in Ontos, powered by the ontology-driven data model. Asset types (Dataset, Table, View, Dashboard, API Endpoint, Stream, etc.) are defined in the ontology (`ontos-ontology.ttl`) and synced automatically at startup.

- **Ontology-Driven**: Asset types, their fields, and valid relationships are all derived from the OWL ontology
- **Unified Model**: Replaces bespoke tables for datasets, tables, views, etc. with a single `assets` table using typed properties
- **Dynamic Forms**: Create and edit any asset type using dynamically generated forms based on the ontology schema
- **Entity Relationships**: Cross-entity relationships (lineage, containment, consumption) stored in `entity_relationships`
- **Persona Visibility**: Asset types are filtered per-persona based on ontology annotations
- **Asset Explorer**: Browse all asset types in a unified sidebar with type-based filtering, available under Data Steward and Data Governance Officer personas

> **Legacy Note**: The standalone "Datasets" feature is deprecated. Datasets are now stored as
> Asset entities with `asset_type="Dataset"`. The legacy API at `/api/datasets` remains for
> backward compatibility.

### Data Contracts

**Data Contracts** define the technical specifications and guarantees for data assets following ODCS v3.1.0 standard.

- **Schema Definition**: Column names, types, constraints, and descriptions
- **Quality Guarantees**: Data quality rules and SLOs (Service Level Objectives)
- **Semantic Linking**: Connect schemas and properties to business concepts
- **Lifecycle**: Draft → Proposed → Under Review → Approved → Active → Certified → Deprecated → Retired
- **Versioning**: Track contract evolution over time

### Data Products

**Data Products** are curated collections of Databricks assets (tables, views, models) delivered as consumable products.

- **Product Types**: Source, Source-Aligned, Aggregate, Consumer-Aligned
- **Input/Output Ports**: Define data flows and dependencies
- **Tags**: Organize and discover products using standardized tags
- **Status**: Development → Sandbox → Pending Certification → Certified → Active → Deprecated

### Semantic Models

**Semantic Models** provide a knowledge graph connecting technical data assets to business concepts.

- **Business Concepts**: High-level domain concepts (Customer, Product, Transaction)
- **Business Properties**: Specific data elements (email, firstName, customerId)
- **Semantic Linking**: Three-tier system linking contracts, schemas, and properties to business terms
- **RDF/RDFS**: Based on standard ontology formats for interoperability

### Compliance Policies

**Compliance Policies** are rules that automatically check your data assets for governance requirements.

- **DSL (Domain-Specific Language)**: Write rules in a SQL-like declarative syntax
- **Entity Types**: Check catalogs, schemas, tables, views, functions, and app entities
- **Actions**: Tag non-compliant assets, send notifications, or fail validations
- **Continuous Monitoring**: Run policies on schedules to track compliance over time

### Connectors (Platform Integrations)

**Connectors** are pluggable components that enable Ontos to discover and manage assets from different data platforms.

- **Unified Interface**: All connectors implement the same asset discovery and metadata API
- **Platform-Agnostic Governance**: Write policies that work across Unity Catalog, Snowflake, Kafka, etc.
- **Extensible Architecture**: New connectors can be added without changing core governance logic
- **Native UC Support**: Unity Catalog connector is fully implemented with support for tables, views, functions, models, volumes, and metrics

**Currently Available:**
- **Databricks/Unity Catalog**: Full support for all UC object types including AI/BI metrics

**Planned Connectors:**
- **Snowflake**: Tables, views, streams, stages, functions
- **Apache Kafka**: Topics, Schema Registry schemas
- **Microsoft Power BI**: Datasets, semantic models, dashboards, reports

---

## Getting Started

When you first access Ontos as an enterprise, the application will be empty. Here's how to set up your data governance foundation.

### Initial Setup Checklist

1. **Configure Roles and Permissions** (Admin task)
2. **Create Domain Structure**
3. **Set Up Teams**
4. **Define Initial Projects**
5. **Load Semantic Models** (Optional)
6. **Create Compliance Policies**
7. **Begin Creating Datasets, Contracts, and Products**

**Tip**: See the [Growing with Ontos](#growing-with-ontos) section for a recommended progression path from datasets → contracts → products → compliance.

### Step 1: Configure Roles and Permissions

**Who**: System Administrator

Navigate to **Settings → RBAC** to configure roles and permissions.

#### Default Roles

Ontos comes with predefined roles:

- **Admin**: Full system access
- **Data Governance Officer**: Broad governance capabilities
- **Data Steward**: Review and approve contracts/products
- **Data Producer**: Create and manage contracts/products
- **Data Consumer**: Read-only access to discover data

#### Assign Groups to Roles

1. Go to **Settings → RBAC → Roles**
2. Select a role (e.g., "Data Steward")
3. Click **Edit** and assign Databricks workspace groups
4. Configure **Deployment Policies** to control catalog/schema access

**Example Deployment Policy**:
```json
{
  "allowed_catalogs": ["dev_*", "staging_*", "prod_analytics"],
  "allowed_schemas": ["*"],
  "default_catalog": "dev_team",
  "default_schema": "default",
  "require_approval": true,
  "can_approve_deployments": false
}
```

This policy allows the role to deploy to catalogs matching `dev_*` or `staging_*` patterns.

### Step 2: Create Domain Structure

**Who**: Data Governance Officer or Admin

Navigate to **Domains** in the sidebar.

#### Creating Your First Domain

1. Click **Create Domain**
2. Fill in the form:
   - **Name**: A unique identifier (e.g., "Finance")
   - **Description**: Clear description of the domain scope
   - **Parent Domain**: Optional parent (e.g., "Core" as root)
   - **Tags**: Add relevant tags for categorization

3. Click **Create**

#### Example Domain Hierarchy

```text
Core (root)
├── Finance
│   ├── Accounting
│   └── Treasury
├── Sales
│   ├── Retail Sales
│   └── Enterprise Sales
├── Customer
└── Product
```

**Best Practice**: Start with 3-5 high-level domains and expand as needed. Avoid creating too many domains initially.

### Step 3: Set Up Teams

**Who**: Domain Owners or Admins

Navigate to **Teams** in the sidebar.

#### Creating a Team

1. Click **Create Team**
2. Fill in the form:
   - **Name**: Unique team identifier (e.g., "data-engineering")
   - **Title**: Display name (e.g., "Data Engineering Team")
   - **Description**: Team's purpose and responsibilities
   - **Domain**: Select the team's primary domain
   - **Metadata**: Add Slack channel, team lead email, etc.

3. Add team members:
   - **Type**: User (individual email) or Group (Databricks group name)
   - **Member Identifier**: Email address or group name
   - **Role Override**: Optional custom role for this member

4. Click **Create**

#### Example Team Configuration

```yaml
Name: analytics-team
Title: Analytics Team
Description: Business analytics and reporting
Domain: Retail Analytics
Members:
  - alice.johnson@company.com (Data Consumer)
  - analysts (Databricks group - inherits role)
  - bob.smith@company.com (Data Steward - override)
Metadata:
  slack_channel: #analytics-team
  lead: alice.johnson@company.com
  tools: ["Tableau", "SQL", "Python"]
```

### Step 4: Define Initial Projects

**Who**: Team Leads or Product Owners

Navigate to **Projects** in the sidebar.

#### Creating a Project

1. Click **Create Project**
2. Fill in the form:
   - **Name**: Unique project identifier (e.g., "customer-360-platform")
   - **Title**: Display name (e.g., "Customer 360 Platform")
   - **Description**: Project objectives and scope
   - **Project Type**: Team (for shared work)
   - **Owner Team**: Primary team responsible for the project
   - **Metadata**: Add documentation links, timelines, etc.

3. Assign additional teams if needed
4. Click **Create**

**Personal Projects**: Each user automatically gets a personal project (e.g., `project_jsmith`) for individual experimentation.

### Step 5: Load Semantic Models (Optional)

**Who**: Data Governance Officer or Admin

Semantic models provide business context for your data. Ontos includes sample taxonomies, or you can create custom ones.

#### Using Built-in Taxonomies

Navigate to **Semantic Models** to explore pre-loaded concepts:

- **Business Concepts**: Customer, Product, Transaction, etc.
- **Business Properties**: email, firstName, customerId, etc.

These are loaded from RDF/RDFS files at:
- `/src/backend/src/data/taxonomies/business-concepts.ttl`
- `/src/backend/src/data/taxonomies/business-properties.ttl`

#### Adding Custom Concepts

Contact your administrator to add custom RDF/RDFS files to the taxonomies directory. After adding files, restart the application to load them.

### Step 6: Create Compliance Policies

**Who**: Data Governance Officer or Security Officer

Navigate to **Compliance** in the sidebar.

#### Creating Your First Policy

1. Click **Create Policy**
2. Fill in the form:
   - **Name**: Descriptive name (e.g., "Table Naming Conventions")
   - **Description**: What the policy checks
   - **Severity**: Critical, High, Medium, Low
   - **Category**: Governance, Security, Quality, etc.

3. Write the compliance rule using the DSL (see [Compliance Checks](#compliance-checks) section)

4. Click **Save**

#### Example Starter Policy

```text
MATCH (obj:Object)
WHERE obj.type IN ['table', 'view'] AND obj.catalog = 'prod'
ASSERT HAS_TAG('data-product') OR HAS_TAG('excluded-from-products')
ON_FAIL FAIL 'All production assets must be tagged with a data product'
ON_FAIL ASSIGN_TAG compliance_status: 'untagged'
```

This policy ensures all production tables and views are organized into data products.

---

## Growing with Ontos

Ontos is designed to support your data governance journey at any stage. Whether you're just starting to catalog existing data assets or building a mature data mesh, Ontos provides a natural progression path.

### The Growth Journey

```plaintext
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   1. DISCOVER          2. FORMALIZE         3. PRODUCTIZE     4. GOVERN     │
│   ───────────          ────────────         ─────────────     ─────────     │
│                                                                             │
│   ┌─────────┐         ┌─────────────┐       ┌───────────┐    ┌──────────┐   │
│   │ Datasets│   →     │   Data      │   →   │   Data    │ →  │Compliance│   │
│   │         │         │  Contracts  │       │ Products  │    │  Checks  │   │
│   └─────────┘         └─────────────┘       └───────────┘    └──────────┘   │
│                                                                             │
│   Register your       Define specs         Package for       Automate       │
│   existing tables     and quality          business value    quality        │
│   and views           guarantees           delivery          monitoring     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Stage 1: Discover with Datasets

**Goal**: Catalog your existing data assets and understand what you have.

**Who**: Data Engineers, Data Producers

**What to Do**:
1. Navigate to **Datasets** → **Create Dataset**
2. Give your dataset a meaningful name (e.g., "Customer Master Data")
3. Add physical instances pointing to your Unity Catalog tables
4. Group related tables together (main + dimensions + lookups)
5. Assign ownership to a team
6. Add tags for discoverability

**Example**:
```yaml
Dataset: Customer Master Data
Description: Core customer information across all systems

Instances:
  - Main Table: prod_catalog.crm.customers (Production)
  - Dimension: prod_catalog.crm.customer_addresses (Production)
  - Lookup: prod_catalog.reference.countries (Production)
  - Main Table: dev_catalog.crm.customers (Development)

Owner: data-engineering
Tags: customer, pii, crm
```

**Benefits at This Stage**:
- ✅ Central registry of data assets
- ✅ Team ownership visibility
- ✅ Basic discoverability via search
- ✅ Foundation for governance

### Stage 2: Formalize with Data Contracts

**Goal**: Define specifications, quality guarantees, and semantic meaning for your data.

**Who**: Data Producers, Data Stewards

**What to Do**:
1. From a Dataset, click **Create Contract from Dataset**
2. Ontos infers schema from Unity Catalog (if UC-backed)
3. Enrich with:
   - Column descriptions and business meaning
   - Data quality rules (not null, valid ranges, patterns)
   - SLOs (freshness, availability, accuracy targets)
   - Semantic links to business concepts
4. Submit for Data Steward review
5. Link the approved contract back to your dataset

**Example**:
```yaml
Contract: Customer Data Contract v1.0.0
Status: Active
Implements Schema: customers

Properties:
  - customer_id (string, required, unique)
    → Linked to: "customerId" business property
  
  - email (string, required, unique, PII)
    → Linked to: "email" business property
    Quality Rule: Must match email pattern
  
  - created_at (timestamp, required)
    Quality Rule: Cannot be in the future

SLOs:
  - Freshness: Updated daily by 6 AM UTC
  - Completeness: >99% for required fields
```

**Benefits at This Stage**:
- ✅ Formal quality commitments
- ✅ Schema documentation
- ✅ Semantic clarity via business concepts
- ✅ Breaking change prevention
- ✅ Consumer expectations are clear

### Stage 3: Productize with Data Products

**Goal**: Package datasets and contracts into consumable, value-delivering products.

**Who**: Data Product Owners, Data Engineers

**What to Do**:
1. Navigate to **Products** → **Create Product**
2. Define product metadata:
   - Name, description, owner team
   - Product type (Source, Aggregate, Consumer-Aligned)
3. Link to your data contracts
4. Define input/output ports:
   - Where data comes from
   - What data is delivered
5. Add tags and documentation
6. Submit for review and publish to marketplace

**Example**:
```yaml
Product: Customer 360 View
Type: Aggregate
Status: Active

Description: Comprehensive customer profile combining 
  CRM, transactions, and support interactions.

Implements Contracts:
  - Customer Data Contract v1.0.0
  - Transaction Data Contract v2.0.0

Input Ports:
  - customer-master-dataset (Dataset)
  - transaction-history (Table)
  
Output Ports:
  - customer_360_enriched (Delta Table)
    Location: main.analytics.customer_360
    Contract: Customer 360 Contract v1.0.0
```

**Benefits at This Stage**:
- ✅ Clear value proposition for consumers
- ✅ Self-service discovery in marketplace
- ✅ Defined data lineage
- ✅ Product-oriented thinking
- ✅ Formalized input/output contracts

### Stage 4: Govern with Compliance Checks

**Goal**: Automate quality monitoring and policy enforcement.

**Who**: Data Governance Officers, Data Stewards

**What to Do**:
1. Navigate to **Compliance** → **Create Policy**
2. Write rules using the Compliance DSL:
   - Naming conventions
   - Documentation requirements
   - Security policies (PII handling)
   - Quality thresholds
3. Schedule automated runs
4. Set up notifications for violations
5. Track compliance scores over time

**Example Policies**:

**Policy 1: All Production Assets Must Have Contracts**
```text
MATCH (obj:Object)
WHERE obj.type IN ['table', 'view'] AND obj.catalog = 'prod'
ASSERT HAS_TAG('data-contract')
ON_FAIL FAIL 'Production assets must be linked to a data contract'
ON_FAIL ASSIGN_TAG compliance_issue: 'missing_contract'
```

**Policy 2: Dataset Ownership Required**
```text
MATCH (ds:dataset)
WHERE ds.status = 'active'
ASSERT ds.owner_team != '' AND ds.owner_team != null
ON_FAIL FAIL 'Active datasets must have an owner team assigned'
ON_FAIL NOTIFY 'data-governance@company.com'
```

**Policy 3: Contract Quality SLOs**
```text
MATCH (contract:data_contract)
WHERE contract.status = 'active'
ASSERT HAS_TAG('slo_defined') AND TAG('slo_freshness') != ''
ON_FAIL FAIL 'Active contracts must have freshness SLOs defined'
```

**Benefits at This Stage**:
- ✅ Automated policy enforcement
- ✅ Proactive issue detection
- ✅ Continuous quality monitoring
- ✅ Compliance reporting
- ✅ Reduced manual review burden

### The Complete Picture

When all stages are in place, you have a complete data governance ecosystem:

```plaintext
┌──────────────────────────────────────────────────────────────────┐
│                        DATA GOVERNANCE                           │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐                                                │
│  │   Datasets   │ ←── Physical reality                           │
│  │  (Instances) │     What exists in UC/Snowflake                │
│  └──────┬───────┘                                                │
│         │ implements                                             │
│         ▼                                                        │
│  ┌──────────────┐                                                │
│  │    Data      │ ←── Specification                              │
│  │  Contracts   │     Quality, schema, semantics                 │
│  └──────┬───────┘                                                │
│         │ packages                                               │
│         ▼                                                        │
│  ┌──────────────┐                                                │
│  │    Data      │ ←── Value delivery                             │
│  │  Products    │     Business-ready data                        │
│  └──────┬───────┘                                                │
│         │ monitored by                                           │
│         ▼                                                        │
│  ┌──────────────┐                                                │
│  │  Compliance  │ ←── Continuous governance                      │
│  │   Policies   │     Automated quality checks                   │
│  └──────────────┘                                                │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Starting Points Based on Your Maturity

| Current State | Recommended Starting Point |
|---------------|---------------------------|
| No catalog, scattered data | Start with **Datasets** to inventory assets |
| Have catalog, no contracts | Add **Data Contracts** to formalize specs |
| Have contracts, no products | Build **Data Products** for value delivery |
| Have products, no automation | Add **Compliance Policies** for governance |
| Everything in place | Focus on **optimization and adoption** |

### Tips for Success

1. **Start Small**: Begin with one domain or team
2. **Quick Wins First**: Catalog high-value datasets that teams use daily
3. **Iterate**: Don't aim for perfection; improve incrementally
4. **Involve Stakeholders**: Get buy-in from data producers and consumers
5. **Measure Progress**: Track metrics like catalog coverage, contract adoption
6. **Celebrate Milestones**: Recognize teams that adopt governance practices

---

## Working with Domains

Domains provide the top-level organizational structure for your data assets.

### Viewing Domains

Navigate to **Domains** to see all domains in your organization. The view shows:

- Domain hierarchy (parent-child relationships)
- Domain descriptions
- Associated tags
- Number of teams and products in each domain

### Creating a Domain

1. Click **Create Domain**
2. Enter domain details:
   - **Name**: Must be unique (e.g., "Customer")
   - **Description**: Scope and purpose
   - **Parent Domain**: Optional parent for hierarchy
   - **Tags**: Add classification tags

3. Click **Create**

### Editing a Domain

1. Click on a domain name to view details
2. Click **Edit**
3. Modify fields as needed
4. Click **Save**

**Note**: Changing a domain name may affect references in teams, products, and contracts.

### Domain Best Practices

- **Start Simple**: Begin with 3-7 top-level domains aligned to major business areas
- **Align with Organization**: Match your organizational structure or data mesh architecture
- **Clear Ownership**: Each domain should have a clear owner (Domain Owner persona)
- **Stable Names**: Avoid frequent name changes; use descriptions for evolving scope
- **Use Hierarchy**: Create sub-domains for complex areas (e.g., Retail → Retail Operations, Retail Analytics)

---

## Managing Teams

Teams are the collaborative units that build and maintain data products.

### Viewing Teams

Navigate to **Teams** to see all teams. The view displays:

- Team name and title
- Associated domain
- Number of members
- Creation date

### Creating a Team

1. Click **Create Team**
2. Fill in basic information:
   - **Name**: Unique identifier (lowercase with hyphens recommended)
   - **Title**: Display name
   - **Description**: Team purpose and responsibilities
   - **Domain**: Primary domain assignment

3. Add metadata (optional):
   - **Slack Channel**: Team communication channel
   - **Lead**: Team lead email
   - **Tools**: Technologies the team uses

4. Add team members:
   - Click **Add Member**
   - Select type: **User** or **Group**
   - Enter identifier (email or group name)
   - Set optional role override

5. Click **Create**

### Managing Team Members

#### Adding Members

1. Open team details
2. Click **Add Member**
3. Enter member details
4. Click **Add**

#### Role Overrides

Team members inherit roles from their Databricks groups by default. You can override this:

1. Edit a team member
2. Select **Role Override**
3. Choose a different role (e.g., promote to Data Steward within this team)

**Use Case**: A user is normally a "Data Consumer" globally, but acts as "Data Producer" for their team's domain.

### Team Composition Guidelines

#### Minimal Team (2-3 people)

For simple domains or prototypes:

- **Data Product Owner**: Vision and stakeholder management
- **Data Engineer**: Implementation and operations
- **Optional Analyst/QA**: Validation and testing

**Timeline**: 1-3 weeks for simple data products

#### Elaborate Team (5-8 people)

For mission-critical domains:

- **Data Product Owner**: Product strategy and roadmap
- **Lead Data Engineer**: Technical architecture
- **Data Engineers (2-3)**: Implementation
- **Business Analyst**: Requirements and documentation
- **QA Engineer**: Testing and validation
- **Data Steward Liaison**: Governance and compliance

**Timeline**: 1-3 months for complex data products

---

## Organizing Projects

Projects provide workspace isolation and organization for team initiatives.

### Viewing Projects

Navigate to **Projects** to see all projects:

- Project name and title
- Owner team
- Assigned teams
- Project type (Personal or Team)

### Creating a Team Project

1. Click **Create Project**
2. Fill in the form:
   - **Name**: Unique identifier (e.g., "fraud-detection-ml")
   - **Title**: "Fraud Detection ML Platform"
   - **Description**: Project goals and deliverables
   - **Project Type**: Team
   - **Owner Team**: Select the primary team

3. Assign collaborating teams (optional)
4. Add metadata:
   - Documentation links
   - Milestones
   - Related systems

5. Click **Create**

### Personal Projects

Personal projects are automatically created for each user when they first use certain features. Format: `project_{username}`.

**Use Cases**:
- Individual experimentation
- Learning and training
- Personal data analysis
- Prototype development

### Project Lifecycle

1. **Planning**: Define scope, teams, and objectives
2. **Development**: Build data contracts and products
3. **Review**: Submit for governance approval
4. **Production**: Deploy and monitor
5. **Maintenance**: Ongoing updates and support
6. **Sunset**: Deprecate and archive when no longer needed

---

## Managing Datasets

> **Note:** The standalone Datasets model is **deprecated**. Datasets are now stored as
> Asset entities (type "Dataset") in the ontology-driven data model. Use the **Asset Explorer**
> (available under Data Steward and Data Governance Officer personas) to browse, create,
> and manage datasets alongside all other asset types. The legacy Datasets API (`/api/datasets`)
> remains available for backward compatibility but will be removed in a future version.

Datasets are the entry point for bringing your existing data assets into Ontos. They represent logical groupings of related physical tables and views.

### What is a Dataset?

A Dataset is:
- A **logical container** for related data assets (main table + dimensions + lookups + metrics)
- A **registry** of physical implementations across multiple platforms and environments
- A **bridge** between raw assets and formal Data Contracts
- A **discoverable entity** in the data marketplace
- A **platform-agnostic** abstraction over Unity Catalog, Snowflake, Kafka, Power BI, and other systems

**Key Distinction**:
- **Dataset** = What physically exists (tables, views, metrics, topics across platforms)
- **Data Contract** = What should exist (specification, quality rules)
- **Data Product** = How value is delivered (packaged, documented, monitored)

**Multi-Platform Capability**: Ontos uses a pluggable connector architecture to support assets from multiple platforms. Unity Catalog is fully supported with native connectivity. Connectors for Snowflake, Kafka, and Power BI are planned for future releases.

### Viewing Datasets

Navigate to **Datasets** in the sidebar to see all registered datasets:

- Dataset name and description
- Status (Draft, Active, Deprecated, Retired)
- Associated data contract (if linked)
- Owner team
- Number of physical instances
- Subscriber count

### Creating a Dataset

**Who**: Data Producers, Data Engineers

1. Click **Create Dataset**
2. Fill in basic information:
   - **Name**: Descriptive name (e.g., "Customer Master Data")
   - **Description**: Purpose and contents
   - **Status**: Draft (initially)
   - **Owner Team**: Responsible team
   - **Project**: Optional project assignment
   
3. Click **Create**

**Note**: Physical instances are added from the dataset details page after creation.

### Adding Physical Instances

Physical instances represent actual tables/views in your data platform.

#### From the Dataset Details Page

1. Open a dataset
2. In the **Physical Instances** section, click **Add Instance**
3. Fill in instance details:

   **Contract Version** (optional):
   - Select a data contract this instance implements
   - Enables compliance checking
   
   **Server** (if contract selected):
   - Choose from servers defined in the contract
   - Provides system type (Databricks, Snowflake) and environment
   
   **Physical Path** (required):
   - Full path to the object
   - Format: `catalog.schema.table` for Unity Catalog
   - Format: `DATABASE.SCHEMA.TABLE` for Snowflake
   - Format: `topic_name` for Kafka topics
   
   **Asset Type** (optional but recommended):
   - Unified type identifier across platforms
   - Examples: `uc_table`, `uc_view`, `uc_metric`, `snowflake_table`, `kafka_topic`
   - Enables platform-agnostic compliance policies and search
   
   **Role**:
   - **Main Table**: Primary data in the dataset
   - **Dimension**: Related dimension table
   - **Lookup**: Reference/lookup table
   - **Reference**: External reference data
   - **Staging**: Intermediate staging table
   
   **Environment**:
   - Development, Staging, Production, Test, QA, UAT
   
   **Display Name**:
   - Human-readable name for this specific instance
   
   **Status**:
   - Active, Deprecated, Retired

4. Click **Create**

#### Example Instance Configuration

```yaml
Instance: Customers Master Table
Role: Main Table
Environment: Production
Physical Path: prod_catalog.crm.customers_master
Asset Type: uc_table
Contract: Customer Data Contract v1.0.0
Server: databricks-prod
Status: Active
Tags: delta-table, partitioned
```

#### Multi-Platform Instance Example

```yaml
Dataset: Customer Master Data
Description: Core customer information across all systems

Instances:
  # Unity Catalog (primary)
  - Physical Path: prod.crm.customers
    Asset Type: uc_table
    Role: Main Table
    Environment: Production
    Server: databricks-prod
  
  # Unity Catalog Metric
  - Physical Path: prod.crm.customer_count
    Asset Type: uc_metric
    Role: Reference
    Environment: Production
    
  # Snowflake replica (when connector available)
  - Physical Path: ANALYTICS.CRM.CUSTOMERS
    Asset Type: snowflake_table
    Role: Main Table
    Environment: Production
    Server: snowflake-prod
```

### Grouping Related Tables

A key strength of Datasets is grouping related tables:

**Example: Customer Master Dataset**

```text
Customer Master Data (Dataset)
├── Main Table
│   ├── prod_catalog.crm.customers_master (Production)
│   └── dev_catalog.crm.customers_master (Development)
├── Dimension
│   └── prod_catalog.crm.customer_addresses (Production)
└── Lookup
    ├── prod_catalog.reference.countries (Production)
    └── prod_catalog.reference.regions (Production)
```

**Benefits**:
- Single point of discovery for related data
- Clear ownership across all related assets
- Consistent contract application
- Simplified impact analysis

### Multi-System Support

Ontos uses a **pluggable connector architecture** that supports multiple data platforms through a unified asset registry. This enables you to manage assets from different systems within the same governance framework.

#### Supported Platforms

| Platform | Connector | Status | Supported Asset Types |
|----------|-----------|--------|----------------------|
| **Databricks Unity Catalog** | `databricks` | ✅ Active | Tables, Views, Functions, Models, Volumes, Metrics, Notebooks, Jobs, Pipelines |
| **Snowflake** | `snowflake` | 🔜 Planned | Tables, Views, Streams, Stages, Functions, Procedures, Tasks |
| **Apache Kafka** | `kafka` | 🔜 Planned | Topics, Schemas (Schema Registry) |
| **Microsoft Power BI** | `powerbi` | 🔜 Planned | Datasets, Semantic Models, Dashboards, Reports, Dataflows |
| **Cloud Storage** | Various | 🔜 Planned | S3 Buckets/Objects, ADLS Containers, GCS Buckets |

#### Physical Path Formats

| System | Physical Path Format | Example |
|--------|---------------------|---------|
| Unity Catalog | `catalog.schema.table` | `prod.crm.customers` |
| Snowflake | `DATABASE.SCHEMA.TABLE` | `ANALYTICS.CRM.CUSTOMERS` |
| Kafka | `topic_name` | `customer-events` |
| Power BI | `workspace/dataset` | `Analytics/Customer360` |
| S3 | `s3://bucket/path/` | `s3://data-lake/customers/` |

#### Unified Asset Types

Each dataset instance can specify an **asset type** that identifies the kind of asset across platforms:

**Unity Catalog Assets:**
- `uc_table` - Managed or external tables
- `uc_view` - Standard views
- `uc_materialized_view` - Materialized views
- `uc_streaming_table` - Streaming tables (DLT/SDP)
- `uc_function` - User-defined functions
- `uc_model` - Registered ML models
- `uc_volume` - Unity Catalog volumes
- `uc_metric` - AI/BI metrics (first-class support)

**Other Platforms (when connectors are implemented):**
- `snowflake_table`, `snowflake_view`, `snowflake_stream`
- `kafka_topic`, `kafka_schema`
- `powerbi_dataset`, `powerbi_semantic_model`, `powerbi_dashboard`

**Benefits of Unified Asset Types:**
- Platform-agnostic governance policies
- Consistent metadata model across systems
- Simplified search and discovery
- Future-proof for new platform integrations

Instances can span multiple systems within the same dataset, enabling cross-platform data governance.

### Linking to Data Contracts

Connect your dataset to a formal specification:

#### Method 1: From Dataset Details

1. Open dataset details
2. Click **Edit** on the dataset
3. Select a **Data Contract** from the dropdown
4. Save

#### Method 2: From Instance Creation

1. Add a new instance
2. Select the **Contract Version** it implements
3. The instance is now linked to that contract version

#### Method 3: Create Contract from Dataset

1. Open dataset details
2. Click **Create Contract from Dataset** (if UC-backed)
3. Ontos infers schema from Unity Catalog
4. Enrich and submit for review
5. Contract is automatically linked

### Dataset Subscriptions

Users can subscribe to datasets for notifications:

**For Consumers**:
1. Open dataset details
2. Click **Subscribe**
3. Enter reason for subscription
4. Click **Subscribe**

**For Producers**:
- View subscribers in the **Subscribers** section
- Notify subscribers of changes
- Track adoption and usage

### Dataset Lifecycle

#### Draft

- Initial state after creation
- Add instances and metadata
- Private to team

#### Active

- Published for discovery
- Visible in marketplace
- Contract enforcement active

#### Deprecated

- Being phased out
- Show deprecation warnings
- Guide to replacement

#### Retired

- No longer available
- Archived for history
- Cannot be reactivated

### Publishing to Marketplace

Make your dataset discoverable:

1. Open dataset details (status must be Active)
2. Click **Publish** toggle
3. Dataset appears in Home → Marketplace
4. Consumers can discover and subscribe

**Requirements for Publishing**:
- Status must be "Active"
- Must have at least one physical instance
- Recommended: Link to a data contract

### Tags and Metadata

Enhance discoverability with rich metadata:

#### Tags
- Add tags for categorization
- Use consistent taxonomy
- Include data classification (pii, confidential)

#### Semantic Links
- Link to business concepts
- Enable semantic search
- Provide business context

#### Custom Properties
- Add domain-specific metadata
- Store operational information
- Track lineage information

### Dataset Best Practices

1. **Group Logically**: Include all related assets in one dataset (tables, views, metrics)
2. **Name Clearly**: Use descriptive, searchable names
3. **Document Well**: Add descriptions to dataset and instances
4. **Tag Consistently**: Use organization-wide tag taxonomy
5. **Assign Ownership**: Every dataset needs a responsible team
6. **Link Contracts**: Connect to contracts for quality governance
7. **Track Environments**: Register instances for each SDLC stage
8. **Keep Updated**: Remove retired instances, update paths when changed
9. **Specify Asset Types**: Always set the unified asset type for each instance
10. **Cross-Platform Consistency**: When an asset exists in multiple platforms, create instances for each with the appropriate asset type

---

## Creating Data Contracts

Data Contracts define formal specifications for data assets following the ODCS v3.1.0 standard.

### Why Data Contracts?

- **Consumer-Centric**: Define clear expectations for data consumers
- **Quality Guarantees**: Formalize data quality commitments (SLOs)
- **Breaking Change Prevention**: Contract versioning prevents unexpected changes
- **Semantic Clarity**: Link technical schemas to business concepts
- **Governance**: Enable approval workflows and compliance checks

### Contract Structure

A complete data contract includes:

1. **Metadata**: Name, version, owner, description
2. **Schema Objects**: Tables, views with their properties
3. **Properties**: Columns with types, constraints, and descriptions
4. **Service Level Objectives**: Availability, freshness, quality targets
5. **Authoritative Definitions**: Semantic links to business concepts
6. **Terms**: Usage restrictions, privacy requirements

### Creating a Contract

Navigate to **Contracts** and click **Create Contract**.

#### Basic Information

- **Name**: Unique contract identifier (e.g., "customer-data-contract")
- **Version**: Semantic version (e.g., "1.0.0")
- **Owner Team**: Responsible team
- **Domain**: Business domain
- **Status**: Draft (initial state)
- **Description**:
  - **Purpose**: What data and why
  - **Usage**: How consumers should use it
  - **Limitations**: Constraints and restrictions

#### Adding Schema Objects

1. Click **Add Schema Object**
2. Enter details:
   - **Name**: Logical name (e.g., "customers")
   - **Physical Name**: Actual UC table (e.g., "main.customer_domain.customers_v2")
   - **Description**: What the schema represents
   - **Type**: Table, View, Model, etc.

3. Add **Authoritative Definitions** (optional but recommended):
   - Click **Add Semantic Link**
   - Search for a business concept (e.g., "Customer")
   - Select the concept to link

#### Adding Properties (Columns)

For each schema object:

1. Click **Add Property**
2. Fill in details:
   - **Name**: Column name (e.g., "customer_id")
   - **Logical Type**: String, Integer, Date, etc.
   - **Required**: Is this field mandatory?
   - **Unique**: Must values be unique?
   - **Description**: What this field contains
   - **PII**: Does it contain personally identifiable information?

3. Add **Authoritative Definition** for the property:
   - Search for a business property (e.g., "customerId")
   - Link to provide semantic meaning

#### Example Contract Structure

```yaml
Name: Customer Data Contract
Version: 1.0.0
Owner Team: data-engineering
Domain: Customer
Status: draft

Description:
  Purpose: Core customer master data for enterprise applications
  Usage: Customer profiles, preferences, and transaction history
  Limitations: PII encrypted at rest; 7-year retention policy

Schema Objects:
  1. customers (table)
     Physical: main.customer_domain.customers_v2
     Semantic: → Business Concept "Customer"
     
     Properties:
       - customer_id (string, required, unique)
         Semantic: → Business Property "customerId"
       
       - email (string, required, unique, PII)
         Semantic: → Business Property "email"
       
       - first_name (string, required)
         Semantic: → Business Property "firstName"
       
       - last_name (string, required)
         Semantic: → Business Property "lastName"
       
       - date_of_birth (date, optional, PII)
         Semantic: → Business Property "dateOfBirth"

Service Level Objectives:
  - Availability: 99.9%
  - Freshness: Updated daily by 6 AM UTC
  - Completeness: >99% for required fields
  - Accuracy: <0.1% invalid emails
```

### Semantic Linking (Three-Tier System)

Ontos supports semantic linking at three levels:

#### 1. Contract-Level Links

Link the entire contract to a business domain concept.

**Example**: "Customer Data Contract" → "CustomerDomain" business concept

**When to Use**: High-level domain classification

#### 2. Schema-Level Links

Link schema objects (tables, views) to specific business entities.

**Example**: "customers" table → "Customer" business concept

**When to Use**: The schema represents a specific business entity

#### 3. Property-Level Links

Link individual columns to business properties.

**Example**: "email" column → "email" business property

**When to Use**: Every important data element (recommended for all columns)

**Benefits**:
- Enables semantic search ("find all tables with customer email")
- Provides business glossary integration
- Supports data lineage and impact analysis
- Facilitates cross-domain data discovery

### Contract Lifecycle

#### 1. Draft

- **Who**: Data Product Owner, Data Engineer
- **Actions**: Create and iterate on contract definition
- **Visibility**: Private to team

#### 2. Proposed

- **Who**: Data Product Owner
- **Actions**: Submit for review
- **Visibility**: Visible to assigned Data Stewards

**How to Submit for Review**:

**Option 1: Quick Submit**:
1. Open contract details (status must be Draft)
2. Click **Submit for Review** button
3. Contract transitions to Proposed status
4. Data Stewards are notified

**Option 2: Full Review Request** (recommended):
1. Open contract details (status must be Draft)
2. Click **Request...** button
3. Select **Request Data Steward Review** from the dropdown
4. Add optional message for the reviewer
5. Click **Send Request**
6. Creates formal review workflow with notifications and tracking

#### 3. Under Review

- **Who**: Data Steward
- **Actions**: Review contract for:
  - Schema completeness and clarity
  - Semantic alignment to business concepts
  - Compliance with data standards
  - Security and privacy requirements
  - SLO feasibility

**Review Criteria**:
- ✓ Clear descriptions for all fields
- ✓ Appropriate semantic links
- ✓ PII fields identified and protected
- ✓ Naming conventions followed
- ✓ Realistic SLOs defined

#### 4. Approved

- **Who**: Data Steward
- **Actions**: Approve or request changes
- **Visibility**: Organization-wide (metadata)

**What Happens**:
- Contract is officially approved
- Teams can begin implementation
- Contract can be deployed to Unity Catalog

#### 5. Active

- **Who**: Data Product Owner
- **Actions**: Deploy to production, monitor SLOs
- **Visibility**: Public in catalog

**Deployment**:
1. Click **Deploy Contract**
2. Select target catalog and schema (governed by deployment policy)
3. Review deployment preview
4. Submit deployment request (if approval required)
5. Admin approves deployment
6. Contract is deployed to Unity Catalog

**Production Operations**:
- Monitor SLO compliance
- Track data quality metrics
- Handle consumer feedback
- Maintain documentation

#### 6. Certified

- **Who**: Data Steward or Quality Assurance
- **Actions**: Certify contract for high-value or regulated use cases
- **Visibility**: Public with certification badge

**What is Certification**:
- Additional quality verification beyond standard approval
- Indicates contract meets elevated standards
- Required for sensitive data or critical applications
- Optional step for standard contracts

**Certification Criteria**:
- All SLOs consistently met for 30+ days
- Complete documentation
- No outstanding data quality issues
- Security requirements verified
- Consumer feedback is positive

#### 7. Deprecated

- **Who**: Data Product Owner
- **Actions**: Mark as deprecated, set sunset date
- **Visibility**: Public with deprecation warning

**When to Deprecate**:
- Replaced by newer version
- Business requirements changed
- Data source no longer available

**Deprecation Process**:
1. Announce deprecation with timeline (90 days recommended)
2. Update status to Deprecated
3. Communicate replacement contract
4. Support consumer migration
5. Monitor usage decline
6. Transition to Retired when no longer in use

#### 8. Retired

- **Who**: Data Product Owner or Admin
- **Actions**: Archive contract, maintain historical record
- **Visibility**: Archive only (not visible in active catalogs)

**Terminal State**: Retired is the final state. Contracts cannot transition out of Retired status.

**What Happens**:
- Contract metadata preserved for audit trail
- No longer available for new implementations
- Historical data access may be maintained
- Documentation kept for compliance purposes

**When to Retire**:
- All consumers have migrated to replacement
- Grace period after deprecation has elapsed
- Data source has been decommissioned

### Versioning Contracts

When making breaking changes:

1. Open contract details
2. Click **Create New Version**
3. Increment version (e.g., 1.0.0 → 2.0.0)
4. Make changes
5. Save as new contract
6. Go through approval workflow
7. Deprecate old version after migration

**Semantic Versioning**:
- **Major (X.0.0)**: Breaking changes (removed fields, type changes)
- **Minor (1.X.0)**: Backward-compatible additions (new optional fields)
- **Patch (1.0.X)**: Bug fixes, documentation updates

### Exporting and Importing Contracts

#### Export to ODCS YAML

1. Open contract details
2. Click **Export**
3. Select format: ODCS YAML
4. Download file

**Use Cases**:
- Share with external systems
- Version control in Git
- Documentation generation
- Compliance reporting

#### Import from ODCS YAML

1. Navigate to **Contracts**
2. Click **Import**
3. Upload ODCS YAML file
4. Review parsed contract
5. Click **Import**

**What's Preserved**:
- Schema structure
- Semantic links (authoritative definitions)
- SLOs and terms
- Metadata and descriptions

---

## Building Data Products

Data Products are curated collections of Databricks assets delivered as consumable products.

### What is a Data Product?

A Data Product is:
- A **product**, not just data
- Owned by a specific team
- Implements one or more data contracts
- Discoverable and self-service
- Monitored for quality and availability

### Product Types

#### 1. Source Products

Raw data ingested from operational systems.

**Example**: "POS Transaction Stream" from retail store systems

**Characteristics**:
- No input ports (system is the source)
- Single output port
- Minimal transformation
- Real-time or batch ingestion

#### 2. Source-Aligned Products

Prepared data optimized for analytics from a single source.

**Example**: "Prepared Sales Transactions" cleaned and validated from POS data

**Characteristics**:
- One input port (from source product)
- One or more output ports
- Data cleaning and standardization
- Implements quality rules

#### 3. Aggregate Products

Combined data from multiple sources for specific analytical purposes.

**Example**: "Customer 360 View" combining CRM, transactions, and support data

**Characteristics**:
- Multiple input ports
- Complex transformations
- Business logic and calculations
- Rich output datasets

#### 4. Consumer-Aligned Products

Purpose-built products for specific consumer needs.

**Example**: "Marketing Campaign Performance Dashboard"

**Characteristics**:
- Optimized for specific use case
- Aggregated and filtered
- Ready for direct consumption
- May include visualizations

### Creating a Data Product

Navigate to **Products** and click **Create Product**.

#### Basic Information

- **Name**: Unique identifier (e.g., "customer-360-view")
- **Title**: Display name (e.g., "Customer 360 View")
- **Version**: Semantic version (e.g., "1.0.0")
- **Product Type**: Source, Source-Aligned, Aggregate, or Consumer-Aligned
- **Owner Team**: Responsible team
- **Domain**: Business domain
- **Status**: Development (initial state)
- **Description**: Product purpose and value proposition

#### Linking to Contracts

Products implement data contracts:

1. Click **Link Contract**
2. Search for and select a contract
3. Specify which schema objects this product implements
4. Click **Link**

**Recommended Approach**: Create contracts first, then build products to implement them.

#### Defining Input Ports

Input ports define where data comes from:

1. Click **Add Input Port**
2. Fill in details:
   - **Name**: Descriptive name
   - **Description**: What data flows in
   - **Source Type**: Data Product, Table, External API, etc.
   - **Source ID**: Reference to source (another product, UC table, etc.)
   - **Tags**: Categorization tags

3. Click **Add**

#### Defining Output Ports

Output ports define what data this product provides:

1. Click **Add Output Port**
2. Fill in details:
   - **Name**: Port identifier
   - **Description**: What data is available
   - **Type**: Table, View, Volume, API, etc.
   - **Status**: Active, Deprecated
   - **Server Details**:
     - Location: UC path or URL
     - Format: Delta, Parquet, JSON, etc.
   - **Contains PII**: Flag for privacy
   - **Tags**: Categorization

3. Click **Add**

#### Example Data Product

```yaml
Name: customer-360-view
Title: Customer 360 View
Version: 2.1.0
Type: Aggregate
Owner Team: analytics-team
Domain: Customer
Status: active

Description: Comprehensive customer profile combining CRM data, 
  transaction history, support tickets, and marketing interactions.

Implements Contracts:
  - customer-data-contract (v1.0.0)
  - transaction-data-contract (v2.0.0)

Input Ports:
  1. crm-data-input
     Source: customer-master-data product
     Type: data-product
  
  2. transaction-history-input
     Source: main.sales.transactions
     Type: table

Output Ports:
  1. customer_360_enriched
     Type: table
     Location: main.analytics.customer_360_v2
     Format: Delta
     Contains PII: true
     Status: active
     
  2. customer_360_api
     Type: rest-api
     Location: https://api.company.com/v2/customers
     Status: active

Tags:
  - customer
  - analytics
  - aggregate
  - 360-view
  - pii

Links:
  documentation: https://docs.company.com/products/customer-360
  dashboard: https://analytics.company.com/customer-360
  support: #customer-360-support
```

### Product Lifecycle

Data Products follow a structured lifecycle aligned with Data Contracts (ODPS aligned with ODCS standard).

#### Complete Lifecycle Flow

```text
Draft → [Sandbox] → Proposed → Under Review → Approved → Active → Certified → Deprecated → Retired
```

**Key Points**:
- Sandbox is optional for testing before review
- Same governance workflow as Data Contracts (Proposed → Under Review → Approved)
- Certified is an elevated status after Active (not a prerequisite)
- Retired is terminal

#### 1. Draft

- **Who**: Data Product Owner, Data Engineers
- **Actions**: Initial product creation and design
- **Visibility**: Private to team

**Activities**:
- Define product structure
- Link to data contracts (optional at this stage)
- Add input/output ports
- Set basic metadata

**How to Create**:
1. Navigate to **Products** → **Create Product**
2. Or click **Create Data Product** from a contract details page

#### 2. Sandbox (Optional)

- **Who**: Data Engineers
- **Actions**: Build and test product implementation
- **Visibility**: Team + selected testers

**Activities**:
- Build data pipelines
- Implement contract specifications
- Link contracts to output ports
- Write tests
- Document usage
- Deploy to sandbox environment

**How to Move to Sandbox**:
1. Open product details (status must be Draft)
2. Click **Move to Sandbox** button
3. Product transitions to Sandbox status

**Key Requirement**: Each output port should have a data contract assigned via the `dataContractId` field.

**Note**: You can skip Sandbox and submit directly from Draft for review.

#### 3. Proposed

- **Who**: Data Product Owner
- **Actions**: Submit for review
- **Visibility**: Visible to assigned Data Stewards

**How to Submit for Review**:

**Option 1: Quick Submit**:
1. Open product details (status must be Draft or Sandbox)
2. Click **Submit for Review** button
3. Product transitions to Proposed status

**Option 2: Full Review Request** (recommended):
1. Open product details (status must be Draft or Sandbox)
2. Click **Request...** button
3. Select **Request Data Steward Review** from the dropdown
4. Add optional message for the reviewer
5. Click **Send Request**
6. Creates formal review workflow with notifications and tracking

#### 4. Under Review

- **Who**: Data Steward
- **Actions**: Review product implementation and documentation
- **Visibility**: Visible to Data Stewards and owner

**What Happens**:
- Product is being actively reviewed by Data Steward
- Review workflow is in progress
- Team waits for approval or rejection

**Review Criteria**:
- ✓ All output ports have approved contracts linked
- ✓ Implements contract specifications correctly
- ✓ Passes data quality checks
- ✓ Has complete documentation
- ✓ Security requirements met (PII handling, encryption)
- ✓ Lineage is documented
- ✓ Monitoring is in place
- ✓ SLOs are achievable

#### 5. Approved

- **Who**: Data Steward (completes approval)
- **Actions**: Product approved by governance, ready to publish
- **Visibility**: Organization-wide (metadata visible)

**Approval Actions**:
1. Data Steward opens product details
2. Reviews implementation and documentation
3. Clicks **Approve** button
4. Product transitions to Approved status

**If Rejected**:
- Data Steward clicks **Reject** button
- Product returns to Draft status for revisions
- Owner is notified with rejection reason

**Ready for Publication**:
- Product has been approved by governance
- All quality gates have passed
- Documentation is complete
- Ready to be made available to consumers

**Next Step**: Publish to make active

#### 6. Active (Published)

- **Who**: Data Product Owner
- **Actions**: Publish to marketplace, monitor operations
- **Visibility**: Public in catalog and marketplace

**How to Publish**:
1. Open product details (status must be Approved)
2. Click **Publish to Marketplace**
3. System validates:
   - Status is Approved
   - All output ports have `dataContractId` set
4. Product transitions to Active status

**What Happens**:
- Product appears in Discovery/Marketplace section
- Available for consumers to find and request access
- SLO monitoring begins
- Compliance tracking is enabled

**Production Operations**:
- Monitor data quality metrics
- Track SLO compliance
- Handle consumer support requests
- Respond to access requests
- Plan iterations and improvements
- Maintain linked contracts

#### 7. Certified

- **Who**: Data Steward or Quality Assurance
- **Actions**: Certify product for high-value or regulated use cases
- **Visibility**: Public with certification badge

**What is Certification**:
- Additional quality verification beyond standard approval
- Indicates product meets elevated standards
- Required for sensitive data or critical applications
- Optional step for standard products

**How to Certify**:
1. Data Steward opens product details (status must be Active)
2. Clicks **Certify** button
3. Product transitions to Certified status

**Certification Criteria**:
- All SLOs consistently met for 30+ days
- Complete documentation
- No outstanding data quality issues
- Security requirements verified
- Consumer feedback is positive

#### 8. Deprecated

- **Who**: Data Product Owner
- **Actions**: Mark as deprecated, communicate sunset
- **Visibility**: Public with deprecation warning

**When to Deprecate**:
- Replaced by newer version
- Business requirements changed
- Data source no longer available

**How to Deprecate**:
1. Open product details (status must be Active or Certified)
2. Click **Deprecate**
3. Confirm deprecation
4. Product transitions to Deprecated status

**Deprecation Process**:
1. Announce deprecation with timeline (90 days recommended)
2. Communicate replacement product
3. Support consumer migration
4. Monitor usage decline
5. Transition to Retired when no longer in use

#### 9. Retired

- **Who**: Data Product Owner or Admin
- **Actions**: Archive product, maintain historical record
- **Visibility**: Archive only (not visible in active catalogs)

**Terminal State**: Retired is the final state. Products cannot transition out of Retired status.

**What Happens**:
- Product metadata preserved for audit trail
- No longer available for new implementations
- Historical data access may be maintained
- Documentation kept for compliance purposes

**When to Retire**:
- All consumers have migrated to replacement
- Grace period after deprecation has elapsed
- Data source has been decommissioned

### Tagging Products

Tags enable discovery and organization:

**Standard Tags**:
- **Domain Tags**: finance, sales, customer
- **Type Tags**: source, aggregate, realtime
- **Quality Tags**: certified, tested, experimental
- **Data Classification**: pii, confidential, public
- **Technology Tags**: kafka, delta, python

**Best Practices**:
- Use consistent tag taxonomy
- Apply multiple relevant tags
- Include version tags (v1, v2)
- Tag by consumer persona (analyst-friendly, ml-ready)

---

## Semantic Models

Semantic Models provide a knowledge graph that connects technical data assets to business concepts.

### What are Semantic Models?

Semantic Models define:
- **Business Concepts**: High-level domain entities (Customer, Product, Order)
- **Business Properties**: Specific data elements (email, firstName, productId)
- **Relationships**: How concepts relate to each other
- **Hierarchies**: Taxonomies and categorizations

### Viewing Semantic Models

Navigate to **Semantic Models** in the sidebar.

**What You'll See**:
- List of business concepts
- List of business properties
- Concept details (definition, examples, relationships)
- Property details (data type, format, constraints)

### Using Semantic Models

#### Linking Contracts to Concepts

When creating a data contract:

1. At **Contract Level**: Link to high-level domain concept
   - Example: "Customer Data Contract" → "CustomerDomain"

2. At **Schema Level**: Link table to specific entity
   - Example: "customers" table → "Customer" concept

3. At **Property Level**: Link column to business property
   - Example: "email" column → "email" property

#### Benefits of Semantic Linking

1. **Discovery**: Find all tables containing "customer email"
2. **Consistency**: Ensure "email" field has same format everywhere
3. **Documentation**: Auto-generate business glossary
4. **Lineage**: Track business concepts through transformations
5. **Compliance**: Check policies based on semantic meaning

### Semantic Search

Use the search bar to find assets by business concept:

**Examples**:
- Search "customer" → Find all assets linked to Customer concept
- Search "email" → Find all columns representing email addresses
- Search "PII" → Find all assets containing personal information

### Exploring Concept Relationships

Click on a concept to see:
- **Definition**: What this concept means
- **Properties**: Which business properties belong to this concept
- **Related Concepts**: Parent/child and associated concepts
- **Linked Assets**: Which contracts, schemas, and tables use this concept

### Custom Semantic Models

To add custom business concepts and properties:

1. Create RDF/RDFS files defining your concepts
2. Place files in `/src/backend/src/data/taxonomies/`
3. Restart the application
4. Concepts will be available in the semantic linking dialogs

**RDF Format Example**:

```turtle
@prefix ontos: <http://example.com/ontology#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ontos:Subscription a rdfs:Class ;
    rdfs:label "Subscription" ;
    rdfs:comment "Customer subscription to a service or product" ;
    rdfs:subClassOf ontos:BusinessConcept .

ontos:subscriptionId a rdf:Property ;
    rdfs:label "Subscription ID" ;
    rdfs:comment "Unique identifier for a subscription" ;
    rdfs:domain ontos:Subscription ;
    rdfs:range xsd:string .
```

---

## Compliance Checks

Compliance Policies automate governance by checking data assets against defined rules.

### Compliance DSL

The Compliance Domain-Specific Language (DSL) enables you to write declarative rules similar to SQL.

#### DSL Structure

```text
MATCH (entity:Type)
WHERE filter_condition
ASSERT compliance_condition
ON_PASS action
ON_FAIL action
```

**Components**:
- **MATCH**: Which entities to check
- **WHERE**: Filter entities (optional)
- **ASSERT**: The compliance rule to verify
- **ON_PASS**: Actions when rule passes
- **ON_FAIL**: Actions when rule fails

### Supported Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `=` | Equality | `obj.status = 'active'` |
| `!=` | Not equal | `obj.owner != 'unknown'` |
| `>`, `<`, `>=`, `<=` | Comparison | `obj.score >= 95` |
| `MATCHES` | Regex match | `obj.name MATCHES '^[a-z_]+$'` |
| `IN` | List membership | `obj.type IN ['table', 'view']` |
| `CONTAINS` | Substring | `obj.description CONTAINS 'PII'` |
| `AND`, `OR`, `NOT` | Boolean logic | `obj.active AND NOT obj.deprecated` |

### Built-in Functions

| Function | Description | Example |
|----------|-------------|---------|
| `HAS_TAG(key)` | Check tag exists | `HAS_TAG('data-product')` |
| `TAG(key)` | Get tag value | `TAG('domain') = 'finance'` |
| `LENGTH(str)` | String length | `LENGTH(obj.name) <= 64` |
| `UPPER(str)` | To uppercase | `UPPER(obj.name)` |
| `LOWER(str)` | To lowercase | `LOWER(obj.name) = obj.name` |

### Available Actions

| Action | Syntax | Description |
|--------|--------|-------------|
| `PASS` | `PASS` | Mark as passed (default) |
| `FAIL` | `FAIL 'message'` | Mark as failed with message |
| `ASSIGN_TAG` | `ASSIGN_TAG key: 'value'` | Add/update tag |
| `REMOVE_TAG` | `REMOVE_TAG key` | Remove tag |
| `NOTIFY` | `NOTIFY 'email@company.com'` | Send notification |

### Entity Types

You can write rules for:

**Unity Catalog Objects**:
- `catalog` - Catalogs
- `schema` - Schemas
- `table` - Tables
- `view` - Views
- `function` - Functions
- `volume` - Volumes
- `model` - Registered ML models
- `metric` - Unity Catalog metrics (AI/BI)

**Cross-Platform Objects** (when connectors available):
- `topic` - Kafka topics
- `stream` - Snowflake streams
- `dashboard` - Power BI dashboards
- `semantic_model` - Power BI semantic models

**Application Entities**:
- `data_product` - Data products
- `data_contract` - Data contracts
- `dataset` - Datasets
- `dataset_instance` - Dataset instances (with `asset_type` filtering)
- `domain` - Domains
- `glossary_term` - Glossary terms
- `review` - Review requests

**Generic**:
- `Object` - Matches all entity types

### Example Policies

#### Policy 1: Naming Conventions

**Requirement**: All tables use lowercase_snake_case; views must start with `v_`

```text
MATCH (obj:Object)
WHERE obj.type IN ['table', 'view']
ASSERT
  CASE obj.type
    WHEN 'view' THEN obj.name MATCHES '^v_[a-z][a-z0-9_]*$'
    WHEN 'table' THEN obj.name MATCHES '^[a-z][a-z0-9_]*$'
  END
ON_FAIL FAIL 'Names must be lowercase_snake_case. Views must start with "v_"'
ON_FAIL ASSIGN_TAG compliance_issue: 'naming_violation'
```

**Test Cases**:
- ✅ `customer_orders` (table)
- ✅ `v_active_customers` (view)
- ❌ `CustomerOrders` (table - uppercase)
- ❌ `orders_view` (view - missing `v_` prefix)

#### Policy 2: PII Data Protection

**Requirement**: All PII data must be encrypted with AES256

```text
MATCH (tbl:table)
WHERE HAS_TAG('contains_pii') AND TAG('contains_pii') = 'true'
ASSERT TAG('encryption') = 'AES256'
ON_FAIL FAIL 'PII data must be encrypted with AES256'
ON_FAIL ASSIGN_TAG security_risk: 'high'
ON_FAIL NOTIFY 'security-team@company.com'
ON_PASS ASSIGN_TAG last_compliance_check: '2025-01-15'
```

**What it checks**:
- Tables tagged with `contains_pii: true`
- Must have `encryption: AES256` tag
- On failure: tags as high risk and alerts security team
- On success: updates last check timestamp

#### Policy 3: Data Product Ownership

**Requirement**: All active data products must have a valid owner

```text
MATCH (prod:data_product)
WHERE prod.status IN ['active', 'certified']
ASSERT prod.owner != 'unknown' AND LENGTH(prod.owner) > 0
ON_FAIL FAIL 'Active data products must have a valid owner assigned'
ON_FAIL ASSIGN_TAG needs_attention: 'missing_owner'
ON_FAIL NOTIFY 'data-governance@company.com'
ON_PASS REMOVE_TAG needs_attention
```

#### Policy 4: Production Asset Tagging

**Requirement**: All production assets must be tagged with a data product

```text
MATCH (obj:Object)
WHERE obj.type IN ['table', 'view'] AND obj.catalog = 'prod'
ASSERT HAS_TAG('data-product') OR HAS_TAG('excluded-from-products')
ON_FAIL FAIL 'All production assets must be tagged with a data product or marked as excluded'
ON_FAIL ASSIGN_TAG compliance_status: 'untagged'
ON_PASS REMOVE_TAG compliance_status
```

#### Policy 5: Schema Documentation

**Requirement**: All schemas must have meaningful descriptions

```text
MATCH (sch:schema)
WHERE sch.catalog != 'temp'
ASSERT
  sch.comment != '' AND
  LENGTH(sch.comment) >= 20
ON_FAIL FAIL 'Schemas must have a description of at least 20 characters'
ON_FAIL ASSIGN_TAG documentation_status: 'incomplete'
ON_FAIL NOTIFY 'data-documentation-team@company.com'
ON_PASS ASSIGN_TAG documentation_status: 'complete'
```

### Creating a Compliance Policy

Navigate to **Compliance** and click **Create Policy**.

1. **Basic Information**:
   - **Name**: Descriptive name
   - **Description**: What the policy enforces
   - **Severity**: Critical, High, Medium, Low
   - **Category**: Governance, Security, Quality, etc.
   - **Active**: Enable/disable the policy

2. **Write Rule**: Enter your DSL rule in the editor

3. **Add Examples** (optional but recommended):
   - Passing examples
   - Failing examples
   - Help users understand the rule

4. Click **Save**

### Running Compliance Checks

#### On-Demand Run

1. Open policy details
2. Click **Run Policy**
3. Optionally set a limit for testing (e.g., 100 assets)
4. Click **Run**
5. Wait for results

**Results Include**:
- Total assets checked
- Passed vs. failed count
- Compliance score percentage
- Detailed results per asset
- Applied actions (tags, notifications)

#### Scheduled Runs

Configure policies to run automatically:

1. Open policy details
2. Click **Schedule**
3. Set frequency: Hourly, Daily, Weekly
4. Set time and timezone
5. Click **Save Schedule**

**Best Practices**:
- Run critical policies daily
- Run expensive policies weekly
- Start with manual runs to validate

### Reviewing Compliance Results

Navigate to **Compliance → Runs** to see all runs.

#### Run Details

Click on a run to see:
- **Summary**: Pass/fail counts, score, duration
- **Results Table**: Each asset checked with pass/fail status
- **Failure Details**: Error messages for failed checks
- **Actions Taken**: Tags assigned, notifications sent
- **Historical Trend**: Score over time

#### Filtering Results

- **Status**: Show only failures or passes
- **Entity Type**: Filter by table, view, etc.
- **Severity**: Filter by policy severity

#### Exporting Results

1. Open run details
2. Click **Export**
3. Select format: CSV, JSON, PDF
4. Download report

**Use Cases**:
- Compliance reporting
- Remediation tracking
- Audit trails

### Compliance Best Practices

1. **Start Simple**: Begin with 3-5 high-priority policies
2. **Use WHERE Efficiently**: Filter before checking to improve performance
3. **Provide Clear Messages**: Users need actionable feedback
4. **Tag for Tracking**: Use tags to monitor compliance over time
5. **Notify Sparingly**: Avoid alert fatigue; only notify on critical violations
6. **Test First**: Run with limits to validate rules before full deployment
7. **Document Examples**: Help users understand what passes and fails

---

## Process Workflows

Process Workflows enable automated, configurable multi-step processes that trigger on entity lifecycle events. They replace hardcoded business logic with flexible, user-editable flows that can be customized per organization.

### What are Process Workflows?

Process Workflows are:
- **Trigger-based**: Automatically fire when entities are created, updated, or when specific events occur
- **Multi-step**: Chain together validation, approval, notification, and other actions
- **Configurable**: Edit, duplicate, or create new workflows through the UI
- **Extensible**: Support custom scripts and compliance policy checks

### Use Cases

| Use Case | Description |
|----------|-------------|
| **Pre-creation validation** | Block table creation if naming conventions fail |
| **Approval workflows** | Require Data Steward approval before publishing products |
| **Access request handling** | Route access requests through configurable approval chains |
| **Automated tagging** | Auto-assign owner tags to new assets |
| **Notifications** | Alert subscribers when datasets change |
| **Compliance enforcement** | Run policy checks before creating assets |

### Workflow Components

#### Triggers

Triggers determine when a workflow fires. Available trigger types:

| Trigger Type | Description | Example Use Case |
|--------------|-------------|------------------|
| **On Create** | Fires when an entity is created | Validate naming conventions |
| **On Update** | Fires when an entity is updated | Notify subscribers of changes |
| **On Delete** | Fires when an entity is deleted | Archive audit trail |
| **On Status Change** | Fires when status transitions | Approve publish to production |
| **Scheduled** | Fires on a cron schedule | Daily compliance scans |
| **Manual** | Triggered by user action | On-demand data quality check |
| **Before Create** | Fires before entity creation (blocking) | Enforce naming policies |
| **Before Update** | Fires before entity update (blocking) | Validate schema changes |
| **Review Request** | Fires when review is requested | Route to Data Steward |
| **Access Request** | Fires when access is requested | Approval workflow for grants |
| **Publish Request** | Fires when publish is requested | Contract publish approval |
| **Status Change Request** | Fires when status change is requested | Deprecation approval |
| **Job Success** | Fires when a background job succeeds | Success notifications |
| **Job Failure** | Fires when a background job fails | Alert administrators |
| **Subscription** | Fires when user subscribes | Welcome notifications |
| **Unsubscription** | Fires when user unsubscribes | Feedback collection |
| **Expiring** | Fires when access is about to expire | Renewal reminders |
| **Access Revoked** | Fires when access is revoked | Revocation notifications |

#### Entity Types

Workflows can target specific entity types:

| Entity Type | Description |
|-------------|-------------|
| **Catalog** | Unity Catalog catalogs |
| **Schema** | Database schemas |
| **Table** | Tables (including Delta tables) |
| **View** | Database views |
| **Data Contract** | Data contract definitions |
| **Data Product** | Data product packages |
| **Dataset** | Dataset registrations |
| **Domain** | Data domains |
| **Project** | Team projects |
| **Access Grant** | Access grant records |
| **Role** | Application roles |
| **Asset Review** | Data asset review requests |
| **Job** | Background jobs |
| **Subscription** | Dataset subscriptions |

#### Workflow Steps

Steps are the building blocks of workflows:

| Step Type | Description | Configuration |
|-----------|-------------|---------------|
| **Validation** | Evaluate a compliance rule | Rule DSL expression |
| **Approval** | Request human approval | Approvers, timeout, require all |
| **Notification** | Send a notification | Recipients, template, message |
| **Assign Tag** | Add or update a tag | Key, value or value source |
| **Remove Tag** | Remove a tag | Key to remove |
| **Conditional** | Branch based on condition | Condition expression |
| **Script** | Execute custom logic | Script code |
| **Policy Check** | Run a compliance policy | Policy ID reference |
| **Delivery** | Trigger delivery service | Delivery mode configuration |
| **Pass** | End workflow successfully | Optional message |
| **Fail** | End workflow with failure | Error message |

### Viewing Workflows

Navigate to **Compliance → Workflows** to see all configured workflows:

- Workflow name and description
- Trigger type and entity types
- Number of steps
- Active/Inactive status
- Default badge (for built-in workflows)

### Creating a Workflow

1. Navigate to **Compliance → Workflows**
2. Click **Create Workflow**
3. Fill in basic information:
   - **Name**: Descriptive name
   - **Description**: What the workflow does
   - **Trigger Type**: When to fire
   - **Entity Types**: Which entities to target
   - **Active**: Enable/disable

4. Add workflow steps using the visual designer:
   - Drag and connect steps
   - Configure each step's settings
   - Define on_pass and on_fail transitions

5. Click **Save**

### Visual Workflow Designer

The workflow designer provides a visual canvas for building workflows:

- **Trigger Node**: Starting point showing trigger configuration
- **Step Nodes**: Colored by type (validation, approval, notification, etc.)
- **Connections**: Lines showing flow between steps
- **Properties Panel**: Configure selected node settings

#### Designer Tips

- Click a node to select and edit its properties
- Connect nodes by dragging from output to input handles
- Use the minimap for navigation in complex workflows
- Auto-layout organizes nodes automatically

### Default Workflows

Ontos includes pre-configured default workflows that cover common governance patterns. These can be edited or duplicated but not deleted.

#### Validation Workflows

| Workflow | Trigger | Description |
|----------|---------|-------------|
| **Naming Convention Validation** | On Create (catalog, schema, table) | Validates lowercase_snake_case naming |
| **Table Pre-Creation Validation** | Before Create (table) | Checks naming and reserved words |
| **Data Contract Schema Validation** | On Create (data_contract) | Ensures schema is defined |
| **Pre-Creation Compliance** | Before Create (catalog, schema, table) | Runs policy checks before creation (disabled by default) |

#### Approval Workflows

| Workflow | Trigger | Description |
|----------|---------|-------------|
| **Data Product Publish Approval** | On Status Change (data_product) | Requires domain owner approval for publishing |
| **Dataset Review Request** | Review Request (dataset) | Data Steward approval for datasets |
| **Data Contract Review Request** | Review Request (data_contract) | Data Steward approval for contracts |
| **Data Product Review Request** | Review Request (data_product) | Domain owner approval for products |
| **Data Contract Publish Request** | Publish Request (data_contract) | Contract approver authorization |
| **Access Grant Request** | Access Request (access_grant) | Admin approval for access |
| **Status Change Request** | Status Change Request (dataset, data_product) | Admin approval for status changes |
| **Role Access Request** | Access Request (role) | Admin approval for role assignments |

#### Notification Workflows

| Workflow | Trigger | Description |
|----------|---------|-------------|
| **Dataset Update Notification** | On Update (dataset) | Notifies subscribers of changes |
| **PII Detection and Classification** | On Create (table) | Detects and tags PII columns (disabled by default) |
| **Job Failure Notification** | Job Failure (job) | Alerts administrators |
| **Job Success Notification** | Job Success (job) | Notifies requester (disabled by default) |
| **Subscription Welcome** | Subscription (dataset) | Welcome message to subscribers (disabled by default) |
| **Access Expiring Warning** | Expiring (access_grant) | Warns users before access expires |
| **Access Revoked Notification** | Access Revoked (access_grant) | Notifies users of revocation |

### Editing a Default Workflow

Default workflows can be customized:

1. Navigate to **Compliance → Workflows**
2. Click on a default workflow
3. Click **Edit**
4. Modify steps, add new steps, or change configuration
5. Click **Save**

**Tip**: Use **Duplicate** to create a copy before making major changes.

### Duplicating a Workflow

Create a copy of any workflow:

1. Click the actions menu (⋮) on a workflow row
2. Select **Duplicate**
3. Enter a new name
4. Click **Duplicate**
5. Edit the copy as needed

### Workflow Execution

#### How Workflows Run

1. **Trigger Event**: An entity event matches a workflow's trigger
2. **Scope Check**: Workflow scope is evaluated (all, project, catalog, domain)
3. **Step Execution**: Steps run in sequence following on_pass/on_fail paths
4. **Result**: Workflow ends at a Pass or Fail terminal step

#### Blocking vs Non-Blocking

- **Blocking Workflows** (before_create, before_update): Prevent the action if workflow fails
- **Non-Blocking Workflows**: Run asynchronously; failures don't prevent the triggering action

#### Approval Pausing

Approval steps pause workflow execution:

1. Workflow reaches approval step
2. Notification sent to approvers
3. Workflow status becomes "Paused"
4. Approver makes decision via notification
5. Workflow resumes with on_pass or on_fail path

### Workflow Best Practices

#### Design Principles

1. **Keep It Simple**: Start with minimal steps; add complexity as needed
2. **Clear Naming**: Use descriptive names for workflows and steps
3. **Handle Failures**: Always define on_fail paths for important steps
4. **Notify Users**: Include notification steps for visibility
5. **Test First**: Disable new workflows and test before enabling

#### Common Patterns

**Validation → Auto-Fix → Notify Pattern**:
```yaml
Steps:
  1. Validate condition
     on_pass → success
     on_fail → auto-fix

  2. Auto-fix (assign_tag)
     on_pass → success
     on_fail → notify

  3. Notify (on failure)
     on_pass → fail

  4. Success (pass)
  5. Fail (fail)
```

**Request → Approve → Notify Pattern**:
```yaml
Steps:
  1. Notify requester (confirmation)
     on_pass → request-approval

  2. Request approval
     on_pass → notify-approved
     on_fail → notify-rejected

  3. Notify approved
     on_pass → success

  4. Notify rejected
     on_pass → fail

  5. Success (pass)
  6. Fail (fail)
```

#### Performance Considerations

- Avoid complex workflows on high-frequency triggers (on_update)
- Use scopes to limit workflow execution to relevant entities
- Disable unnecessary default workflows
- Monitor workflow execution times in logs

### Troubleshooting Workflows

#### Workflow Not Firing

1. Check workflow is **Active**
2. Verify trigger type matches the event
3. Check entity types include the affected entity
4. Verify scope includes the entity (project, catalog, domain)

#### Step Failing Unexpectedly

1. Check step configuration for typos
2. Verify validation rule syntax
3. Check approver roles/groups exist
4. Review backend logs for detailed errors

#### Approval Not Received

1. Verify approver role/group is configured correctly
2. Check notifications are not filtered/blocked
3. Ensure approvers have notification access

---

## Asset Review Workflow

The Asset Review feature enables Data Stewards to formally review and approve Databricks assets before they're promoted to production.

### What is Asset Review?

Asset Review is a governance workflow where:
- Data Producers request review of assets (tables, views, functions)
- Data Stewards examine asset definitions and data quality
- Stewards approve, reject, or request clarifications
- System tracks review history and decisions

### Creating a Review Request

**Who**: Data Producer or Data Engineer

1. Navigate to **Asset Reviews**
2. Click **Create Review Request**
3. Fill in the form:
   - **Reviewer**: Select a Data Steward
   - **Notes**: Explain what needs review and why
   
4. Add assets to review:
   - Click **Add Asset**
   - Enter fully qualified name (e.g., `main.sales.orders`)
   - Select asset type (table, view, function, model, volume, metric, dashboard, topic, etc.)
   - Repeat for all assets

5. Click **Submit Request**

**Example Request**:
```text
Reviewer: data.steward@company.com
Notes: Pre-production review for Q4 sales dashboard assets. 
       Please verify schema consistency and data quality.

Assets:
  1. main.staging.orders_cleaned (table)
  2. main.staging.v_orders_summary (view)
  3. main.staging.fn_calculate_revenue (function)
```

### Reviewing Assets

**Who**: Data Steward

Navigate to **Asset Reviews** to see pending requests.

#### Review Process

1. Click on a review request
2. For each asset:
   
   **a. View Definition**
   - Click **View Definition**
   - Review CREATE TABLE/VIEW statement
   - Check schema, constraints, comments
   
   **b. Preview Data** (for tables)
   - Click **Preview Data**
   - Examine sample rows (default: 25)
   - Check data quality and patterns
   
   **c. AI Analysis** (optional)
   - Click **Analyze with AI**
   - LLM reviews asset for issues
   - Get suggestions and warnings
   
   **d. Make Decision**
   - Select action: **Approve**, **Reject**, or **Needs Clarification**
   - Add comments explaining the decision
   - Click **Submit Decision**

3. Once all assets are reviewed, finalize the request:
   - Click **Complete Review**
   - Request status changes to **Approved**, **Rejected**, or **Needs Review**

#### AI-Assisted Review

The system can analyze asset definitions using AI:

**What AI Checks**:
- Schema design issues
- Missing comments/documentation
- Potential data quality problems
- Security concerns (e.g., unencrypted PII)
- Best practice violations

**How to Use**:
1. Click **Analyze with AI** on an asset
2. Wait for analysis (typically 10-30 seconds)
3. Review findings:
   - **Warnings**: Potential issues found
   - **Suggestions**: Improvements to consider
   - **Security**: Security-related concerns

4. Use findings to inform your decision

**Note**: AI analysis is a tool to assist, not replace, human judgment.

### Review Statuses

#### Request Statuses

- **Queued**: Newly created, awaiting review
- **In Review**: Steward is actively reviewing
- **Needs Review**: Requester must address concerns
- **Approved**: All assets approved, ready for promotion
- **Rejected**: Request rejected, assets cannot be promoted

#### Asset Statuses

- **Pending**: Awaiting review
- **Approved**: Asset passed review
- **Rejected**: Asset failed review
- **Needs Clarification**: Issues found, requester must respond

### Responding to Review Feedback

**Who**: Data Producer

If a review request returns with **Needs Review** status:

1. Open the review request
2. Read steward comments
3. Address issues:
   - Fix asset definitions
   - Improve data quality
   - Add missing documentation
   
4. Click **Resubmit for Review**
5. Add notes explaining changes
6. Steward will re-review

### Review History

All review decisions are tracked:

- **Audit Trail**: Who reviewed what and when
- **Comments**: Rationale for decisions
- **History**: Multiple review rounds for the same asset
- **Reporting**: Generate compliance reports

Navigate to **Audit Trail** to see detailed review history.

### Best Practices

**For Requesters**:
- Provide context in notes
- Ensure assets have documentation
- Run your own quality checks first
- Group related assets in one request
- Respond promptly to feedback

**For Reviewers**:
- Use the AI analysis as a starting point
- Check schema documentation
- Verify naming conventions
- Review data samples
- Provide specific, actionable feedback
- Explain rejection reasons clearly

---

## User Roles and Permissions

Ontos uses Role-Based Access Control (RBAC) to manage permissions.

### Default Roles

#### Admin

**Purpose**: Full system administration

**Permissions**:
- All features: Read/Write
- User management
- Role configuration
- System settings

**Who**: IT administrators, platform engineers

#### Data Governance Officer

**Purpose**: Broad governance oversight

**Permissions**:
- All governance features: Read/Write
- Compliance policies: Read/Write
- Asset reviews: Read/Write
- Cannot modify system settings

**Who**: Chief Data Officer, governance leads

#### Data Steward

**Purpose**: Review and approve data assets

**Permissions**:
- Data contracts: Read/Write (approval authority)
- Data products: Read/Write (certification authority)
- Asset reviews: Read/Write
- Compliance: Read Only
- Settings: No Access

**Who**: Domain data stewards, governance team members

#### Data Producer

**Purpose**: Create and manage data products

**Permissions**:
- Data contracts: Read/Write (own team only)
- Data products: Read/Write (own team only)
- Compliance: Read Only
- Asset reviews: Create requests only

**Who**: Data engineers, analytics engineers

#### Data Consumer

**Purpose**: Discover and use data products

**Permissions**:
- Data products: Read Only
- Data contracts: Read Only
- Semantic models: Read Only
- All other features: No Access

**Who**: Analysts, data scientists, business users

#### Security Officer

**Purpose**: Security and access control

**Permissions**:
- Entitlements: Read/Write
- Compliance (security policies): Read/Write
- Audit trail: Read Only
- Asset reviews (security): Read/Write

**Who**: Information security team

### Viewing Your Permissions

Click your profile icon (top right) → **My Profile** to see:
- Your assigned roles
- Groups you belong to
- Effective permissions
- Role overrides from team memberships

### Permission Levels

Each feature has permission levels:

- **No Access**: Feature not visible
- **Read Only**: View only, no modifications
- **Read/Write**: Full CRUD operations
- **Admin**: Full access including configuration

### Deployment Policies

Deployment policies control which Unity Catalog catalogs and schemas users can deploy to.

#### Viewing Your Deployment Policy

Navigate to **My Profile → Deployment Policy** to see:
- Allowed catalogs (list or patterns)
- Allowed schemas (list or patterns)
- Default catalog/schema
- Whether deployments require approval
- Whether you can approve others' deployments

#### Template Variables

Deployment policies support dynamic values:

| Variable | Description | Example |
|----------|-------------|---------|
| `{username}` | Email prefix | `jdoe` from `jdoe@company.com` |
| `{email}` | Full email | `jdoe@company.com` |
| `{team}` | Primary team | `data-engineering` |
| `{domain}` | User's domain | `Finance` |

**Example Policy**:
```json
{
  "allowed_catalogs": [
    "{username}_sandbox",
    "shared_dev",
    "staging"
  ],
  "allowed_schemas": ["*"],
  "default_catalog": "{username}_sandbox",
  "default_schema": "default"
}
```

For user `alice@company.com`, this resolves to:
- Allowed: `alice_sandbox`, `shared_dev`, `staging`
- Default: `alice_sandbox.default`

#### Pattern Matching

Policies support wildcards and regex:

**Wildcards**:
- `*` - Match anything
- `user_*` - Match `user_alice`, `user_bob`, etc.
- `*_sandbox` - Match `alice_sandbox`, `team_sandbox`, etc.

**Regex** (surround with `^` and `$`):
- `^prod_.*$` - Match catalogs starting with `prod_`
- `^[a-z]+_sandbox$` - Match lowercase names ending with `_sandbox`

### Team Role Overrides

Users can have different roles in different teams:

**Example**:
- Global role: **Data Consumer**
- In "analytics-team": **Data Producer** (override)
- In "finance-domain-team": **Data Steward** (override)

This allows flexible, context-specific permissions.

---

## MCP Integration (AI Assistants)

Ontos provides a **Model Context Protocol (MCP)** server that enables AI assistants (like Claude, GPT, or custom LLM agents) to programmatically discover and execute tools within your data governance platform.

### What is MCP?

The **Model Context Protocol** is a standard for AI assistants to interact with external systems. It allows:

- **Tool Discovery**: AI assistants can discover what operations are available
- **Secure Execution**: Tools are executed with scope-based authorization
- **Programmatic Access**: Automate data governance workflows via AI

### Use Cases

| Use Case | Description |
|----------|-------------|
| **AI-Powered Search** | Ask "Find all data products related to customer analytics" |
| **Automated Documentation** | Generate contract documentation from natural language |
| **Governance Chatbot** | Answer questions about data lineage and ownership |
| **Compliance Queries** | Check compliance status across domains |
| **Semantic Discovery** | Find entities by business concept (e.g., "all tables with customer email") |

### MCP Tokens

MCP tokens are API keys that authenticate AI assistants to the MCP endpoint. Each token has:

- **Name**: Descriptive identifier
- **Scopes**: Permissions granted (what tools can be used)
- **Expiration**: Optional time limit
- **Audit Trail**: Last used timestamp and creation info

#### Creating an MCP Token

**Who**: Administrators

1. Navigate to **Settings → MCP Tokens**
2. Click **Create Token**
3. Fill in the form:
   - **Name**: Descriptive name (e.g., "Claude Assistant - Analytics Team")
   - **Description**: Purpose of this token
   - **Scopes**: Select required permissions (see [Available Scopes](#available-scopes))
   - **Expiration**: Optional expiry time

4. Click **Create**
5. **IMPORTANT**: Copy the generated token immediately. It will only be shown once.

**Example Token Configuration**:
```yaml
Name: claude-assistant-analytics
Description: Claude assistant for analytics team queries
Scopes:
  - data-products:read
  - contracts:read
  - semantic:read
  - search:read
Expiration: 90 days
```

#### Managing Tokens

**View Tokens**: Navigate to **Settings → MCP Tokens** to see all tokens with:
- Name and description
- Scopes granted
- Created by and when
- Last used timestamp
- Expiration status

**Revoke Token**: Click **Revoke** to immediately disable a token. Revoked tokens cannot be restored.

**Delete Token**: Permanently remove a token and its audit history.

### Available Scopes

Scopes control which tools an MCP token can access. Use the principle of least privilege.

#### Read Scopes

| Scope | Tools Available |
|-------|-----------------|
| `data-products:read` | Search, get, list data products |
| `contracts:read` | Search, get, list data contracts |
| `domains:read` | Search, get domains |
| `teams:read` | Search, get teams |
| `projects:read` | Search, get projects |
| `tags:read` | Search tags, list entity tags |
| `semantic:read` | Search glossary terms, list semantic links, find entities by concept |
| `analytics:read` | Get table schemas, explore catalogs, execute read-only queries |
| `costs:read` | Get data product cost information |
| `search:read` | Global search across all entities |

#### Write Scopes

| Scope | Tools Available |
|-------|-----------------|
| `data-products:write` | Create, update, delete data products |
| `contracts:write` | Create, update, delete data contracts |
| `domains:write` | Create, update, delete domains |
| `teams:write` | Create, update, delete teams |
| `projects:write` | Create, update, delete projects |
| `tags:write` | Create, update, delete tags; assign/remove tags from entities |
| `semantic:write` | Add/remove semantic links |

#### Special Scopes

| Scope | Description |
|-------|-------------|
| `sparql:query` | Execute SPARQL queries against the semantic model graph |
| `*` | Full access to all tools (admin only) |

#### Wildcard Scopes

Use wildcards for broader access:

- `data-products:*` → Both read and write for data products
- `*:read` → Read access to all entities
- `*` → Full access (use sparingly)

### Using the MCP Endpoint

The MCP endpoint uses JSON-RPC 2.0 over HTTP.

#### Endpoint URL

```text
POST /mcp
```

> The server is also mounted at the legacy path `/api/mcp`, which continues to
> work for existing clients. New integrations should use `/mcp`.
>
> **On-behalf-of (OBO):** when the MCP server is reached through the Ontos app
> proxy (native integration), tools that read Unity Catalog run **as the calling
> user**, scoped to that user's grants. External agents calling with only an
> `X-API-Key` (no forwarded user identity) run as the app service principal, as
> before.

#### Authentication

Include your MCP token in the `X-API-Key` header:

```bash
curl -X POST https://your-ontos-instance/mcp \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-mcp-token-here" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
```

#### Available Methods

| Method | Description |
|--------|-------------|
| `initialize` | Initialize MCP session |
| `ping` | Health check |
| `tools/list` | List available tools (filtered by token scopes) |
| `tools/call` | Execute a specific tool |

### Tool Discovery

Use `tools/list` to discover available tools:

**Request**:
```json
{
  "jsonrpc": "2.0",
  "method": "tools/list",
  "id": 1
}
```

**Response**:
```json
{
  "jsonrpc": "2.0",
  "result": {
    "tools": [
      {
        "name": "search_data_products",
        "description": "Search for data products by name, description, or tags",
        "inputSchema": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "Search query string"
            }
          },
          "required": ["query"]
        }
      },
      ...
    ]
  },
  "id": 1
}
```

**Note**: Only tools matching your token's scopes are returned.

### Executing Tools

Use `tools/call` to execute a tool:

**Request**:
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "search_data_products",
    "arguments": {
      "query": "customer analytics"
    }
  },
  "id": 2
}
```

**Response**:
```json
{
  "jsonrpc": "2.0",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"success\": true, \"data\": {\"products\": [...], \"total_found\": 5}}"
      }
    ]
  },
  "id": 2
}
```

### Available Tools

The following tools are available through the MCP endpoint:

#### Data Products Tools

| Tool | Description | Required Scope |
|------|-------------|----------------|
| `search_data_products` | Search products by query | `data-products:read` |
| `get_data_product` | Get product details by ID | `data-products:read` |
| `list_data_products` | List all products | `data-products:read` |
| `create_draft_data_product` | Create a new draft product | `data-products:write` |
| `update_data_product` | Update product details | `data-products:write` |
| `delete_data_product` | Delete a product | `data-products:write` |

#### Data Contracts Tools

| Tool | Description | Required Scope |
|------|-------------|----------------|
| `search_data_contracts` | Search contracts by query | `contracts:read` |
| `get_data_contract` | Get contract details by ID | `contracts:read` |
| `list_data_contracts` | List all contracts | `contracts:read` |
| `create_draft_data_contract` | Create a new draft contract | `contracts:write` |
| `update_data_contract` | Update contract details | `contracts:write` |
| `delete_data_contract` | Delete a contract | `contracts:write` |

#### Semantic Tools

| Tool | Description | Required Scope |
|------|-------------|----------------|
| `search_glossary_terms` | Search business concepts and properties | `semantic:read` |
| `list_semantic_links` | List semantic links for an entity | `semantic:read` |
| `find_entities_by_concept` | Find all entities linked to a concept | `semantic:read` |
| `get_concept_hierarchy` | Navigate concept hierarchies | `semantic:read` |
| `get_concept_neighbors` | Discover related concepts | `semantic:read` |
| `add_semantic_link` | Link entity to business concept | `semantic:write` |
| `remove_semantic_link` | Remove semantic link | `semantic:write` |
| `execute_sparql_query` | Run SPARQL query | `sparql:query` |

#### Organization Tools

| Tool | Description | Required Scope |
|------|-------------|----------------|
| `search_domains` | Search domains | `domains:read` |
| `get_domain` | Get domain details | `domains:read` |
| `search_teams` | Search teams | `teams:read` |
| `get_team` | Get team details | `teams:read` |
| `search_projects` | Search projects | `projects:read` |
| `get_project` | Get project details | `projects:read` |

#### Analytics Tools

| Tool | Description | Required Scope |
|------|-------------|----------------|
| `get_table_schema` | Get Unity Catalog table schema | `analytics:read` |
| `explore_catalog_schema` | List tables in a schema | `analytics:read` |
| `execute_analytics_query` | Execute SQL query | `analytics:read` |

#### Other Tools

| Tool | Description | Required Scope |
|------|-------------|----------------|
| `global_search` | Search across all indexed entities | `search:read` |
| `get_data_product_costs` | Get cost information | `costs:read` |
| `search_tags` | Search tags | `tags:read` |
| `list_entity_tags` | List tags on an entity | `tags:read` |

### Integration Examples

#### Claude Desktop Configuration

Add Ontos as an MCP server in your Claude Desktop config:

```json
{
  "mcpServers": {
    "ontos": {
      "url": "https://your-ontos-instance/mcp",
      "headers": {
        "X-API-Key": "your-mcp-token-here"
      }
    }
  }
}
```

#### Python Integration

```python
import httpx

MCP_URL = "https://your-ontos-instance/mcp"
MCP_TOKEN = "your-mcp-token-here"

def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    response = httpx.post(
        MCP_URL,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": MCP_TOKEN
        },
        json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            },
            "id": 1
        }
    )
    return response.json()

# Search for data products
result = call_mcp_tool("search_data_products", {"query": "customer"})
print(result)
```

#### cURL Examples

**List available tools**:
```bash
curl -X POST https://your-ontos-instance/mcp \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MCP_TOKEN" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

**Search data products**:
```bash
curl -X POST https://your-ontos-instance/mcp \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MCP_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "search_data_products",
      "arguments": {"query": "customer analytics"}
    },
    "id": 2
  }'
```

**Find entities by concept**:
```bash
curl -X POST https://your-ontos-instance/mcp \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MCP_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "find_entities_by_concept",
      "arguments": {"concept_iri": "http://example.com/ontology#Customer"}
    },
    "id": 3
  }'
```

### Security Best Practices

#### Token Management

1. **Principle of Least Privilege**: Grant only the scopes needed
2. **Use Expiration**: Set expiration for temporary integrations
3. **Regular Rotation**: Rotate tokens periodically (e.g., every 90 days)
4. **Audit Usage**: Monitor `last_used_at` for unusual patterns
5. **Revoke Immediately**: Revoke tokens when no longer needed or compromised

#### Scope Recommendations

| Integration Type | Recommended Scopes |
|------------------|-------------------|
| Discovery Chatbot | `*:read`, `search:read` |
| Documentation Generator | `contracts:read`, `data-products:read`, `semantic:read` |
| Compliance Monitor | `contracts:read`, `data-products:read`, `analytics:read` |
| Full Automation | Specific write scopes as needed |

#### Network Security

- Use HTTPS in production
- Consider IP allowlisting for sensitive integrations
- Monitor for unusual request patterns

### Error Handling

The MCP endpoint returns standard JSON-RPC 2.0 errors:

| Error Code | Meaning |
|------------|---------|
| `-32600` | Invalid request format |
| `-32601` | Method not found |
| `-32602` | Invalid params |
| `-32603` | Internal error |
| `-32000` | Tool execution error |
| `-32001` | Unauthorized (invalid/missing token) |
| `-32003` | Forbidden (insufficient scopes) |

**Example Error Response**:
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32003,
    "message": "Insufficient scope: requires 'data-products:write', token has ['data-products:read']"
  },
  "id": 1
}
```

### Health Check

Use the health endpoint to verify connectivity:

```bash
curl https://your-ontos-instance/mcp/health
```

**Response**:
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

---

## Delivery Modes

Delivery Modes control how Ontos persists and propagates changes to external systems when entities (Data Products, Data Contracts, Datasets, Domains, Roles, Tags) are created or updated.

### What are Delivery Modes?

When you create or update an entity in Ontos, the change can be **delivered** to external systems in different ways:

- **Direct Mode**: Automatically apply changes to Unity Catalog (e.g., GRANTs, permissions)
- **Indirect Mode**: Export changes as YAML files to a Git repository for GitOps/CI-CD workflows
- **Manual Mode**: Generate actionable notifications for administrators to apply changes manually

Multiple modes can be active simultaneously. For example, you might use Direct mode for immediate access grants while also persisting all changes to Git for version history and audit trails.

### Delivery Modes Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                          DELIVERY MODES                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Entity Change (Create/Update)                                             │
│         │                                                                   │
│         ▼                                                                   │
│   ┌─────────────────┐                                                       │
│   │ Delivery Service│                                                       │
│   └────────┬────────┘                                                       │
│            │                                                                │
│   ┌────────┼────────────────────────────┐                                   │
│   │        │                            │                                   │
│   ▼        ▼                            ▼                                   │
│ ┌──────┐ ┌──────────┐              ┌────────┐                               │
│ │Direct│ │ Indirect │              │ Manual │                               │
│ │ Mode │ │   Mode   │              │  Mode  │                               │
│ └──┬───┘ └────┬─────┘              └───┬────┘                               │
│    │          │                        │                                    │
│    ▼          ▼                        ▼                                    │
│ UC GRANTs   YAML to Git         Notification                               │
│ Applied     Repository          for Admin                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Direct Mode

**Purpose**: Automatically apply changes directly to connected systems using the service principal.

**Use Cases**:
- Grant access permissions immediately when a Data Product is published
- Update Unity Catalog tags when metadata changes
- Apply security policies to new datasets

**How It Works**:
1. Entity is created or updated in Ontos
2. Delivery Service detects active Direct mode
3. Grant Manager applies the appropriate changes to Unity Catalog
4. Changes take effect immediately

**Configuration**:
1. Navigate to **Settings → Delivery**
2. Enable **Direct Mode**
3. Optionally enable **Dry Run** to test without applying changes

**Dry Run Mode**: When enabled, Direct mode will log what changes *would* be applied without actually executing them. Useful for testing and validation.

**Example Scenario**:
```text
User creates a Data Product with output port:
  → Direct Mode triggers
  → Grant Manager applies SELECT permission to the output table
  → Data consumers can immediately query the table
```

### Indirect Mode

**Purpose**: Export entity changes as YAML files to a Git repository for GitOps workflows, CI/CD pipelines, and version-controlled configuration management.

**Use Cases**:
- Maintain version history of all governance configurations
- Trigger CI/CD pipelines when configurations change
- Enable infrastructure-as-code patterns for data governance
- Audit trail through Git commit history
- Multi-environment promotion (dev → staging → prod)

**How It Works**:
1. Entity is created or updated in Ontos
2. Delivery Service detects active Indirect mode
3. Entity is serialized to YAML using File Models
4. YAML file is written to the local Git repository
5. Administrator reviews and pushes changes to remote

#### Git Repository Setup

Before using Indirect mode, configure the Git repository:

1. Navigate to **Settings → Git**
2. Fill in repository details:
   - **Repository URL**: HTTPS URL (e.g., `https://github.com/org/ontos-state.git`)
   - **Branch**: Target branch (e.g., `main`)
   - **Username**: Git username (or leave empty for PAT-only auth)
   - **Token**: Personal Access Token with repository write permissions

3. Click **Save Settings**
4. Click **Clone Repository** to clone the repo to the configured volume

**Creating a GitHub PAT**:
1. Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token (classic)"
3. Set a descriptive name and expiration
4. Select scopes: `repo` (full repository access)
5. Generate and copy the token

#### YAML File Structure

Entities are exported in a Kubernetes-style resource format:

```yaml
apiVersion: ontos/v1
kind: DataProduct
metadata:
  name: customer-360-view
  id: "abc123-def456"
  createdAt: "2026-01-15T10:30:00Z"
  updatedAt: "2026-01-24T14:45:00Z"
spec:
  title: Customer 360 View
  version: "2.1.0"
  status: active
  ownerTeam: analytics-team
  domain: Customer
  description: Comprehensive customer profile...
  inputPorts:
    - name: crm-data-input
      sourceType: data-product
      sourceId: customer-master-data
  outputPorts:
    - name: customer_360_enriched
      type: table
      location: main.analytics.customer_360_v2
      dataContractId: customer-data-contract-v1
```

#### Supported Entity Types

The following entities are exported to YAML:

| Entity Type | File Path Pattern | Example |
|-------------|-------------------|---------|
| Data Product | `data-products/{id}.yaml` | `data-products/abc123.yaml` |
| Data Contract | `data-contracts/{id}.yaml` | `data-contracts/def456.yaml` |
| Dataset | `datasets/{id}.yaml` | `datasets/ghi789.yaml` |
| Data Domain | `data-domains/{id}.yaml` | `data-domains/jkl012.yaml` |
| App Role | `roles/{id}.yaml` | `roles/mno345.yaml` |
| Tag Namespace | `tags/{id}.yaml` | `tags/pqr678.yaml` |

#### Git Operations

**Status**: View the current repository state
1. Navigate to **Settings → Git**
2. The status panel shows:
   - Clone status (Not Cloned, Cloned, Error)
   - Current branch
   - Last sync time
   - Pending changes count

**Pull**: Fetch latest changes from remote
1. Click **Pull** to update local repository
2. Useful before making changes to ensure you have the latest state

**Diff**: Review pending changes
1. Click **View Diff** to see uncommitted changes
2. Review added, modified, and deleted files
3. Verify changes before committing

**Push**: Commit and push changes to remote
1. Click **Push Changes**
2. Enter a commit message describing the changes
3. Click **Commit & Push**
4. Changes are pushed to the configured remote branch

**Workflow Example**:
```text
1. Create Data Product in Ontos UI
   ↓
2. YAML file written: data-products/abc123.yaml
   ↓
3. Navigate to Settings → Git → View Diff
   ↓
4. Review changes, click Push Changes
   ↓
5. Enter commit message: "Add customer-360-view data product"
   ↓
6. Changes pushed to Git remote
   ↓
7. CI/CD pipeline triggered (optional, external)
```

### Manual Mode

**Purpose**: Generate actionable notifications for administrators when changes require human intervention in external systems.

**Use Cases**:
- Changes that cannot be automated (legacy systems, external tools)
- High-risk changes requiring human approval and execution
- Organizations with strict change control processes
- Environments where automated access is restricted

**How It Works**:
1. Entity is created or updated in Ontos
2. Delivery Service detects active Manual mode
3. A notification is created with:
   - Change details (entity type, ID, what changed)
   - Instructions for manual action
   - Link to the entity
4. Administrator receives notification
5. Administrator performs manual action in external system
6. Administrator marks notification as completed

**Configuration**:
1. Navigate to **Settings → Delivery**
2. Enable **Manual Mode**

**Notification Example**:
```text
Title: Manual Delivery Required: Data Product Updated
Type: delivery
Entity: DataProduct (customer-360-view)
Change: PRODUCT_UPDATE
User: alice@company.com

Action Required:
Apply the following changes in Unity Catalog:
- Update tags on table main.analytics.customer_360_v2
- Verify access permissions match contract requirements

[Mark Complete] [View Entity]
```

### Configuring Delivery Modes

Navigate to **Settings → Delivery** to configure delivery modes.

#### Delivery Settings Panel

| Setting | Description |
|---------|-------------|
| **Direct Mode** | Enable automatic application of changes to Unity Catalog |
| **Direct Dry Run** | Test direct mode without applying changes |
| **Indirect Mode** | Enable YAML export to Git repository |
| **Manual Mode** | Enable notification-based manual delivery |

#### Recommended Configurations

**Development Environment**:
```text
Direct Mode: ✓ (enabled)
Direct Dry Run: ✓ (enabled for testing)
Indirect Mode: ✓ (enabled for tracking)
Manual Mode: ✗ (disabled)
```

**Staging Environment**:
```text
Direct Mode: ✓ (enabled)
Direct Dry Run: ✗ (disabled)
Indirect Mode: ✓ (enabled for CI/CD triggers)
Manual Mode: ✗ (disabled)
```

**Production Environment (GitOps)**:
```text
Direct Mode: ✗ (disabled - changes flow through GitOps)
Indirect Mode: ✓ (enabled - source of truth)
Manual Mode: ✓ (enabled - for exceptions)
```

**Production Environment (Direct)**:
```text
Direct Mode: ✓ (enabled)
Indirect Mode: ✓ (enabled - for audit trail)
Manual Mode: ✗ (disabled)
```

### Error Handling

Delivery operations use a "best effort" approach:
- Delivery failures do not block the primary operation (create/update)
- Errors are logged but do not prevent the user from saving changes
- Failed deliveries can be retried manually

**Checking for Issues**:
1. View backend logs for delivery errors
2. Check Git status for uncommitted changes
3. Review notification history for failed manual deliveries

**Common Issues**:

| Issue | Cause | Solution |
|-------|-------|----------|
| Git clone fails | Invalid credentials | Verify PAT has `repo` scope |
| Push rejected | Remote has newer commits | Pull before pushing |
| YAML not generated | Entity type not supported | Check supported entity types |
| Direct mode no effect | Dry run enabled | Disable dry run for real changes |

### Best Practices

#### GitOps Workflow

1. **Single Source of Truth**: Use Git as the authoritative source for configurations
2. **Pull Requests**: Require PR reviews for production changes
3. **Branch Strategy**: Use feature branches for development
4. **Automated Testing**: Run validation in CI before merge
5. **Automated Deployment**: Deploy from Git to target environments

#### Security Considerations

1. **PAT Scope**: Grant minimal required permissions (only `repo`)
2. **Token Rotation**: Rotate Git tokens regularly (every 90 days)
3. **Audit Trail**: Use meaningful commit messages
4. **Access Control**: Limit who can push to production branches

#### Multi-Mode Strategy

1. **Redundancy**: Enable both Direct and Indirect for critical changes
2. **Verification**: Use Indirect mode's Git history to verify Direct mode applied correctly
3. **Fallback**: Manual mode as backup when automation fails

---

## Best Practices

### Organizational Setup

#### Start with Pilot Domain

1. Choose one well-defined domain
2. Create 1-2 teams
3. Build 2-3 data contracts
4. Publish 1-2 data products
5. Learn and iterate
6. Expand to other domains

#### Establish Governance Early

- Define naming conventions
- Create compliance policies
- Set up review workflows
- Document standards

#### Leverage Demo Mode

Enable `APP_DEMO_MODE` during initial setup to see examples:
- Sample domains, teams, projects
- Example contracts and products
- Pre-configured compliance policies
- Semantic model examples

Disable once you understand the system.

### Workflow Recommendations

#### Contracts First Approach (Recommended)

1. Define the data contract
2. Get contract approved
3. Build the product implementing the contract
4. Request product certification
5. Deploy to production

**Benefits**:
- Consumer needs are clear upfront
- Reduces rework
- Enables parallel development
- Formal quality commitments

#### Products First Approach (Exploration)

1. Build the data product
2. Derive contract from implementation
3. Get contract approved retroactively
4. Request product certification

**When to Use**: Experimentation, prototypes, unclear requirements

### Naming Conventions

#### General Rules

- **Lowercase**: Use lowercase for consistency
- **Snake Case**: Use underscores between words (`customer_orders`)
- **Descriptive**: Make names self-explanatory
- **Avoid Abbreviations**: Unless they're industry-standard

#### Specific Conventions

**Domains**:
- PascalCase: `Finance`, `CustomerSuccess`
- Clear boundaries: `Retail Operations` not `RetailOps`

**Teams**:
- Lowercase with hyphens: `data-engineering`, `analytics-team`
- Include function: `finance-data-team`

**Projects**:
- Lowercase with hyphens: `customer-360-platform`
- Descriptive: `fraud-detection-ml-pipeline`

**Contracts**:
- Lowercase with hyphens: `customer-data-contract`
- Include domain: `finance-transactions-contract`

**Products**:
- Lowercase with hyphens: `customer-360-view`
- Include type: `pos-transaction-stream` (source)

**Tags**:
- Lowercase, no spaces: `pii`, `realtime`, `certified`
- Namespace with prefix: `domain:finance`, `type:aggregate`

### Semantic Linking Strategy

#### When to Link

**Always Link**:
- Important domain concepts
- PII and sensitive fields
- Customer and user identifiers
- Financial fields
- Core business entities

**Consider Linking**:
- Technical metadata fields
- Calculated fields with business meaning
- Aggregated metrics

**Don't Link**:
- Pure technical fields (e.g., `_created_at`, `_id`)
- Temporary columns in transformations
- System-generated fields with no business meaning

#### Three-Tier Linking

Apply semantic links at all three levels for maximum value:

1. **Contract → Business Domain**
2. **Schema → Business Entity**
3. **Property → Business Attribute**

This enables complete semantic traceability.

### Compliance Policy Strategy

#### Policy Categories

Organize policies by category:

- **Governance**: Naming, documentation, ownership
- **Security**: Encryption, access control, PII protection
- **Quality**: Completeness, accuracy, freshness
- **Operations**: Monitoring, SLOs, availability

#### Policy Severity

Assign appropriate severity:

- **Critical**: Security violations, data loss risks
- **High**: Governance requirements, quality issues
- **Medium**: Best practice violations
- **Low**: Recommendations, nice-to-haves

#### Progressive Enforcement

1. **Phase 1**: Create policies, run manually, generate reports
2. **Phase 2**: Enable automated runs, send notifications
3. **Phase 3**: Block deployments based on policy failures
4. **Phase 4**: Auto-remediation where possible

### Review Workflow Optimization

#### Request Grouping

Group related assets in single review requests:

**Good**:
- All tables for a data product
- Tables and views for a feature
- Assets being promoted together

**Avoid**:
- Mixing unrelated assets
- Too many assets (>10) in one request
- Assets not ready for review

#### Steward Assignment

Assign the right steward:

- **Domain Steward**: For domain-specific reviews
- **Security Officer**: For PII/security reviews
- **Technical Steward**: For complex technical assets
- **General Steward**: For routine reviews

#### Response Times

Set expectations:

- **Standard Reviews**: 2-3 business days
- **Urgent Reviews**: 1 business day (pre-arranged)
- **Complex Reviews**: Up to 1 week

Communicate timelines clearly.

### Data Product Lifecycle Management

#### Version Tagging

Tag products with version indicators:

- `v1`, `v2`, `v3` - Major versions
- `stable`, `beta`, `alpha` - Maturity
- `deprecated` - Products being sunset

#### Deprecation Process

When deprecating a product:

1. Announce 90 days in advance (minimum)
2. Mark product as "Deprecated" with sunset date
3. Communicate replacement product
4. Send reminders at 60, 30, and 7 days
5. Track consumer usage
6. Archive after sunset date
7. Keep documentation available

#### Consumer Communication

Notify consumers of changes:

- **Breaking Changes**: 90-day notice, major version bump
- **New Features**: Release notes, minor version bump
- **Bug Fixes**: Release notes, patch version bump
- **Deprecations**: Multiple reminders over 90 days

Use Ontos notifications and external channels (email, Slack).

---

## Conclusion

Ontos provides comprehensive tools for data governance and management at enterprise scale. By following the practices outlined in this guide, your organization can:

- Establish clear organizational structure with domains, teams, and projects
- Formalize data specifications with contracts
- Deliver high-quality data products
- Automate compliance and governance
- Enable self-service data discovery
- Maintain semantic clarity and lineage

### Next Steps

1. **Complete Initial Setup**: Follow the "Getting Started" section
2. **Register Existing Assets**: Create datasets for your most important data
3. **Formalize Specifications**: Build data contracts for key datasets
4. **Run Pilot**: Choose one domain and build 2-3 products end-to-end
5. **Add Compliance**: Create policies to automate governance
6. **Establish Standards**: Document your naming conventions and policies
7. **Scale Adoption**: Expand to additional domains and teams
8. **Continuous Improvement**: Iterate based on user feedback

**Recommended Path**: Follow the [Growing with Ontos](#growing-with-ontos) journey for a structured adoption approach.

### Getting Help

- **Documentation**: Refer to this guide and linked references
- **Settings → About**: View feature documentation and API docs
- **Audit Trail**: Track what changes were made and by whom
- **Support**: Contact your Ontos administrator or support team

### Additional Resources

- **Compliance DSL Documentation**:
  - [Compliance DSL Quick Guide](/user-docs/compliance-dsl-guide) - Quick start guide for writing compliance rules
  - [Compliance DSL Reference](/user-docs/compliance-dsl-reference) - Complete syntax reference and advanced examples
- [User Journeys](user-journeys/README.md)
- [API Documentation](http://localhost:8000/docs) (when running locally)

**Note**: Compliance DSL documentation can be accessed via the Settings menu or directly through the documentation API.

---

*This user guide covers the stable, non-beta/alpha features of Ontos. Features marked as "alpha" or "beta" in the UI may have incomplete documentation or evolving functionality.*

**App Version**: 0.4.6  
**Last Updated**: January 2026  
**Target Audience**: Ontos End Users (Data Product Teams, Data Stewards, Data Consumers)

For detailed changes between versions, see the [Release Notes](/user-docs/release-notes).


---
sidebar_position: 3
---
# Core Concepts

Understanding Ontos foundational concepts is key to effectively using the platform for comprehensive Unity Catalog governance and metadata management.

The concepts below define the structure, ownership, and boundaries for your data initiatives.

![Ontos Concepts](/img/concepts.png)

## 🏢 Organizational Structure
Organize data work using **Domains**, **Teams**, and **Projects** aligned with your organizational structure and data mesh architecture.

### 🗂️ Domains
Domains are logical, hierarchical groupings of data based on business areas (e.g., Finance, Sales). They provide high-level organization, clear ownership boundaries, and group related data products.

### 👥 Teams
Collections of users and Databricks workspace groups working on data initiatives. Teams can be associated with specific Domains, track metadata (like Slack channels), and support custom role overrides for individual members.

### 📁 Projects
Workspace containers that organize team initiatives with defined boundaries.
There are two types of projects, namely _Personal_ (auto-created for individual users) and _Team_ (shared for collaborative work). Teams provide logical isolation for development work and allow multiple teams to collaborate.


## Assets and Specifications
Now let's explore concepts related to _data assets and specifications_. These ideas describe the physical data, its defined specifications, and how it is packaged for use.


### 📦 Assets

Assets are the unified representation of all cataloged objects in Ontos, powered by the ontology-driven data model. Asset types (Dataset, Table, View, Dashboard, API Endpoint, Stream, etc.) are defined in the ontology (ontos-ontology.ttl) and synced automatically at startup.

The following are the types of Assets managed in Ontos: 

- *Ontology-Driven:* Asset types, their fields, and valid relationships are all derived from the OWL ontology
- *Unified Model:* Replaces bespoke tables for datasets, tables, views, etc., with a single assets table using typed properties
- *Dynamic Forms:* Create and edit any asset type using dynamically generated forms based on the ontology schema
- *Entity Relationships:* Cross-entity relationships (lineage, containment, consumption) stored in entity_relationships
- *Persona Visibility:* Asset types are filtered per-persona based on ontology annotations
- *Asset Explorer:* Browse all asset types in a unified sidebar with type-based filtering, available under Data Steward and Data Governance Officer personas


:::info
**Legacy Note:** The standalone "Datasets" feature is deprecated. Datasets are now stored as Asset entities with *asset_type="Dataset"*. The legacy API at `/api/datasets` remains for backward compatibility.
:::

### 📝 Data Contracts
Represent technical specifications and guarantees for data assets, following the ODCS v3.1.0 standard. They define schema (names, types, constraints), data quality rules (SLOs), and semantic links to business concepts. A Data Contract is the _what should exist_ (specification).

The key attributes of a Data Contract in Ontos are as follows:
- *Schema Definition*: Column names, types, constraints, and descriptions
- *Quality Guarantees*: Data quality rules and SLOs (Service Level Objectives)
- *Semantic Linking*: Connect schemas and properties to business concepts
- *Lifecycle*: Draft → Proposed → Under Review → Approved → Active → Certified → Deprecated → Retired
- *Versioning*: Track contract evolution of the data contract over time

### 📊 Data Products
Embody curated, consumable collections of Databricks assets (tables, views, models). Data Products are delivered products with defined Input/Output Ports, organized by standardized tags, and progress through various status levels (e.g., Development, Certified).

The key attributes of a Data Product in Ontos are as follows:
- *Product Types:* Source, Source-Aligned, Aggregate, Consumer-Aligned
- *Input/Output Ports:* Define data flows and dependencies
- *Tags:* Organize and discover products using standardized tags
- *Status:* Development → Sandbox → Pending Certification → Certified → Active → Deprecated

## Governance and Integrations
Lastly, the definitions below relate to Ontos elements used for _governance, modeling, and integration_. These concepts support comprehensive governance and interoperability across platforms.


### 🧠 Semantic Models
In Ontos, Semantic Models are used as a knowledge graph that connects technical data assets to high-level business concepts (e.g., Customer, Transaction) and properties (email, customerId). They are used as Frameworks, based on standard ontology formats (RDF/RDFS) to ensure interoperability.

A semantic model in Ontos is composed of the following:
- *Business Concepts:* High-level domain concepts (Customer, Product, Transaction)
- *Business Properties:* Specific data elements (email, firstName, customerId)
- *Semantic Linking:* Three-tier system linking contracts, schemas, and properties to business terms
- *RDF/RDFS:* Based on standard ontology formats for interoperability

### ✅ Compliance Policies
Compliance Policies act as rules that automatically check data assets against governance requirements. They are written in a SQL-like Domain-Specific Language (DSL), can check various entity types (catalogs, tables, app entities), and trigger actions like tagging or validation failures. Compliance rules run on schedules for continuous monitoring.

Essentially, an Ontos compliance policy outlines the following:
- *DSL (Domain-Specific Language):* Write rules in a SQL-like declarative syntax
- *Entity Types:* Check catalogs, schemas, tables, views, functions, and app entities
- *Actions:* Tag non-compliant assets, send notifications, or fail validations
- *Continuous Monitoring:* Run policies on schedules to track compliance over time

### 🤖 Connectors
Connectors or Platform Integrations are modular components that enable Ontos to manage assets from various data platforms beyond Unity Catalog. They support platform-independent governance and asset discovery through a unified interface. Currently, Ontos supports Databricks/Unity Catalog and plans to add support for Snowflake, Apache Kafka, and Microsoft Power BI.

:white_check_mark: If you are ready to deploy Ontos to a Databricks Workspace, please proceed to the next section. 













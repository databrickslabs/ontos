---
sidebar_position: 3
---
# Core Concepts

Understanding Ontos foundational concepts is key to effectively using the platform for comprehensive Unity Catalog governance and metadata management.

The concepts below define the structure, ownership, and boundaries for your data initiatives.

![Ontos Concepts](/img/concepts.png)

## 🏢 Organizational Structure
Organize data work using **Domains**, **Teams**, and **Projects** aligned with your organizational structure and data mesh architecture.

### Domains
Domains are logical, hierarchical groupings of data based on business areas (e.g., Finance, Sales). They provide high-level organization, clear ownership boundaries, and group related data products.

### Teams
Collections of users and Databricks workspace groups working on data initiatives. Teams can be associated with specific Domains, track metadata (like Slack channels), and support custom role overrides for individual members.

### Projects
Workspace containers that organize team initiatives with defined boundaries.
There are two types of projects, namely _Personal_ (auto-created for individual users) and _Team_ (shared for collaborative work). Teams provide logical isolation for development work and allow multiple teams to collaborate.

Now let's explore concepts related to _data assets and specifications_. These ideas describe the physical data, its defined specifications, and how it is packaged for use.

## 📦 Datasets
Datasets are defined as logical groupings of related data assets (tables, dimensions, lookups, metrics) that represent the physical reality of data. They can have multiple physical implementations across different systems and environments (multi-platform support), use a unified asset type system, and can implement Data Contracts. In short, a Dataset is the _what exists_ (physical reality).

## 📝 Data Contracts
Represent technical specifications and guarantees for data assets, following the ODCS v3.1.0 standard. They define schema (names, types, constraints), data quality rules (SLOs), and semantic links to business concepts. A Data Contract is the _what should exist_ (specification).

## 📊 Data Products
Embody curated, consumable collections of Databricks assets (tables, views, models). Data Products are delivered products with defined Input/Output Ports, organized by standardized tags, and progress through various status levels (e.g., Development, Certified).

Lastly, the definitions below relate to Ontos elements used for _governance, modeling, and integration_. These concepts support comprehensive governance and interoperability across platforms.

## 🧠 Semantic Models
In Ontos, Semantic Models are used as a knowledge graph that connects technical data assets to high-level business concepts (e.g., Customer, Transaction) and properties (email, customerId). They are used as Frameworks, based on standard ontology formats (RDF/RDFS) to ensure interoperability.

## ✅ Compliance Policies
Compliance Policies act as rules that automatically check data assets against governance requirements. They are written in a SQL-like Domain-Specific Language (DSL), can check various entity types (catalogs, tables, app entities), and trigger actions like tagging or validation failures. Compliance rules run on schedules for continuous monitoring.

## 🤖 Connectors
Connectors or Platform Integrations are modular components that enable Ontos to manage assets from various data platforms beyond Unity Catalog. They support platform-independent governance and asset discovery through a unified interface. Currently, Ontos supports Databricks/Unity Catalog and plans to add support for Snowflake, Apache Kafka, and Microsoft Power BI.

:white_check_mark: If you are ready to deploy Ontos to a Databricks Workspace, please proceed to the next section. 













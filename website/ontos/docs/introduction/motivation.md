---
sidebar_position: 1
---
# Motivation

**Ontos**  is a comprehensive data governance and metadata management platform built for Databricks Unity Catalog and delivered as a native Databricks App. It empowers data teams to implement data mesh principles by providing tools to organize, govern, and deliver high-quality data products, Data Contracts, and Business Glossaries, adhering to industry standards like ODCS and ODPS.

:::info
Refer to the [BITOL Open Data Contract Standard (ODCS)](https://github.com/bitol-io/open-data-contract-standard) and the [BITOL Open Data Product Standard (ODPS)](https://github.com/bitol-io/open-data-product-standard) for data product to learn more about the standards supported by Ontos. 
:::

:::tip
Ontos can now be accessed via the [Databrickslabs](https://www.databricks.com/learn/labs) site and the [Databricks Marketplace](https://www.databricks.com/product/marketplace).
:::


## Key benefits

The following outlines the key benefits of adopting and implementing Ontos. 

:white_check_mark: **Data Product Management:** Group and organize Databricks assets (tables, views, functions, models, dashboards) into discoverable data products with proper ownership and governance

:white_check_mark: **Data Contracts:** Instrument data products with technical metadata following the Open Data Contract Standard (ODCS), including schema validation, quality checks, and access control

:white_check_mark: **Business Glossary:** Maintain hierarchical glossaries that provide semantic context and enable consistent terminology across your organization

:white_check_mark: **Role-Based Access Control:** Built-in RBAC with configurable personas (Admin, Data Producer, Data Consumer, Data Steward) to control who can create, edit, or consume data products

:white_check_mark: **Compliance & Governance:** Automated compliance scoring and verification to ensure data products meet organizational standards

## Use cases

Below are the primary use cases for leveraging Ontos. While this list is not exhaustive, it highlights the main patterns through which Ontos delivers most of its value. 

:bulb: **Data Mesh Implementation:** Enable domain teams to publish and manage their data products independently while maintaining enterprise governance standards

:bulb: **Self-Service Data Discovery:** Provide a marketplace-like experience for data consumers to browse, subscribe to, and access certified data products

:bulb: **Data Contract-Driven Development:** Establish clear contracts be   tween data producers and consumers before building pipelines, reducing integration issues

:bulb: **Business Glossary Management:** Create and maintain organization-wide or domain-specific business terminology to ensure consistent data interpretation

:bulb: **Compliance Auditing:** Continuously monitor and score data assets against defined compliance rules with automated notifications for violations

:bulb: **Access Policies:** Author access rules once as W3C ODRL policies for audiences and assets, then compile and deliver them to Unity Catalog (and other platforms) with tracked, time-bound grants

## How Ontos works

Ontos provides a comprehensive framework for managing data assets, starting with `Domains`, hierarchical, logical groupings that define ownership boundaries based on business areas such as Finance or Sales. `Teams`, consisting of users and groups, are assigned to these domains to manage data initiatives and roles, often working within `Projects`, which serve as isolated workspaces for development. 

The core data assets include `Datasets`, representing the "what exists" or the physical reality of related tables and dimensions across systems, and `Data Contracts`, which define the "what should exist" by specifying technical details, quality guarantees, and semantic links according to the ODCS v3.1.0 standard. These assets are packaged into `Data Products`, which are curated, consumable collections of Databricks assets with defined input/output ports. 

To ensure discoverability and interoperability, `Semantic Models` act as a knowledge graph, connecting technical assets to high-level business concepts using RDF/RDFS. Finally, `Compliance Policies`, written in a Domain Specific Language (DSL), automatically check data assets against governance requirements, enabling actions such as automatic tagging or validation failures.

The building blocks of Ontos discussed earlier are further explained in the [Concepts and Definitions](../introduction/concepts) section.

## Traget audience

Ontos is a tool for a variety of data-focused roles, including:
- _Data Product Owners_: Managing product vision and delivery.
- _Data Engineers_: Building and maintaining data pipelines and products.
- _Data Stewards_: Ensuring governance, compliance, and quality.
- _Data Consumers_: Discovering and using data products.
- _Analytics Teams_: Working with curated data for insights.
- _Platform Engineers_: Integrating AI assistants and automating workflows via MCP.


:rocket: Now that you understand what Ontos is and how it functions, we’ll guide you through its architecture and main solution components. :arrow_right:



---
sidebar_position: 0
id: index
title: Getting Started
description: getting started guide for setting up ontos in databricks
---

# Getting Started

Ontos can be deployed in Databricks in two ways:

1. **[Databricks Marketplace](./install_marketplace.md):** Install Ontos via the [Databricks Marketplace](https://marketplace.databricks.com/).
2. **[Databricks Labs](./install_databricks.md):** Configure and deploy Ontos by cloning the Ontos GitHub repository from [Databricks Labs](https://github.com/databrickslabs).

Take your pick! For simplicity, select the Marketplace option; for customization, choose the Databricks Labs path.

## Prerequisites

The following items must be available on the workspace where Ontos will be deployed:

- Access to a foundational model API (e.g., databricks-claude-sonnet-4-5)
- Access to a DBSQL Serverless or DBSQL Pro endpoint
- Permissions:
    - You have Workspace Admin entitlement
    - `APP_ADMIN_DEFAULT_GROUPS` in `app.yaml` corresponds to IdP admin group

In addition to the items above, a managed volume within a Unity Catalog and Schema dedicated to Ontos is required.

Follow the process for Creating a Volume from the official Databricks [documentation](https://docs.databricks.com/aws/en/volumes/utility-commands#create-a-volume).

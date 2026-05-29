# AI-Focused Podcast Narrative: Ontos and Ontological Knowledge Systems

## Episode Title: "Bridging the Gap: When Business Data Meets Semantic Intelligence"

### Episode Overview

This episode explores how **Ontos**—a comprehensive data governance platform—represents a new paradigm in enterprise data management: the fusion of traditional data engineering with **ontological knowledge systems**. We'll discuss how AI and semantic modeling are transforming how organizations understand, govern, and derive value from their data assets.

---

## Part 1: Setting the Stage

### Opening Monologue (Host)

*"Every organization today is drowning in data. We have petabytes of tables, views, and dashboards scattered across our data platforms. But here's the uncomfortable truth: most companies can't answer a simple question—'What customer data do we have, and what does it mean?'*

*Today we're exploring a platform called Ontos that attempts to solve this fundamental disconnect. It's not just another data catalog. It's an attempt to bridge the gap between the technical reality of data—the tables, schemas, and pipelines—with the semantic reality of what that data actually means to the business.*

*And at the heart of this is something that might surprise you: ontologies. Yes, the same ontologies that power the semantic web, knowledge graphs, and increasingly, the reasoning capabilities of large language models."*

---

## Part 2: The Interview

### Q1: What problem is Ontos trying to solve?

**Guest (Lars George, Creator of Ontos):**

"The core problem is what I call the 'semantic gap.' We have incredibly sophisticated data platforms—Databricks, Snowflake, data lakes—but there's a massive disconnect between what the data technically *is* and what it *means* to the business.

A data engineer sees `main.crm.customers_v2` with columns like `cust_id`, `fname`, `lname`, `dob`. But a business user asks: 'Where's our customer master data? Does it include the email addresses we need for GDPR compliance?'

Traditional data catalogs try to bridge this with tags and descriptions. But Ontos goes further. We build an actual **knowledge graph**—using RDF and RDFS—that creates formal semantic links between technical assets and business concepts.

So that `customers_v2` table isn't just tagged 'customer.' It's formally linked to a 'Customer' business concept in an ontology. The `dob` column is linked to a 'dateOfBirth' business property. And that property has semantics: it's personally identifiable information, it has privacy implications, it relates to the 'Person' concept.

This means when an AI assistant—or a compliance policy—asks about PII, we can answer with confidence, not guesswork."

---

### Q2: Can you explain what you mean by "ontological knowledge systems" in practical terms?

**Guest:**

"Great question. An ontology, in data terms, is a formal representation of knowledge as a set of concepts, their properties, and the relationships between them.

Think of it as a shared vocabulary—but structured. It's not just a list of definitions. It captures the fact that a 'Customer' is a type of 'Person,' that a 'Person' has an 'email,' that an 'email' is a type of 'ContactMethod,' and so on.

In Ontos, we have two types of semantic entities:

1. **Business Concepts**: High-level domain entities like Customer, Product, Transaction, Order
2. **Business Properties**: Specific data elements like email, firstName, customerId, transactionAmount

These are defined in RDF/RDFS format—the same format that powers the semantic web, Wikidata, and enterprise knowledge graphs.

The practical value? When you search for 'customer email' in Ontos, you're not doing keyword matching. The system understands that 'email' is a property of 'Customer,' and it can find every data asset in your organization that represents customer email addresses—regardless of whether the column is called `email`, `email_address`, `cust_email`, or `e_mail`.

That's the power of semantic linking."

---

### Q3: How does this relate to AI and large language models?

**Guest:**

"This is where it gets really interesting. Large language models are incredibly powerful at understanding natural language, but they have a fundamental limitation: they don't have access to your organization's specific data and its meaning.

Ontos solves this through the **Model Context Protocol (MCP)**—an emerging standard for connecting AI assistants to external systems.

We expose our entire data governance platform through MCP. So when you're talking to Claude or another AI assistant, it can:

- **Discover** what data products exist in your organization
- **Understand** the semantic meaning of data through our ontology
- **Query** the knowledge graph using SPARQL
- **Navigate** relationships between business concepts and technical assets

Here's a concrete example. You could ask an AI: 'Find all tables that contain customer personally identifiable information.'

Without Ontos, the AI would have to guess—maybe look for columns named 'SSN' or 'email.' With Ontos, the AI can query our semantic model: 'Find all data assets linked to business properties that have the PII classification.' It returns precise, complete results.

Even better, because we follow the ODCS (Open Data Contract Standard), all this semantic metadata is structured. The AI can understand data quality rules, SLAs, ownership, and lineage—not just column names."

---

### Q4: You mentioned Data Contracts. How do they fit into this semantic picture?

**Guest:**

"Data Contracts are really the heart of Ontos. They're formal specifications—think of them as APIs for data.

A Data Contract defines:
- The **schema**: what columns exist, their types, constraints
- **Quality rules**: data must be non-null, must match patterns, must be within ranges
- **SLOs**: service level objectives like freshness, availability, accuracy
- **Semantic links**: formal connections to business concepts

The semantic linking happens at three levels:

1. **Contract level**: The whole contract is linked to a business domain
2. **Schema level**: Each table/view is linked to a business entity
3. **Property level**: Each column is linked to a business property

This three-tier system means we capture semantics at every level of granularity. And because contracts follow the ODCS standard, they're portable. You can share them across organizations, import them from other systems, or generate them from existing assets.

The relationship model is elegant:

```
Data Product → Data Contract ← Dataset
                    ↑
            Semantic Links → Business Ontology
```

A Data Product packages data for consumption. It references Data Contracts for its output ports. Datasets are the physical implementations—the actual tables in Unity Catalog or Snowflake. And everything is threaded together through semantic links to the business ontology."

---

### Q5: How does this enable better compliance and governance automation?

**Guest:**

"This is one of my favorite aspects of Ontos. We have a Compliance DSL—a domain-specific language for writing governance rules.

Here's a simple example:

```
MATCH (obj:Object)
WHERE obj.type IN ['table', 'view'] AND obj.catalog = 'prod'
ASSERT HAS_TAG('data-product') OR HAS_TAG('excluded-from-products')
ON_FAIL FAIL 'All production assets must be tagged with a data product'
ON_FAIL ASSIGN_TAG compliance_status: 'untagged'
```

This rule automatically checks every production table and view, ensuring they're properly organized into data products.

But here's where semantics make it powerful. Because we have semantic links, we can write rules like:

```
MATCH (tbl:table)
WHERE HAS_TAG('contains_pii') AND TAG('contains_pii') = 'true'
ASSERT TAG('encryption') = 'AES256'
ON_FAIL NOTIFY 'security-team@company.com'
```

This rule finds all tables containing PII—not by guessing from column names, but by following semantic links to properties classified as personally identifiable information—and ensures they're properly encrypted.

The compliance engine runs continuously. It's not a one-time audit; it's ongoing governance. And because everything is semantically grounded, the rules are precise and don't suffer from the false positives you get with pattern matching."

---

### Q6: You mentioned Data Products and Data Mesh. How does Ontos support that paradigm?

**Guest:**

"Ontos is built from the ground up for Data Mesh. The core idea of Data Mesh is treating data as a product—with clear ownership, quality guarantees, and discoverability.

Our object model reflects this:

- **Domains**: Business areas like Finance, Sales, Customer
- **Teams**: Groups of people who own and produce data
- **Projects**: Initiatives where data work happens
- **Data Contracts**: Formal specifications
- **Data Products**: Consumable packages of data
- **Datasets**: Physical implementations

Each data product has:
- An **owner team** responsible for its quality
- **Input ports** defining data dependencies
- **Output ports** defining what's delivered
- **Linked contracts** specifying the guarantees
- **Lifecycle states**: Draft → Sandbox → Certified → Active → Deprecated

We support both 'Contracts First' and 'Products First' approaches, though we recommend Contracts First. The idea is: agree on the interface (the contract) before building the implementation (the product).

This is analogous to API-first development. You define the contract, consumers agree it meets their needs, and then engineers build to that specification. It prevents the all-too-common scenario of building a data product that nobody actually needs."

---

### Q7: How do AI assistants actually interact with Ontos?

**Guest:**

"Through MCP—the Model Context Protocol. It's a JSON-RPC 2.0 based protocol that lets AI assistants discover and call tools.

When an AI connects to Ontos via MCP, it can:

1. **List available tools**: Based on the token's scopes, the AI sees what operations are available
2. **Search**: `search_data_products`, `search_data_contracts`, `search_glossary_terms`
3. **Read**: `get_data_product`, `get_table_schema`, `explore_catalog_schema`
4. **Navigate semantics**: `find_entities_by_concept`, `get_concept_hierarchy`, `get_concept_neighbors`
5. **Query**: `execute_sparql_query` for complex semantic queries
6. **Write**: Create contracts, update products, add semantic links

Here's what's powerful: the AI can chain these together intelligently.

You ask: 'What data do we have about customer transactions, and who owns it?'

The AI:
1. Searches for 'customer transactions' using semantic search
2. Finds the relevant data products and contracts
3. Gets the owner team information
4. Queries the semantic model for related concepts
5. Returns a comprehensive answer with lineage, ownership, and quality information

All of this happens through natural conversation. The user doesn't need to know about catalogs, schemas, or query languages."

---

### Q8: What about data quality and trust? How do users know they can rely on the data?

**Guest:**

"Trust is built through multiple mechanisms:

1. **Asset Review Workflows**: Before any data product goes to production, it goes through formal review by Data Stewards. They can examine schemas, preview data, and even get AI-assisted analysis of potential issues.

2. **Certification**: Products go through a certification process. The 'Certified' status indicates the product has passed rigorous governance review.

3. **SLOs in Contracts**: Every contract can define Service Level Objectives—freshness guarantees, availability targets, accuracy thresholds. These are automatically monitored.

4. **Compliance Policies**: Continuous automated checking against governance rules.

5. **Semantic Clarity**: Because everything is linked to business concepts, there's no ambiguity about what data means.

We also track lineage—where data comes from, how it's transformed, what depends on it. This creates a complete trust chain from source to consumption.

And here's something we're working on: trust scores. Aggregating signals—compliance status, SLO adherence, consumer feedback, freshness—into a single trust indicator for each data product."

---

## Part 3: Demo Walkthrough

### Demo Segment: "Semantic Discovery in Action"

*Host: "Let's see this in practice. Lars, can you walk us through a demonstration?"*

---

#### Demo 1: Semantic Search and Discovery

**Scenario**: A data analyst needs to find customer email data for a marketing campaign.

**Steps**:
1. Navigate to the **Search** bar in Ontos
2. Type: "customer email"
3. Show how results return:
   - Data Products containing customer email
   - Data Contracts with email properties
   - Physical Datasets implementing email
4. Click into a Data Contract
5. Demonstrate the **semantic links**:
   - Contract → "CustomerDomain" business concept
   - Schema → "Customer" entity
   - `email` column → "email" business property
6. Show the **business property details**: PII classification, format constraints, linked assets

**Key Talking Point**: *"Notice how we didn't search for 'email_address' or 'e_mail' or 'cust_email.' The semantic model understands that all these represent the same business concept. This is impossible with traditional keyword search."*

---

#### Demo 2: AI-Powered Data Discovery (MCP Integration)

**Scenario**: Using an AI assistant to explore data governance.

**Steps**:
1. Open Claude Desktop (or show a terminal with MCP client)
2. Ask: "What data products do we have related to customer analytics?"
3. Show the AI calling `search_data_products` via MCP
4. Ask: "What's the schema of the Customer 360 product?"
5. AI calls `get_data_product`, then `get_table_schema`
6. Ask: "Find all tables that contain personally identifiable information"
7. AI calls `find_entities_by_concept` with PII concept
8. Show results: tables semantically linked to PII properties

**Key Talking Point**: *"The AI isn't guessing or doing string matching. It's querying our knowledge graph. When we ask about PII, it's traversing semantic relationships—from PII classification to business properties to column definitions to physical tables. This is ontological reasoning in action."*

---

#### Demo 3: Data Contract Creation with Semantic Linking

**Scenario**: A data engineer creates a new contract with proper semantic grounding.

**Steps**:
1. Navigate to **Contracts** → **Create Contract**
2. Fill in basic info: "Sales Transaction Contract v1.0"
3. Add a Schema Object: "transactions" table
4. Click **Add Semantic Link** on the schema
5. Search for and select "Transaction" business concept
6. Add properties: `transaction_id`, `amount`, `customer_id`, `timestamp`
7. For each property, add semantic links:
   - `transaction_id` → "transactionId" business property
   - `amount` → "monetaryAmount" business property (show PII=false, type=decimal)
   - `customer_id` → "customerId" business property (show it's a foreign key concept)
8. Define quality rules: `amount > 0`, `timestamp NOT NULL`
9. Define SLOs: 99.9% availability, refreshed hourly
10. Submit for review

**Key Talking Point**: *"We've created more than a schema definition. We've created a semantically grounded specification. When compliance policies run, when AI assistants query, when data consumers search—they all understand the business meaning of this data."*

---

#### Demo 4: Compliance Automation

**Scenario**: Running automated governance checks.

**Steps**:
1. Navigate to **Compliance**
2. Show an existing policy: "PII Data Must Be Encrypted"
3. Explain the DSL syntax:
   ```
   MATCH (tbl:table)
   WHERE HAS_TAG('contains_pii') AND TAG('contains_pii') = 'true'
   ASSERT TAG('encryption') = 'AES256'
   ON_FAIL ASSIGN_TAG security_risk: 'high'
   ON_FAIL NOTIFY 'security-team@company.com'
   ```
4. Click **Run Policy**
5. Show results:
   - Tables checked: 150
   - Passed: 145
   - Failed: 5
6. Drill into a failure—show the non-compliant table
7. Show that the `security_risk: high` tag was automatically applied

**Key Talking Point**: *"This is declarative governance. We're not writing procedural code to check each table. We're expressing intent—'PII must be encrypted'—and the system enforces it continuously. And because we know which tables contain PII through semantic links, not guesses, there are no false negatives."*

---

#### Demo 5: Knowledge Graph Exploration

**Scenario**: Navigating the semantic model visually.

**Steps**:
1. Navigate to **Semantic Models**
2. Explore the **Business Concepts** hierarchy:
   - Show top-level concepts: Customer, Product, Transaction
   - Drill into Customer → show subConcepts, properties
3. Click on a concept to see **Linked Assets**:
   - Contracts linked to "Customer"
   - Schemas linked to "Customer"
   - Properties linked to "Customer"
4. Use **Search** to find "email"
5. Show the business property definition:
   - Type: string
   - Classification: PII
   - Pattern: email format
   - Linked to: "Person", "Customer", "Contact"
6. Click **Find Entities by Concept** to see all uses of email across the organization

**Key Talking Point**: *"This is your organization's business vocabulary, formalized. It's not documentation that rots—it's a living knowledge graph that powers search, compliance, AI integration, and data discovery. Every data asset is grounded in this shared understanding."*

---

## Part 4: Deep Dive Q&A

### Q9: What's the relationship between Ontos and the Databricks ecosystem?

**Guest:**

"Ontos is designed to run as a **Databricks App**—it's natively integrated with the Databricks platform.

The integration points are:
- **Unity Catalog**: Ontos reads catalog metadata, validates asset existence, and can deploy contracts to UC
- **Databricks SDK**: We use the official SDK for all platform operations
- **Databricks Workflows**: Heavy workloads like bulk imports and compliance checks run as Databricks jobs
- **Workspace Groups**: Our RBAC integrates with Databricks identity
- **Lakebase**: We can use Databricks' serverless Postgres for our metadata store

But Ontos isn't locked to Databricks. Datasets can have instances in Snowflake, BigQuery, or any other system. The semantic layer is platform-agnostic.

This is important for enterprises with hybrid architectures. You might have customer data in Snowflake, transaction data in Databricks, and reference data in Postgres. Ontos provides a unified semantic layer across all of them."

---

### Q10: How does this fit with emerging standards like the Open Data Contract Standard?

**Guest:**

"We're committed to open standards. Ontos implements:

- **ODCS v3.0.2**: Open Data Contract Standard—this is our contract schema format
- **ODPS**: Open Data Product Specification—this informs our product model
- **MCP**: Model Context Protocol—for AI integration
- **RDF/RDFS**: For semantic modeling

The benefit of standards is interoperability. An ODCS contract created in Ontos can be exported and used in other ODCS-compliant systems. You're not locked in.

We're active participants in the BITOL community—that's the organization behind ODCS and ODPS. Data contracts are becoming a standard practice, and we want to ensure Ontos contracts are portable and future-proof."

---

### Q11: What's the learning curve for organizations adopting this?

**Guest:**

"We've designed for progressive adoption. The User Guide outlines a four-stage journey:

1. **Discover with Datasets**: Just register your existing tables. No contracts, no semantics—just inventory your assets and assign ownership.

2. **Formalize with Contracts**: Start defining contracts for your most important datasets. Add schemas, quality rules, and optionally semantic links.

3. **Productize with Products**: Package datasets and contracts into Data Products. Define input/output ports, publish to the marketplace.

4. **Govern with Compliance**: Write policies, automate enforcement, track compliance over time.

You can start at stage 1 and never progress—you still get value from the central registry. Or you can go all the way to stage 4 for full automated governance.

The semantic modeling is optional but increasingly valuable as you mature. We provide sample taxonomies—business concepts and properties—so you don't have to build from scratch."

---

### Q12: Where do you see this going in the future?

**Guest:**

"A few directions excite me:

**1. AI-Native Governance**: We're just scratching the surface with MCP. Imagine AI assistants that can not just query but also propose contracts, suggest semantic links, identify compliance gaps, and recommend remediations. The structured nature of our data model makes this feasible.

**2. Federated Ontologies**: Right now our semantic model is centralized. Future versions could support federated ontologies—where each domain maintains its own business vocabulary, and Ontos reconciles them into a unified view.

**3. Active Metadata**: Moving from passive documentation to active enforcement. Contracts that automatically validate data as it's written. Semantic links that propagate quality signals. Compliance policies that block non-compliant deployments.

**4. Trust Networks**: Extending trust beyond organizational boundaries. If two companies share data via a common contract standard, with semantic interoperability, you could have cross-organizational data products with verifiable quality guarantees.

**5. Knowledge Graph Reasoning**: Using the semantic model for inference. If 'CustomerEmail' is PII, and 'AccountEmail' is linked to 'CustomerEmail', then 'AccountEmail' is implicitly PII. This kind of reasoning is powerful for compliance and discovery.

The fundamental insight is that data governance is ultimately about meaning. And ontologies—knowledge graphs, semantic models—are how we formalize meaning. AI is how we scale the application of that meaning. Ontos is our attempt to bring these together."

---

## Part 5: Rapid-Fire Questions

### Q: One-sentence pitch for Ontos?

**A:** "Ontos is a semantic layer for data governance—connecting what data technically is to what it means for your business, and making that understanding accessible to humans and AI alike."

### Q: What's the single most underrated feature?

**A:** "SPARQL query support via MCP. You can run arbitrary semantic queries over your entire data estate—find all assets where the owner is in a certain domain, or all contracts with PII properties but no encryption requirement. It's incredibly powerful."

### Q: Biggest challenge in building Ontos?

**A:** "Getting the abstraction level right. Too simple and you lose semantic power. Too complex and adoption suffers. Data Contracts with three-tier semantic linking—contract, schema, property—seems to be the sweet spot."

### Q: If listeners want to try Ontos, where do they start?

**A:** "It's open source under Apache 2.0 at github.com/databrickslabs/ontos. Clone it, follow the Quick Start, enable demo mode to see sample data, and start exploring. The User Guide is comprehensive."

### Q: What existing technology inspired Ontos the most?

**A:** "Honestly, knowledge graphs and the semantic web vision. The idea that meaning should be machine-understandable, that relationships matter as much as entities, that shared vocabularies enable interoperability—these ideas from the 2000s are finally practical at enterprise scale."

---

## Part 6: Closing Thoughts

### Host Closing Monologue

*"What strikes me about Ontos is that it's not trying to replace your data platform—it's trying to give it meaning. In a world where AI is increasingly how we interact with systems, having structured, semantic, machine-understandable metadata isn't a nice-to-have—it's essential.*

*The gap between technical data and business understanding has plagued enterprises for decades. Maybe ontological knowledge systems—the same technology that powers knowledge graphs and the semantic web—are finally ready to bridge that gap.*

*If you're struggling with data discovery, compliance, or just explaining to stakeholders what data you actually have, check out Ontos. It might just change how you think about data governance."*

---

## Demo Script Summary

For easy reference, here are the key demos to prepare:

| Demo | Duration | Key Showcase |
|------|----------|--------------|
| **Semantic Search** | 5 min | Finding 'customer email' through semantic links, not keywords |
| **AI Integration (MCP)** | 7 min | Claude discovering data and navigating the knowledge graph |
| **Contract Creation** | 8 min | Building a semantically-grounded contract with three-tier linking |
| **Compliance Automation** | 5 min | Running a policy that uses semantic understanding of PII |
| **Knowledge Graph Exploration** | 5 min | Navigating concepts, properties, and linked assets visually |

---

## Key Messages to Emphasize

1. **Semantic Gap**: The disconnect between technical data and business meaning is the core problem.

2. **Ontological Approach**: RDF/RDFS-based semantic modeling enables machine-understandable meaning.

3. **Three-Tier Linking**: Contract → Schema → Property semantic links at every level of granularity.

4. **AI-Ready**: MCP integration makes the semantic layer accessible to AI assistants.

5. **Standards-Based**: ODCS, ODPS, MCP, RDF/RDFS—no vendor lock-in.

6. **Progressive Adoption**: Start with datasets, grow into full semantic governance.

7. **Practical Value**: Better search, automated compliance, trusted data products.

---

## Suggested Promotional Clips

For social media/podcast highlights:

1. **"The Semantic Gap"** (30 sec): "A data engineer sees `customers_v2`. A business user asks 'Where's our customer master data?'"

2. **"Ontologies in Practice"** (45 sec): "When you search for 'customer email,' the system understands email is a property of Customer..."

3. **"AI Meets Data Governance"** (60 sec): "The AI isn't guessing. It's querying our knowledge graph. This is ontological reasoning in action."

4. **"Data as a Product"** (45 sec): "A Data Contract is like an API for data—with schema, quality rules, SLOs, and semantic links."

5. **"The Trust Chain"** (30 sec): "Every data product is grounded in a shared understanding of what the data means."

---

*Document Version: 1.0*
*Created: January 2026*
*For: AI-Focused Podcast Episode on Ontos and Ontological Knowledge Systems*



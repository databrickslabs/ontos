# PRD: CDM / vertical onboarding helpers (e.g. telco)

> **Feature request — feedback wanted.** This document is meant to be pasted into a GitHub issue (or linked from one) so maintainers and users can comment on scope, priorities, and real-world CDM sources. Please comment with: your industry, how you represent CDM today (UC only, MDM tool, spreadsheets), and whether you need in-app wizards, jobs-only automation, or file-based packs first.

## Problem Statement

Telco and other Customer Data Management (CDM)–heavy organizations need a **governed business catalog** view of customer data: core entities (Customer, Account, Subscription, Product, Interaction, Invoice, Consent, etc.), links to physical tables and data products, and governance metadata (ownership, quality, PII/consent context, process notes such as match/merge or survivorship). Ontos already supports much of this through Unity Catalog, semantic models, data products, glossaries/concepts, quality items, and relationships—but **onboarding is fragmented**. Customers must discover and combine UC tag–based bulk import, YAML/JSON batch data products, RDF/taxonomy import, asset bulk import (CSV/XLSX), and schema import without a **guided, repeatable path** tailored to CDM. That raises time-to-value and makes certification (readiness) harder.

## Solution

Introduce a **CDM / vertical onboarding** capability that **composes existing primitives** rather than replacing them:

1. **Vertical packs** (telco first, others later): starter semantic content (concepts/relationships), recommended UC tag patterns for domains/products/contracts, optional batch data product templates, and a **readiness checklist** (e.g. unlinked concepts, missing owners, assets without products).
2. **Guided onboarding** (UI and/or documented job flow): steps such as choose vertical → apply or import ontology pack → configure or confirm UC discovery patterns → preview/dry-run → execute sync → surface gaps and next actions.
3. **Optional structured seed** (scope TBD): a single documented **entity catalog** CSV/JSON format to bootstrap concepts and external system references, avoiding one-off connectors for every MDM vendor in v1.

Access control, masking, and row-level security remain **Unity Catalog’s responsibility**; Ontos surfaces and documents policy context alongside business metadata.

## User Stories

1. As a **data governance lead**, I want a **clear onboarding entry point** for the customer/CDM domain, so that my team does not have to hunt for every import feature separately.
2. As a **governance lead**, I want **recommended UC tag conventions** aligned to the pack, so that bulk import from UC stays consistent across teams.
3. As a **platform admin**, I want to **run or schedule** UC-oriented bulk import with sensible defaults for CDM, so that new tagged assets appear in Ontos reliably.
4. As a **semantic modeler**, I want a **starter ontology** for telco customer entities, so that we do not start from an empty graph.
5. As a **semantic modeler**, I want to **import or extend** that pack using existing RDF/Turtle or industry-ontology flows, so that we stay aligned with current Ontos capabilities.
6. As a **data product owner**, I want **templated batch creation** of core products (e.g. Customer 360, Subscription 360), so that ownership, SLAs, and descriptions stay consistent.
7. As a **data product owner**, I want **concepts linked to UC-backed assets** after onboarding, so that discovery is business-first.
8. As a **data steward**, I want **prompted slots** for CDM process documentation (match/merge, survivorship, enrichment), so that curated tables are explainable in the catalog.
9. As a **compliance stakeholder**, I want **PII, consent, and purpose** visible in the same journey as products and terms, so that usage rules are not divorced from the dataset list.
10. As a **downstream analyst**, I want to **find certified customer-domain products** via search and hierarchy, so that I use trusted assets.
11. As an **implementer**, I want a **readiness report** after onboarding, so that we know what still blocks certification.
12. As an **implementer**, I want **dry-run or preview** before applying bulk changes, so that we avoid accidental catalog pollution.
13. As a **vendor or partner**, I want the design to support **additional vertical packs** without forking the app, so that utilities, insurance, or retail can reuse the same mechanism.
14. As an **admin**, I want **auditable onboarding actions**, so that enterprise change-control requirements are met.
15. As an **operator**, I want **idempotent** imports and clear conflict behavior, so that retries are safe.
16. As a **power user**, I want **documented escape hatches** to raw APIs (YAML products, RDF upload, asset CSV), so that automation is not limited to the wizard.
17. As a **migrator with a legacy MDM export**, I want a **minimal, documented interchange** (optional), so that we can seed metadata without full vendor API support in v1.
18. As a **product owner**, I want **feedback hooks** (what worked, what was missing), so that packs and wizards improve over time.

## Implementation Decisions

### Composition over new core engines

Reuse UC bulk import workflows, `DataProductsManager` batch YAML/JSON, semantic model / collection RDF import, asset bulk import, and schema import where applicable. New code should favor **orchestration, pack metadata, and UI** over duplicate validation or persistence paths.

### Vertical packs as data, not scattered conditionals

Packs bundle: ontology fragments or import instructions, default tag patterns, optional product YAML templates, readiness rule definitions, and user-facing copy. Packs are versioned and selectable.

### Wizard vs job-only

Initial delivery may be **documentation + job parameters + pack files** before a full UI wizard, or the reverse—product decision. Backend contracts should allow both (same pack resolved server-side).

### MDM / external interchange

If included, v1 targets **one** optional CSV/JSON schema for “entity catalog” (name, description, external system, identifier type, optional parent entity)—not native APIs to each MDM vendor unless explicitly added later.

### Readiness

Either extend existing readiness-style checks or add CDM-specific rules driven by pack configuration; avoid one-off hard-coded checks per customer.

### Security and limits

File uploads for packs or entity catalogs follow existing patterns: size limits, permission checks, audit logging for mutations.

## Testing Decisions

### Philosophy

Tests assert **observable outcomes**: created/updated products, import summaries, linked concepts, readiness flags, permission denials—not wizard implementation details.

### Suggested coverage

- Pack loading and validation (missing files, bad version).
- Preset tag patterns produce expected discovery configuration (unit level where logic is pure).
- Idempotent second run behavior aligned with existing conflict strategies.
- Dry-run/preview returns stable diff without committing when supported.

### Prior art

Existing tests around bulk import, batch data product upload, and route-level integration for file uploads and permissions.

## Out of Scope

- **Executing** MDM match-merge, survivorship, or golden-record computation inside Ontos.
- Replacing Unity Catalog for **enforcement** of access, masking, or row filters (documentation and links only).
- Native real-time sync from every operational CRM or CDP.
- Unlimited vendor-specific MDM API connectors in v1 unless explicitly rescoped.

## Further Notes

- **Marketplace positioning**: CDM in a business catalog aligns with Ontos as a Unity Catalog–native business catalog; packs make that story operational for vertical GTM.
- **Open questions for comments**: (1) MVP: wizard-only, jobs + docs only, or both? (2) Is telco-only v1 acceptable or must v1 be vertical-agnostic with telco as the first pack? (3) Is a minimal MDM CSV in v1 essential or defer to v2?
- **Using this doc**: Create a GitHub issue titled e.g. *Feature: CDM / vertical onboarding helpers*, paste the Problem + Solution + Open questions, and link to this file in the repo for the full PRD.

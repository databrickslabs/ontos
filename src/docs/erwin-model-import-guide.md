# Importing erwin Data Models

Ontos imports models from **erwin Data Modeler** in two layers:

- the **logical model** (entities, attributes, relationships, subtypes, domains) becomes **concepts** in a concept collection;
- the **physical model** (tables, columns, keys) becomes **draft data contracts**, bound to the Unity Catalog tables Ontos already knows.

Every import is staged first. You review a preview and choose the options, and nothing is written until you confirm. Importing a newer version of the same model later updates what the first import created; it does not duplicate it.

## Exporting the model from erwin

In erwin Data Modeler, open the model (from a file or from erwin Mart) and choose **File → Save As**. Pick **XML Files (\*.xml)** and the **XML Standard** format.

| Export format | Supported |
|---|---|
| XML Standard | Yes (recommended) |
| XML Repository Format | Yes; the extra derived properties are ignored |
| XML Standard with Min Info | Yes, with a warning: columns without a stated null option are imported as nullable unless they are part of the primary key |
| JSON | Not yet |
| Native `.erwin` file | No. Export to XML first |

The file can be up to 100 MiB (administrators can change this; see [Limits](#limits)).

## Running an import

1. Start the import from either place:
   - **Data Contracts → erwin model** imports contracts, plus concepts if you can edit concepts;
   - **Concepts → Define → Import → Import an erwin model** imports concepts only.
2. Drop the XML file. Ontos reads the model and opens the import page (**Model imports → *model name***).
3. Review the options, and choose **Update preview** after changing any of them.
4. Check the preview tabs. When it looks right, choose **Import**.

Concepts are written straight away. Contracts are written in the background, and the page and your notifications show the progress. The **Model imports** page lists your imports. Administrators see everyone's.

### Options

| Option | What it does |
|---|---|
| Concepts from the logical model | Import the logical layer into a concept collection. |
| Draft contracts from the physical model | Import the physical layer as draft contracts. |
| Subject areas | Import only the selected subject areas. With none selected, the whole model is imported. When contracts are grouped by subject area, the order of your selection decides which contract gets a table that is in several subject areas. |
| Concept collection | A new collection named after the model (the default), or an existing collection you can edit. A re-import uses the collection of the previous import. |
| One contract per | **Subject area** (default), **Owner / schema**, **Table**, or **Whole model**. Tables outside every subject area go into an *Unassigned* contract. |
| Source database | The dialect of the physical types. Normally read from the model; set it when erwin wrote a numeric code. |
| Migration mode | Replace the modeled physical types with Databricks types, e.g. Oracle `NUMBER(12,2)` → `DECIMAL(12,2)` and `VARCHAR2(n)` → `STRING`. The original type is kept as `erwin.sourcePhysicalType`. Use it when the model describes a legacy warehouse you are moving to Databricks. |
| Unity Catalog mapping | Map each erwin owner/schema to a UC `catalog.schema`, with *Any other owner* as the fallback. This is how tables find their UC table. |
| User-defined properties | Where each erwin UDP goes: a custom property (default), a tag, a column's classification, the column's critical-data-element flag, or nowhere. |
| Domain (Contracts tab) | The data domain of a new contract. |
| Unity Catalog table (Unity Catalog tab) | Override the UC table of a single erwin table. |

The options you choose are remembered for the next import of the same model.

### Preview tabs

- **Summary**: the model's size, and the concepts and contracts that will be created, changed, left unchanged or deprecated.
- **Concepts**: the new, changed and deprecated concepts.
- **Contracts**: one card per contract, showing what happens to it (*Create*, *Update draft*, *New version*, *Unchanged*), its tables and, on a re-import, what changed.
- **Unity Catalog**: for each table, the UC table it resolves to, plus its **drift**: modeled columns missing in UC, UC columns not in the model, and type and nullability differences.
- **Warnings**: anything Ontos had to guess or skip, such as a relationship without a type, a dangling reference, or tables not found in UC.

## What gets created

### Concepts (logical layer)

| erwin | Ontos concept |
|---|---|
| Entity | Class, with its definition and note; the physical name becomes a synonym |
| Attribute | Datatype property of its class, typed from the logical data type (or its domain) |
| Migrated (foreign key) attribute | No property of its own; the relationship represents it |
| Relationship | Object property from parent to child, named after the verb phrase ("Customer places Order") |
| Subtype relationship | Subclass of the supertype |
| Domain | Concept carrying the base type and valid values; the properties that use it link to it |
| Subject area | `erwin:subjectArea` annotation on its classes |

New concepts start as **Draft** and go through the normal review and publishing lifecycle. Each one remembers the erwin object it came from, so renaming an entity in erwin renames the concept rather than creating a new one.

### Contracts (physical layer)

| erwin | ODCS v3.1 contract |
|---|---|
| Table / view | Schema object: name = table name, physical name = UC table (when resolved), business name = entity name |
| Column | Property with the physical type, a logical type, business name and description |
| Primary key | `primaryKey` with its position; key columns are required |
| Null option | `required` |
| Single-column alternate key | `unique` |
| Foreign key | Relationship from the child columns to the parent columns, including composite keys |
| Default, domain, valid values, view SQL, multi-column alternate keys, UDPs | Custom properties `erwin.*` (or what the UDP mapping says) |

Every table and column links to its concept, so model lineage shows *Concept → Contract → UC table*, and a foreign key column links to the concept of the attribute it refers to. When tables of a contract differ from Unity Catalog, the contract gets an **erwin model drift** note in its metadata panel. The note is refreshed on every import and removed once the drift is gone.

The contract header shows **Source: erwin · *model*** with a link to the import that produced it.

Ontos never creates or changes anything in Unity Catalog. Tables that Ontos does not know yet get no physical name. Bring them in with the **Schema Importer**, then import the model again.

## Importing a newer version

Import the new export the same way. Ontos recognizes the model and shows what changed.

- **Concepts:** changes to existing concepts are saved as a new version of each concept. Concepts whose erwin object left the model are **deprecated**, never deleted. Concepts outside the selected subject areas, and concepts you created by hand in the same collection, are left alone.
- **Contracts:**
  - a draft contract is updated in place; custom properties you added yourself are kept;
  - a contract that is past draft (proposed, approved, certified, …) is not edited. Ontos creates a **new draft version** (e.g. 1.0.0 → 1.1.0) for review;
  - a contract whose content didn't change stays untouched.
- **Removed groups:** when every table of a contract has left the model, the contract is flagged **Removed from the model** and its owner is notified; you decide whether to deprecate it. This check only runs when the whole model is imported, not a selection of subject areas.

Re-imports change the label, definition and synonyms of a concept in the concept's history, and the new version also gets the model's current domain, range and erwin annotations.

## Permissions

- Importing concepts needs **Read/Write** on Semantic Models (Concepts).
- Importing contracts needs **Read/Write** on Data Contracts.
- Viewing import runs needs **Read** on either. You see your own runs; administrators of either feature see all runs.
- Only the person who uploaded a model can change the options of its run or confirm it.

## For administrators

### Limits

| Setting | Default | Meaning |
|---|---|---|
| `MODEL_IMPORT_MAX_BYTES` (environment) | 104857600 (100 MiB) | Largest accepted upload |
| Run expiry | 7 days | A previewed run that is not confirmed expires and its stored model is dropped |
| Concurrent runs | 2 per user, 1 per model | A second import of a model waits until the first finishes |
| Stuck runs | 30 minutes | A run that makes no progress for 30 minutes (e.g. after a server restart) is marked failed, which frees the model for a new import |

### Security

- Uploaded XML is parsed with DTDs, entity expansion and external references disabled, so XML bombs and external entity attacks are rejected.
- The upload is streamed to a temporary file and hashed (SHA-256). The parsed model is stored with the run, compressed, so a run can be confirmed without the file. Nothing is sent to Unity Catalog or any external system.
- Staging, confirming and failed parses are recorded in the audit trail.

### Not supported yet

- erwin JSON exports.
- A live **erwin Mart** connection, and a Unity Catalog volume drop zone that erwin's own automation exports into.
- Writing descriptions or constraints back to Unity Catalog, or exporting Ontos content back to erwin.

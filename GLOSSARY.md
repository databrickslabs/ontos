# Glossary

## Metadata Generation

**Metadata Generation**
The capability that produces LLM-authored metadata (in v1: descriptions) for Unity Catalog tables, views and columns, for human review before it reaches the catalog.
_Avoid_: metagen, dbxmetagen (that is the engine, not the feature), auto-documentation

**Generation Run**
One execution of Metadata Generation over a selected set of Unity Catalog objects, with its options, outcome and the Description Suggestions it produced.
_Avoid_: job, metagen run

**Description Suggestion**
A proposed description for exactly one table, view or column, together with the base text (the description it would replace at the time it was generated).
_Avoid_: proposal, generated comment, DDL

**Apply**
Writing an approved Description Suggestion to Unity Catalog, and to the matching Ontos Asset if one exists.
_Avoid_: push-down, sync, publish (publish already means marketplace publication)

**Conflict**
The state of a Description Suggestion whose base text no longer matches the description in Unity Catalog at the moment of Apply; it is not applied.
_Avoid_: stale suggestion
